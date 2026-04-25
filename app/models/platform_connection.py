import uuid
from sqlalchemy import String, DateTime, JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PlatformConnection(Base):
    __tablename__ = "platform_connections"
    __table_args__ = (UniqueConstraint("user_id", "platform", name="uq_user_platform"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # hh | superjob | rabota_ru | avito

    access_token: Mapped[str | None] = mapped_column(String)
    refresh_token: Mapped[str | None] = mapped_column(String)
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    platform_user_id: Mapped[str | None] = mapped_column(String)
    platform_email: Mapped[str | None] = mapped_column(String)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # resume_id and other platform-specific data

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
