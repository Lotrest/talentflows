import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.platform_connection import PlatformConnection
from app.services.platforms.base import PlatformAdapter

logger = logging.getLogger(__name__)


async def ensure_fresh_token(
    connection: PlatformConnection,
    adapter: PlatformAdapter,
    db: AsyncSession,
) -> str | None:
    """
    Refresh platform token if it expires within 5 minutes.
    Updates connection in-place and commits. Returns current access_token.
    """
    if not connection or not connection.access_token:
        return None
    if not connection.refresh_token:
        return connection.access_token

    expires_at = connection.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return connection.access_token

    try:
        data = await adapter.do_refresh_token(connection.refresh_token)
        connection.access_token = data["access_token"]
        connection.refresh_token = data.get("refresh_token", connection.refresh_token)
        expires_in = data.get("expires_in", 1209600)  # default 14 days
        connection.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        await db.commit()
    except Exception:
        logger.exception(
            "Token refresh failed for platform=%s user=%s — token may be expired, user needs to reconnect",
            getattr(connection, "platform", "?"),
            getattr(connection, "user_id", "?"),
        )

    return connection.access_token


async def upsert_connection(
    db: AsyncSession,
    user_id: str,
    platform: str,
    token_data: dict,
    platform_user: dict,
) -> PlatformConnection:
    """
    Create or update a PlatformConnection from OAuth token response.
    token_data: {access_token, refresh_token?, expires_in?}
    platform_user: {id, email, name}
    """
    from sqlalchemy import select

    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == platform,
        )
    )
    connection = result.scalar_one_or_none()

    if not connection:
        connection = PlatformConnection(user_id=user_id, platform=platform)
        db.add(connection)

    connection.access_token = token_data["access_token"]
    connection.refresh_token = token_data.get("refresh_token", connection.refresh_token)
    expires_in = token_data.get("expires_in", 86400)
    connection.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    connection.platform_user_id = platform_user.get("id")
    connection.platform_email = platform_user.get("email")
    if connection.meta is None:
        connection.meta = {}

    await db.commit()
    await db.refresh(connection)
    return connection
