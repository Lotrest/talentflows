"""
Background scheduler:
- auto_scan_job  — every N hours: fetch new vacancies for all users with HH connected
- apply_worker   — every 5 min:  process APPROVED vacancies through APPLYING → APPLIED/ERROR
"""
import asyncio
import logging
import random
from datetime import datetime, timezone, date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.vacancy import Vacancy
from app.models.application import Application
from app.models.platform_connection import PlatformConnection

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Auto-scan: fetch new vacancies for all eligible users
# ---------------------------------------------------------------------------

async def _auto_scan_all_users():
    logger.info("auto_scan: starting")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.is_active == True,
                User.keywords != None,
                User.keywords != "",
            )
        )
        users = result.scalars().all()

    logger.info("auto_scan: %d users to scan", len(users))

    for user in users:
        async with AsyncSessionLocal() as db:
            conn_result = await db.execute(
                select(PlatformConnection).where(
                    PlatformConnection.user_id == user.id,
                    PlatformConnection.platform == "hh",
                )
            )
            if not conn_result.scalar_one_or_none():
                continue

        try:
            from app.api.v1.vacancies import _scan_and_score
            await _scan_and_score(user.id, "hh")
        except Exception:
            logger.exception("auto_scan: failed for user %s", user.id)

    logger.info("auto_scan: done")


# ---------------------------------------------------------------------------
# Apply worker: APPROVED → APPLYING → APPLIED / ERROR
# ---------------------------------------------------------------------------

async def _count_applied_today(db, user_id: str) -> int:
    """Count how many vacancies this user applied to today."""
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    result = await db.execute(
        select(func.count()).where(
            Vacancy.user_id == user_id,
            Vacancy.status.in_(["applied", "applying"]),
            Vacancy.applied_at >= today_start,
        )
    )
    return result.scalar_one()


