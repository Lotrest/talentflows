import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from app.core.database import get_db
from app.models.user import User
from app.models.vacancy import Vacancy
from app.models.application import Application, Message
from app.models.platform_connection import PlatformConnection
from app.schemas.application import (
    CoverLetterRequest, CoverLetterOut, ApplicationOut, MessageOut, ApproveMessageRequest
)
from app.services import openai_service as ai_service
from app.services.platforms.registry import get_platform_adapter
from app.services.platforms.oauth import ensure_fresh_token
from app.services.rate_limiter import check_ai_rate_limit
from app.api.v1.deps import get_current_user

router = APIRouter(prefix="/applications", tags=["applications"])


async def _get_connection(db: AsyncSession, user_id: str, platform: str) -> PlatformConnection | None:
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == platform,
        )
    )
    return result.scalar_one_or_none()


@router.get("", response_model=list[ApplicationOut])
async def list_applications(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Application)
        .where(Application.user_id == current_user.id)
        .options(selectinload(Application.vacancy))
    )
    if status:
        query = query.where(Application.status == status)
    query = query.order_by(Application.created_at.desc())
    items = (await db.execute(query)).scalars().all()
    return list(items)


@router.post("/generate-letter", response_model=CoverLetterOut)
async def generate_cover_letter(
    req: CoverLetterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_ai_rate_limit(current_user.id, current_user.plan)

    result = await db.execute(
        select(Vacancy).where(Vacancy.id == req.vacancy_id, Vacancy.user_id == current_user.id)
    )
    vacancy = result.scalar_one_or_none()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    letter = await ai_service.generate_cover_letter(
        vacancy_title=vacancy.title,
        company=vacancy.company,
        description=vacancy.description or "",
        skills_required=vacancy.skills_required or [],
        user_skills=current_user.skills or [],
        user_experience=current_user.experience_years,
        tone=req.tone or current_user.tone,
        salary_from=current_user.salary_from,
        salary_to=current_user.salary_to,
        include_salary=current_user.include_salary,
        personalize=current_user.personalize,
        custom_instructions=current_user.custom_instructions,
    )
    return CoverLetterOut(cover_letter=letter, tone=req.tone or current_user.tone)


@router.post("/{vacancy_id}/apply", response_model=ApplicationOut)
async def apply_to_vacancy(
    vacancy_id: str,
    cover_letter: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Vacancy).where(Vacancy.id == vacancy_id, Vacancy.user_id == current_user.id)
    )
    vacancy = result.scalar_one_or_none()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    existing = await db.execute(
        select(Application).where(
            Application.vacancy_id == vacancy_id,
            Application.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already applied")

    platform_application_id = None
    adapter = get_platform_adapter(vacancy.platform)
    if adapter:
        connection = await _get_connection(db, current_user.id, vacancy.platform)
        if await adapter.is_connected(connection):
            if adapter.supports_oauth:
                await ensure_fresh_token(connection, adapter, db)
            resume_id = (connection.meta or {}).get("resume_id", "")
            try:
                api_result = await adapter.apply_to_vacancy(
                    connection=connection,
                    vacancy_id=vacancy.external_id,
                    resume_id=resume_id,
                    cover_letter=cover_letter,
                )
                platform_application_id = str(api_result.get("id", "")) or None
            except Exception:
                pass

    application = Application(
        user_id=current_user.id,
        vacancy_id=vacancy_id,
        cover_letter=cover_letter,
        cover_letter_tone=current_user.tone,
        status="sent",
        sent_at=datetime.now(timezone.utc),
        hh_application_id=platform_application_id,
    )
    db.add(application)
    vacancy.is_applied = True
    vacancy.status = "applied"
    await db.commit()
    await db.refresh(application)
    logger.info(
        "applied: user=%s vacancy=%s platform=%s hh_application_id=%s",
        current_user.id, vacancy_id, vacancy.platform, platform_application_id,
    )
    return application


@router.get("/{application_id}/messages", response_model=list[MessageOut])
async def get_messages(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app_result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
        )
    )
    application = app_result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    msgs = await db.execute(
        select(Message).where(Message.application_id == application_id).order_by(Message.created_at)
    )
    return list(msgs.scalars().all())


@router.post("/{application_id}/draft-reply", response_model=MessageOut)
async def draft_reply(
    application_id: str,
    employer_message: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_ai_rate_limit(current_user.id, current_user.plan)

    app_result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
        )
    )
    application = app_result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    vacancy_result = await db.execute(select(Vacancy).where(Vacancy.id == application.vacancy_id))
    vacancy = vacancy_result.scalar_one_or_none()

    history_result = await db.execute(
        select(Message).where(Message.application_id == application_id).order_by(Message.created_at)
    )
    history = [{"role": m.role, "content": m.content} for m in history_result.scalars().all()]

    employer_msg = Message(
        application_id=application_id,
        role="employer",
        content=employer_message,
        sent_to_hh=True,
    )
    db.add(employer_msg)

    draft_text = await ai_service.draft_reply(
        employer_message=employer_message,
        vacancy_title=vacancy.title if vacancy else "",
        company=vacancy.company if vacancy else "",
        conversation_history=history,
        tone=current_user.tone,
        custom_instructions=current_user.custom_instructions,
    )

    draft_msg = Message(
        application_id=application_id,
        role="ai_draft",
        content=draft_text,
    )
    db.add(draft_msg)
    await db.commit()
    await db.refresh(draft_msg)
    return draft_msg


@router.post("/messages/approve", response_model=MessageOut)
async def approve_message(
    req: ApproveMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Message).where(Message.id == req.message_id))
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    app_result = await db.execute(select(Application).where(Application.id == message.application_id))
    application = app_result.scalar_one_or_none()
    if not application or application.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    message.is_approved = True
    message.approved_at = datetime.now(timezone.utc)
    message.role = "candidate"

    if req.send_immediately and application.hh_application_id:
        vacancy_result = await db.execute(select(Vacancy).where(Vacancy.id == application.vacancy_id))
        vacancy = vacancy_result.scalar_one_or_none()
        if vacancy:
            adapter = get_platform_adapter(vacancy.platform)
            connection = await _get_connection(db, current_user.id, vacancy.platform)
            if adapter and await adapter.is_connected(connection):
                if adapter.supports_oauth:
                    await ensure_fresh_token(connection, adapter, db)
                try:
                    await adapter.send_message(
                        connection=connection,
                        negotiation_id=application.hh_application_id,
                        message=message.content,
                    )
                    message.sent_to_hh = True
                except Exception:
                    pass

    await db.commit()
    await db.refresh(message)
    return message
