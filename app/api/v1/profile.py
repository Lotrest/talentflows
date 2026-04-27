import logging
import httpx
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.user import User
from app.models.platform_connection import PlatformConnection
from app.schemas.user import UserProfile, UserToneSettings, UserProfileOut, ResumeInfo
from app.services.platforms.registry import get_platform_adapter
from app.services.platforms.oauth import ensure_fresh_token
from app.api.v1.deps import get_current_user

router = APIRouter(prefix="/profile", tags=["profile"])

RESUME_UPLOAD_DIR = Path(os.environ.get("RESUME_UPLOAD_DIR", "/var/uploads/resumes"))
ALLOWED_MIME = {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_RESUME_SIZE = 5 * 1024 * 1024  # 5 MB


@router.get("", response_model=UserProfileOut)
async def get_profile(current_user: User = Depends(get_current_user)):
    data = UserProfileOut.model_validate(current_user)
    if current_user.resume_filename and current_user.resume_uploaded_at:
        data.resume = ResumeInfo(
            filename=current_user.resume_filename,
            uploaded_at=current_user.resume_uploaded_at,
        )
    return data


@router.patch("/search")
async def update_search_settings(
    data: UserProfile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(current_user, field, value)
    await db.commit()
    return {"ok": True}


@router.patch("/tone")
async def update_tone_settings(
    data: UserToneSettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for field, value in data.model_dump().items():
        setattr(current_user, field, value)
    await db.commit()
    return {"ok": True}


@router.post("/resume")
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Only PDF or DOCX files are allowed")

    content = await file.read()
    if len(content) > MAX_RESUME_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 5 MB limit")

    user_dir = RESUME_UPLOAD_DIR / current_user.id
    user_dir.mkdir(parents=True, exist_ok=True)

    # Remove old file if exists
    if current_user.resume_path:
        old = Path(current_user.resume_path)
        if old.exists():
            old.unlink()

    ext = Path(file.filename).suffix.lower() if file.filename else ".pdf"
    dest = user_dir / f"resume{ext}"
    dest.write_bytes(content)

    current_user.resume_filename = file.filename
    current_user.resume_path = str(dest)
    current_user.resume_uploaded_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True, "filename": file.filename}


@router.delete("/resume")
async def delete_resume(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.resume_path:
        old = Path(current_user.resume_path)
        if old.exists():
            old.unlink()
    current_user.resume_filename = None
    current_user.resume_path = None
    current_user.resume_uploaded_at = None
    await db.commit()
    return {"ok": True}


@router.get("/resume/download")
async def download_resume(current_user: User = Depends(get_current_user)):
    if not current_user.resume_path:
        raise HTTPException(status_code=404, detail="No resume uploaded")
    path = Path(current_user.resume_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Resume file not found")
    return FileResponse(
        path=str(path),
        filename=current_user.resume_filename or "resume.pdf",
        media_type="application/octet-stream",
    )


@router.get("/{platform}/resumes")
async def get_platform_resumes(
    platform: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    adapter = get_platform_adapter(platform)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{platform}'")

    conn_result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == current_user.id,
            PlatformConnection.platform == platform,
        )
    )
    connection = conn_result.scalar_one_or_none()

    if not await adapter.is_connected(connection):
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' not connected")

    if adapter.supports_oauth:
        await ensure_fresh_token(connection, adapter, db)

    try:
        resumes = await adapter.get_resumes(connection)
    except NotImplementedError:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' does not support resume listing")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"{platform} API error: {e}")

    return [{"id": r.id, "title": r.title, "status": r.status, "url": r.url, "updated_at": r.updated_at} for r in resumes]


@router.post("/rejected-company")
async def add_rejected_company(
    company: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add company to stop-list. Future vacancies from this company will score 0."""
    companies = list(current_user.rejected_companies or [])
    if company not in companies:
        companies.append(company)
        current_user.rejected_companies = companies
        await db.commit()
    return {"ok": True, "rejected_companies": companies}


@router.delete("/rejected-company")
async def remove_rejected_company(
    company: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    companies = [c for c in (current_user.rejected_companies or []) if c != company]
    current_user.rejected_companies = companies
    await db.commit()
    return {"ok": True, "rejected_companies": companies}


@router.patch("/{platform}/settings")
async def update_platform_settings(
    platform: str,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update platform-specific settings (e.g. resume_id for HH)."""
    conn_result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == current_user.id,
            PlatformConnection.platform == platform,
        )
    )
    connection = conn_result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' not connected")

    if connection.meta is None:
        connection.meta = {}
    connection.meta = {**connection.meta, **data}
    await db.commit()
    return {"ok": True}
