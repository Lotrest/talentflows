from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.user import User
from app.models.platform_connection import PlatformConnection
from app.schemas.user import UserProfile, UserToneSettings, UserProfileOut
from app.services.platforms.registry import get_platform_adapter
from app.services.platforms.oauth import ensure_fresh_token
from app.api.v1.deps import get_current_user

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserProfileOut)
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


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
