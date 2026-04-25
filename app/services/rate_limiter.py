from app.core.redis import get_redis
from app.core.config import settings
from fastapi import HTTPException

PLAN_LIMITS = {
    "free": settings.rate_limit_free,
    "pro": settings.rate_limit_pro,
    "team": settings.rate_limit_team,
}


async def check_ai_rate_limit(user_id: str, plan: str) -> None:
    redis = await get_redis()
    key = f"rate_limit:ai:{user_id}:{_today()}"
    limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 86400)  # 24h TTL

    if current > limit:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit_exceeded", "limit": limit, "plan": plan},
        )


async def get_ai_usage(user_id: str, plan: str) -> dict:
    redis = await get_redis()
    key = f"rate_limit:ai:{user_id}:{_today()}"
    current = int(await redis.get(key) or 0)
    limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    return {"used": current, "limit": limit, "remaining": max(0, limit - current)}


def _today() -> str:
    from datetime import date
    return date.today().isoformat()
