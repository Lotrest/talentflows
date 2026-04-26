import logging
import asyncio
from fastapi import APIRouter, Depends, Query, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from app.core.database import get_db, AsyncSessionLocal
from app.models.user import User
from app.models.vacancy import Vacancy
from app.models.platform_connection import PlatformConnection
from app.schemas.vacancy import VacancyOut, VacancyListOut
from app.services import openai_service as ai_service
from app.services.platforms.registry import get_platform_adapter, list_supported_platforms
from app.services.platforms.oauth import ensure_fresh_token
from app.services.rate_limiter import check_ai_rate_limit
from app.api.v1.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vacancies", tags=["vacancies"])

# Maximum applies per day to avoid HH banning
DAILY_APPLY_LIMIT = 20
# Delay between HH API calls during scan (seconds)
HH_REQUEST_DELAY = 1.5


@router.get("", response_model=VacancyListOut)
async def list_vacancies(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sort: str = Query("score"),  # score | date
    min_score: int = Query(0, ge=0, le=100),
    status: str | None = Query(None),  # new | shown | approved | rejected | applied
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Vacancy).where(
        Vacancy.user_id == current_user.id,
        Vacancy.is_archived == False,
        Vacancy.score >= min_score if min_score > 0 else True,
    )
    if status:
        query = query.where(Vacancy.status == status)

    if sort == "score":
        query = query.order_by(Vacancy.score.desc().nullslast())
    else:
        query = query.order_by(Vacancy.found_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.offset((page - 1) * per_page).limit(per_page)
    items = (await db.execute(query)).scalars().all()

    # Mark fetched "new" vacancies as "shown"
    new_ids = [v.id for v in items if v.status == "new"]
    if new_ids:
        await db.execute(
            update(Vacancy).where(Vacancy.id.in_(new_ids)).values(status="shown")
        )
        await db.commit()

    return VacancyListOut(items=list(items), total=total, page=page, per_page=per_page)


@router.post("/scan")
async def scan_vacancies(
    background_tasks: BackgroundTasks,
    platform: str = Query("hh"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    adapter = get_platform_adapter(platform)
    if not adapter:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported platform '{platform}'. Available: {', '.join(list_supported_platforms())}",
        )

    conn_result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == current_user.id,
            PlatformConnection.platform == platform,
        )
    )
    connection = conn_result.scalar_one_or_none()

    if not await adapter.is_connected(connection):
        raise HTTPException(status_code=400, detail=f"{platform} not connected")
    if not current_user.keywords:
        raise HTTPException(status_code=400, detail="No keywords set in profile")

    background_tasks.add_task(_scan_and_score, current_user.id, platform)
    logger.info("scan started: user=%s platform=%s", current_user.id, platform)
    return {"ok": True, "message": "Scan started"}


@router.post("/{vacancy_id}/approve")
async def approve_vacancy(
    vacancy_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves vacancy — marks it ready for application generation."""
    result = await db.execute(
        select(Vacancy).where(Vacancy.id == vacancy_id, Vacancy.user_id == current_user.id)
    )
    vacancy = result.scalar_one_or_none()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if vacancy.status in ("applied", "rejected"):
        raise HTTPException(status_code=409, detail=f"Vacancy already {vacancy.status}")

    vacancy.status = "approved"
    await db.commit()
    logger.info("vacancy approved: user=%s vacancy=%s", current_user.id, vacancy_id)
    return {"ok": True, "status": "approved"}


@router.post("/{vacancy_id}/reject")
async def reject_vacancy(
    vacancy_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User skips vacancy — archives it."""
    result = await db.execute(
        select(Vacancy).where(Vacancy.id == vacancy_id, Vacancy.user_id == current_user.id)
    )
    vacancy = result.scalar_one_or_none()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    vacancy.status = "rejected"
    vacancy.is_archived = True
    await db.commit()
    logger.info("vacancy rejected: user=%s vacancy=%s", current_user.id, vacancy_id)
    return {"ok": True, "status": "rejected"}


@router.get("/{vacancy_id}", response_model=VacancyOut)
async def get_vacancy(
    vacancy_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Vacancy).where(Vacancy.id == vacancy_id, Vacancy.user_id == current_user.id)
    )
    vacancy = result.scalar_one_or_none()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return vacancy