async def _was_applied_to_company_recently(db, user_id: str, company: str, days: int = 7) -> bool:
    """Prevent duplicate applications to same company within N days."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(func.count()).where(
            Vacancy.user_id == user_id,
            Vacancy.company.ilike(f"%{company}%"),
            Vacancy.status == "applied",
            Vacancy.applied_at >= cutoff,
        )
    )
    return result.scalar_one() > 0


async def _apply_worker():
    """
    For every user with APPROVED vacancies:
    1. Check daily apply limit
    2. Check same-company duplicate (7-day window)
    3. Atomically lock vacancy with APPLYING status
    4. Random delay 10-30s (anti-spam)
    5. Call platform API
    6. → APPLIED or ERROR
    """
    logger.info("apply_worker: starting cycle")

    async with AsyncSessionLocal() as db:
        # Get users who have approved vacancies
        result = await db.execute(
            select(Vacancy.user_id).where(Vacancy.status == "approved").distinct()
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        return

    logger.info("apply_worker: %d users have approved vacancies", len(user_ids))

    for user_id in user_ids:
        try:
            await _process_user_applies(user_id)
        except Exception:
            logger.exception("apply_worker: failed for user %s", user_id)


async def _process_user_applies(user_id: str):
    from app.services.platforms.registry import get_platform_adapter
    from app.services.platforms.oauth import ensure_fresh_token

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        applied_today = await _count_applied_today(db, user_id)
        limit = user.daily_apply_limit or 20

        if applied_today >= limit:
            logger.info(
                "apply_worker: user %s hit daily limit (%d/%d), skipping",
                user_id, applied_today, limit,
            )
            return

        # Get approved vacancies, oldest first
        vac_result = await db.execute(
            select(Vacancy)
            .where(Vacancy.user_id == user_id, Vacancy.status == "approved")
            .order_by(Vacancy.found_at.asc())
            .limit(limit - applied_today)
        )
        approved = vac_result.scalars().all()

    for vacancy in approved:
        async with AsyncSessionLocal() as db:
            # Re-fetch user for fresh state
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                return

            applied_today = await _count_applied_today(db, user_id)
            if applied_today >= (user.daily_apply_limit or 20):
                logger.info("apply_worker: user %s hit limit mid-batch, stopping", user_id)
                return

            # Same-company duplicate check
            if await _was_applied_to_company_recently(db, user_id, vacancy.company):
                logger.info(
                    "apply_worker: skipping '%s' — already applied to %s recently",
                    vacancy.title, vacancy.company,
                )
                continue

            # Atomic lock: set APPLYING only if still APPROVED (prevents race conditions)
            updated = await db.execute(
                update(Vacancy)
                .where(Vacancy.id == vacancy.id, Vacancy.status == "approved")
                .values(status="applying", applied_at=datetime.now(timezone.utc))
                .returning(Vacancy.id)
            )
            await db.commit()
            if not updated.fetchone():
                # Another worker got this vacancy first
                logger.debug("apply_worker: vacancy %s already locked, skipping", vacancy.id)
                continue

        # Anti-spam delay BEFORE each API call
        delay = random.uniform(10, 30)
        logger.info(
            "apply_worker: sleeping %.1fs before applying to '%s' @ %s",
            delay, vacancy.title, vacancy.company,
        )
        await asyncio.sleep(delay)

        # Actually apply
        async with AsyncSessionLocal() as db:
            vac_result = await db.execute(select(Vacancy).where(Vacancy.id == vacancy.id))
            vac = vac_result.scalar_one_or_none()
            if not vac:
                continue

            # Get existing application if user already generated a letter
            app_result = await db.execute(
                select(Application).where(
                    Application.vacancy_id == vacancy.id,
                    Application.user_id == user_id,
                )
            )
            application = app_result.scalar_one_or_none()
            cover_letter = application.cover_letter if application else ""

            adapter = get_platform_adapter(vac.platform)
            conn_result = await db.execute(
                select(PlatformConnection).where(
                    PlatformConnection.user_id == user_id,
                    PlatformConnection.platform == vac.platform,
                )
            )
            connection = conn_result.scalar_one_or_none()

            success = False
            error_msg = None

            if adapter and await adapter.is_connected(connection):
                if adapter.supports_oauth and connection:
                    await ensure_fresh_token(connection, adapter, db)

                resume_id = (connection.meta or {}).get("resume_id", "")
                try:
                    api_result = await adapter.apply_to_vacancy(
                        connection=connection,
                        vacancy_id=vac.external_id,
                        resume_id=resume_id,
                        cover_letter=cover_letter,
                    )
                    platform_application_id = str(api_result.get("id", "")) or None
                    success = True
                    logger.info(
                        "apply_worker: APPLIED '%s' @ %s (user=%s hh_id=%s)",
                        vac.title, vac.company, user_id, platform_application_id,
                    )

                    from app.services.email_service import send_application_sent
                    await send_application_sent(user.email, user.name, vac.title, vac.company)

                    # Update or create application record
                    if not application:
                        application = Application(
                            user_id=user_id,
                            vacancy_id=vac.id,
                            cover_letter=cover_letter,
                            cover_letter_tone=user.tone,
                            status="sent",
                            sent_at=datetime.now(timezone.utc),
                            hh_application_id=platform_application_id,
                        )
                        db.add(application)
                    else:
                        application.status = "sent"
                        application.sent_at = datetime.now(timezone.utc)
                        application.hh_application_id = platform_application_id

                except Exception as e:
                    error_msg = str(e)[:255]
                    logger.error(
                        "apply_worker: HH apply failed for '%s' @ %s: %s",
                        vac.title, vac.company, error_msg,
                    )
            else:
                error_msg = "Platform not connected"

            vac.status = "applied" if success else "error"
            vac.is_applied = success
            vac.apply_error = error_msg if not success else None
            if success:
                vac.applied_at = datetime.now(timezone.utc)

            await db.commit()


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler():
    scheduler.add_job(
        _auto_scan_all_users,
        trigger=IntervalTrigger(hours=settings.scan_interval_hours),
        id="auto_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _apply_worker,
        trigger=IntervalTrigger(minutes=5),
        id="apply_worker",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "scheduler: started (scan_interval=%dh, apply_worker=5min)",
        settings.scan_interval_hours,
    )


def stop_scheduler():
    scheduler.shutdown(wait=False)
    logger.info("scheduler: stopped")
