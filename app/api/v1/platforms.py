from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.user import User
from app.models.platform_connection import PlatformConnection
from app.services.platforms.registry import _ADAPTERS
from app.api.v1.deps import get_current_user

router = APIRouter(prefix="/platforms", tags=["platforms"])

_PLATFORM_META = {
    "hh":        {"name": "HH.ru",       "phase": 1},
    "superjob":  {"name": "Superjob",    "phase": 2},
    "rabota_ru": {"name": "Работа.ру",   "phase": 3},
    "avito":     {"name": "Авито Работа","phase": 4},
    "linkedin":  {"name": "LinkedIn",    "phase": 5},
}


@router.get("")
async def list_platforms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conns_result = await db.execute(
        select(PlatformConnection).where(PlatformConnection.user_id == current_user.id)
    )
    connections = {c.platform: c for c in conns_result.scalars().all()}

    result = []
    for key, adapter in _ADAPTERS.items():
        meta = _PLATFORM_META.get(key, {})
        connection = connections.get(key)
        connected = await adapter.is_connected(connection)
        saved_resume_id = (connection.meta or {}).get("resume_id") if connection else None
        result.append({
            "key": key,
            "name": meta.get("name", key),
            "phase": meta.get("phase", 99),
            "integration_mode": adapter.integration_mode,
            "supports_oauth": adapter.supports_oauth,
            "connected": connected,
            "saved_resume_id": saved_resume_id,
        })
    result.sort(key=lambda x: x["phase"])
    return result
