import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import create_access_token
from app.core.config import settings
from app.models.user import User
from app.models.platform_connection import PlatformConnection
from app.schemas.user import UserOut
from app.services.platforms.registry import get_platform_adapter
from app.services.platforms.oauth import upsert_connection
from app.services.email_service import (
    generate_otp,
    otp_expires_at,
    send_verification_code,
)
from app.api.v1.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_PLATFORM_CONFIGURED = {
    "hh": lambda: bool(settings.hh_client_id and settings.hh_client_secret),
    "superjob": lambda: bool(settings.superjob_client_id and settings.superjob_client_secret),
    "rabota_ru": lambda: bool(settings.rabota_ru_client_id and settings.rabota_ru_client_secret),
    "avito": lambda: bool(settings.avito_client_id and settings.avito_client_secret),
    "linkedin": lambda: bool(settings.linkedin_client_id and settings.linkedin_client_secret),
}


# ---------------------------------------------------------------------------
# Email / Password auth
# ---------------------------------------------------------------------------

class EmailRegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class EmailVerifyIn(BaseModel):
    email: EmailStr
    code: str


class EmailLoginIn(BaseModel):
    email: EmailStr
    password: str


class EmailResendIn(BaseModel):
    email: EmailStr


@router.post("/email/register", summary="Register with email + password")
async def email_register(data: EmailRegisterIn, db: AsyncSession = Depends(get_db)):
    """Create account, send 6-digit OTP to email. Call /email/verify next."""
    if len(data.password) < 8:
        raise HTTPException(status_code=422, detail="Пароль должен быть минимум 8 символов")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    code = generate_otp()
    expires = otp_expires_at()

    if user:
        if user.is_verified and user.hashed_password:
            raise HTTPException(status_code=409, detail="Email уже зарегистрирован")
        # Re-registration attempt or unverified — update code
        user.hashed_password = pwd_context.hash(data.password)
        user.name = data.name or user.name
        user.email_code = code
        user.email_code_expires = expires
    else:
        user = User(
            email=data.email,
            name=data.name,
            hashed_password=pwd_context.hash(data.password),
            is_verified=False,
            email_code=code,
            email_code_expires=expires,
        )
        db.add(user)

    await db.commit()

    sent = await send_verification_code(data.email, code)
    if not sent:
        logger.warning("OTP email not sent for %s (SMTP not configured)", data.email)

    return {"ok": True, "message": "Код подтверждения отправлен на почту"}


@router.post("/email/verify", summary="Verify OTP, receive JWT")
async def email_verify(data: EmailVerifyIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not user.email_code:
        raise HTTPException(status_code=400, detail="Код не найден — запросите новый")

    if datetime.now(timezone.utc) > user.email_code_expires.replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=400, detail="Код истёк — запросите новый")

    if user.email_code != data.code:
        raise HTTPException(status_code=400, detail="Неверный код")

    user.is_verified = True
    user.email_code = None
    user.email_code_expires = None
    await db.commit()

    token = create_access_token(user.id)
    logger.info("email_verify: user=%s verified", user.id)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/email/login", summary="Login with email + password")
async def email_login(data: EmailLoginIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    if not pwd_context.verify(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    if not user.is_verified:
        raise HTTPException(
            status_code=403,
            detail="Email не подтверждён. Проверьте почту или запросите новый код.",
        )

    token = create_access_token(user.id)
    logger.info("email_login: user=%s", user.id)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/email/resend", summary="Resend OTP code")
async def email_resend(data: EmailResendIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        # Don't reveal whether email exists
        return {"ok": True, "message": "Если такой email зарегистрирован — код выслан"}

    if user.is_verified:
        raise HTTPException(status_code=400, detail="Email уже подтверждён")

    code = generate_otp()
    user.email_code = code
    user.email_code_expires = otp_expires_at()
    await db.commit()

    await send_verification_code(data.email, code)
    return {"ok": True, "message": "Код выслан повторно"}


# ---------------------------------------------------------------------------
# Platform OAuth
# ---------------------------------------------------------------------------

@router.get("/{platform}")
async def platform_oauth_start(platform: str):
    adapter = get_platform_adapter(platform)
    if not adapter or not adapter.supports_oauth:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' does not support OAuth")

    check = _PLATFORM_CONFIGURED.get(platform)
    if check and not check():
        raise HTTPException(status_code=503, detail=f"Platform '{platform}' OAuth keys not configured yet")

    state = secrets.token_urlsafe(16)
    url = adapter.get_oauth_url(state)
    return {"url": url, "state": state}


@router.get("/{platform}/callback")
async def platform_oauth_callback(
    platform: str,
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    adapter = get_platform_adapter(platform)
    if not adapter or not adapter.supports_oauth:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' does not support OAuth")

    try:
        token_data = await adapter.exchange_code(code)
    except Exception as e:
        logger.error("exchange_code failed: platform=%s type=%s repr=%s", platform, type(e).__name__, repr(e))
        raise HTTPException(status_code=400, detail=f"Failed to exchange {platform} code: {type(e).__name__}: {e}")

    try:
        platform_user = await adapter.get_platform_user_info(token_data["access_token"])
    except Exception as e:
        print(f"USER INFO ERROR type={type(e).__name__} str={str(e)!r} token_data={token_data}")
        raise HTTPException(status_code=400, detail=f"Failed to get {platform} user info: {e}")

    email = platform_user["email"]
    name = platform_user.get("name", "")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email=email, name=name, is_verified=True)
        db.add(user)
        await db.flush()

    await upsert_connection(db, user.id, platform, token_data, platform_user)

    jwt_token = create_access_token(user.id)
    redirect_url = f"{settings.frontend_url}/onboarding?token={jwt_token}"
    print("REDIRECT TO:", redirect_url)
    return RedirectResponse(url=redirect_url)


@router.delete("/{platform}")
async def disconnect_platform(
    platform: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == current_user.id,
            PlatformConnection.platform == platform,
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        await db.delete(connection)
        await db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
