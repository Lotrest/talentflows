from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.models.user import User
from app.models.vacancy import Vacancy
from app.models.application import Application
from app.services.rate_limiter import get_ai_usage
from app.api.v1.deps import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])

DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


@router.get("/summary")
async def get_summary(
    days: int = Query(7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    vacancies_found = (await db.execute(
        select(func.count()).where(Vacancy.user_id == current_user.id, Vacancy.found_at >= since)
    )).scalar_one()

    sent = (await db.execute(
        select(func.count()).where(
            Application.user_id == current_user.id,
            Application.sent_at >= since,
        )
    )).scalar_one()

    replied = (await db.execute(
        select(func.count()).where(
            Application.user_id == current_user.id,
            Application.replied_at >= since,
        )
    )).scalar_one()

    avg_score = (await db.execute(
        select(func.avg(Vacancy.score)).where(
            Vacancy.user_id == current_user.id,
            Vacancy.score.isnot(None),
        )
    )).scalar_one()

    active_dialogs = (await db.execute(
        select(func.count()).where(
            Application.user_id == current_user.id,
            Application.status.in_(["replied", "interview"]),
        )
    )).scalar_one()

    ai_usage = await get_ai_usage(current_user.id, current_user.plan)

    return {
        "vacancies_found": vacancies_found,
        "sent": sent,
        "replied": replied,
        "conversion_pct": round(replied / sent * 100, 1) if sent else 0,
        "avg_score": round(avg_score or 0),
        "active_dialogs": active_dialogs,
        "ai_usage": ai_usage,
        "days": days,
    }


@router.get("/weekly")
async def get_weekly(
    days: int = Query(7, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = []
    for i in range(days):
        day_start = now - timedelta(days=(days - 1 - i))
        day_start = day_start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        sent = (await db.execute(
            select(func.count()).where(
                Application.user_id == current_user.id,
                Application.sent_at >= day_start,
                Application.sent_at < day_end,
            )
        )).scalar_one()

        replied = (await db.execute(
            select(func.count()).where(
                Application.user_id == current_user.id,
                Application.replied_at >= day_start,
                Application.replied_at < day_end,
            )
        )).scalar_one()

        found = (await db.execute(
            select(func.count()).where(
                Vacancy.user_id == current_user.id,
                Vacancy.found_at >= day_start,
                Vacancy.found_at < day_end,
            )
        )).scalar_one()

        result.append({
            "day": DAYS_RU[day_start.weekday()],
            "date": day_start.strftime("%d.%m"),
            "sent": sent,
            "replied": replied,
            "found": found,
        })
    return result


@router.get("/platforms")
async def get_platforms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    platform_rows = (await db.execute(
        select(Vacancy.platform, func.count().label("vacancies"))
        .where(Vacancy.user_id == current_user.id)
        .group_by(Vacancy.platform)
    )).all()

    results = []
    for platform, vac_count in platform_rows:
        sent = (await db.execute(
            select(func.count()).select_from(Application).join(
                Vacancy, Vacancy.id == Application.vacancy_id
            ).where(
                Application.user_id == current_user.id,
                Vacancy.platform == platform,
                Application.status.in_(["sent", "viewed", "replied", "interview", "offer"]),
            )
        )).scalar_one()

        replied = (await db.execute(
            select(func.count()).select_from(Application).join(
                Vacancy, Vacancy.id == Application.vacancy_id
            ).where(
                Application.user_id == current_user.id,
                Vacancy.platform == platform,
                Application.status.in_(["replied", "interview", "offer"]),
            )
        )).scalar_one()

        results.append({
            "platform": platform,
            "vacancies": vac_count,
            "sent": sent,
            "replied": replied,
            "conversion": f"{round(replied / sent * 100, 1)}%" if sent else "—",
        })

    return results


@router.get("/top-companies")
async def get_top_companies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_rows = (await db.execute(
        select(Vacancy.company, func.avg(Vacancy.score).label("avg_score"))
        .where(Vacancy.user_id == current_user.id, Vacancy.score.isnot(None))
        .group_by(Vacancy.company)
        .order_by(func.avg(Vacancy.score).desc())
        .limit(5)
    )).all()

    results = []
    for company, avg_score in company_rows:
        sent = (await db.execute(
            select(func.count()).select_from(Application).join(
                Vacancy, Vacancy.id == Application.vacancy_id
            ).where(
                Application.user_id == current_user.id,
                Vacancy.company == company,
            )
        )).scalar_one()

        replied = (await db.execute(
            select(func.count()).select_from(Application).join(
                Vacancy, Vacancy.id == Application.vacancy_id
            ).where(
                Application.user_id == current_user.id,
                Vacancy.company == company,
                Application.status.in_(["replied", "interview", "offer"]),
            )
        )).scalar_one()

        results.append({
            "company": company,
            "score": round(avg_score),
            "sent": sent,
            "replied": replied,
        })

    return results


@router.get("/funnel")
async def get_funnel(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    found = (await db.execute(
        select(func.count()).where(Vacancy.user_id == current_user.id)
    )).scalar_one()

    sent = (await db.execute(
        select(func.count()).where(
            Application.user_id == current_user.id,
            Application.status.in_(["sent", "viewed", "replied", "interview", "offer", "rejected"]),
        )
    )).scalar_one()

    viewed = (await db.execute(
        select(func.count()).where(
            Application.user_id == current_user.id,
            Application.status.in_(["viewed", "replied", "interview", "offer"]),
        )
    )).scalar_one()

    replied = (await db.execute(
        select(func.count()).where(
            Application.user_id == current_user.id,
            Application.status.in_(["replied", "interview", "offer"]),
        )
    )).scalar_one()

    interview = (await db.execute(
        select(func.count()).where(
            Application.user_id == current_user.id,
            Application.status.in_(["interview", "offer"]),
        )
    )).scalar_one()

    return [
        {"label": "Найдено", "val": found, "pct": 100},
        {"label": "Отправлено", "val": sent, "pct": round(sent / found * 100, 1) if found else 0},
        {"label": "Просмотрено", "val": viewed, "pct": round(viewed / found * 100, 1) if found else 0},
        {"label": "Ответили", "val": replied, "pct": round(replied / found * 100, 1) if found else 0},
        {"label": "Интервью", "val": interview, "pct": round(interview / found * 100, 1) if found else 0},
    ]


@router.get("/rejections")
async def get_rejections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application).where(
            Application.user_id == current_user.id,
            Application.status == "rejected",
        )
    )
    rejections = result.scalars().all()

    reasons: dict[str, int] = {}
    for app in rejections:
        r = app.rejection_reason or "Причина не указана"
        reasons[r] = reasons.get(r, 0) + 1

    total = len(rejections)
    breakdown = [
        {"reason": r, "count": c, "pct": round(c / total * 100) if total else 0}
        for r, c in sorted(reasons.items(), key=lambda x: -x[1])
    ]

    return {"total": total, "breakdown": breakdown}
