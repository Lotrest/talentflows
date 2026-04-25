from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from app.core.config import settings


def create_access_token(subject: Any) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    data = {"sub": str(subject), "exp": expire}
    return jwt.encode(data, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload.get("sub")
    except JWTError:
        return None