async def _scan_and_score(user_id: str, platform: str):
    """Background task: fetch vacancies from platform, score with AI, save to DB."""
    logger.info("_scan_and_score start: user=%s platform=%s", user_id, platform)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            logger.warning("_scan_and_score: user %s not found", user_id)
            return

        adapter = get_platform_adapter(platform)
        if not adapter:
            logger.warning("_scan_and_score: no adapter for platform %s", platform)
            return

        conn_result = await db.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user_id,
                PlatformConnection.platform == platform,
            )
        )
        connection = conn_result.scalar_one_or_none()

        if not await adapter.is_connected(connection):
            logger.warning("_scan_and_score: %s not connected for user %s", platform, user_id)
            return

        if adapter.supports_oauth and connection:
            await ensure_fresh_token(connection, adapter, db)

        raw_query = (user.keywords or "").strip()
        logger.info("_scan_and_score: query=%r platform=%s user=%s", raw_query, platform, user_id)

        try:
            items = await adapter.search_vacancies(
                connection=connection,
                user=user,
                query=raw_query,
                per_page=50,
            )
        except Exception:
            logger.exception("_scan_and_score: search_vacancies failed for user %s", user_id)
            return

        logger.info("_scan_and_score: got %d vacancies for user %s", len(items), user_id)
        new_count = 0

        for item in items:
            existing = await db.execute(
                select(Vacancy).where(
                    Vacancy.external_id == item.external_id,
                    Vacancy.platform == platform,
                    Vacancy.user_id == user_id,
                )
            )
            if existing.scalar_one_or_none():
                continue

            vacancy = Vacancy(
                user_id=user_id,
                platform=platform,
                integration_mode=adapter.integration_mode,
                external_id=item.external_id,
                hh_id=item.external_id if platform == "hh" else None,
                title=item.title,
                company=item.company,
                salary_from=item.salary_from,
                salary_to=item.salary_to,
                salary_currency=item.salary_currency,
                city=item.city,
                work_format=item.work_format,
                url=item.url,
                status="new",
            )
            db.add(vacancy)
            new_count += 1

            # Jooble returns no descriptions/skills — AI scoring is useless, skip it
            if platform == "jooble":
                logger.debug("_scan_and_score: jooble vacancy saved without scoring '%s'", vacancy.title)
                continue

            try:
                await check_ai_rate_limit(user_id, user.plan)
                await asyncio.sleep(HH_REQUEST_DELAY)
                detail = await adapter.get_vacancy_detail(connection, item.external_id)
                vacancy.skills_required = detail.skills_required
                vacancy.description = detail.description[:2000] if detail.description else None

                score_result = await ai_service.score_vacancy(
                    vacancy_title=vacancy.title,
                    company=vacancy.company,
                    description=detail.description,
                    skills_required=detail.skills_required,
                    salary_from=vacancy.salary_from,
                    salary_to=vacancy.salary_to,
                    work_format=vacancy.work_format,
                    user_skills=user.skills or [],
                    user_salary_from=user.salary_from,
                    user_salary_to=user.salary_to,
                    user_work_formats=user.work_formats or [],
                    user_experience=user.experience_years,
                    target_role=getattr(user, "target_role", None),
                    rejected_companies=getattr(user, "rejected_companies", None) or [],
                )
                vacancy.score = score_result.get("score")
                vacancy.score_breakdown = score_result.get("breakdown")
                vacancy.score_explanation = score_result.get("explanation")

                # Only hide below threshold when AI actually scored it.
                # If AI was unavailable (ai_failed=True), keep status "new" so vacancies stay visible.
                threshold = getattr(user, "score_threshold", 60) or 60
                if not score_result.get("ai_failed"):
                    vacancy.status = "new" if (vacancy.score or 0) >= threshold else "scored"

                logger.debug(
                    "_scan_and_score: '%s' @ %s → score=%s status=%s",
                    vacancy.title, vacancy.company, vacancy.score, vacancy.status,
                )
            except Exception:
                logger.exception(
                    "_scan_and_score: failed to score vacancy %s for user %s",
                    item.external_id, user_id,
                )

        await db.commit()
        logger.info(
            "_scan_and_score done: user=%s new_vacancies=%d total_fetched=%d",
            user_id, new_count, len(items),
        )

        if new_count > 0:
            from app.services.email_service import send_new_vacancies_digest
            top_result = await db.execute(
                select(Vacancy)
                .where(Vacancy.user_id == user_id, Vacancy.status == "new")
                .order_by(Vacancy.score.desc().nullslast())
                .limit(3)
            )
            top_vacs = top_result.scalars().all()
            top_data = [
                {"title": v.title, "company": v.company, "salary_from": v.salary_from, "score": v.score}
                for v in top_vacs
            ]
            await send_new_vacancies_digest(user.email, user.name, new_count, top_data)
