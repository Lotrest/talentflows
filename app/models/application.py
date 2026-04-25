from sqlalchemy import String, Integer, Boolean, JSON, DateTime, ForeignKey, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import uuid


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_user_status", "user_id", "status"),
        Index("ix_applications_user_sent_at", "user_id", "sent_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    vacancy_id: Mapped[str] = mapped_column(String, ForeignKey("vacancies.id"), nullable=False)

    status: Mapped[str] = mapped_column(String, default="draft")
    # draft → sent → viewed → replied → interview → offer | rejected

    cover_letter: Mapped[str | None] = mapped_column(Text)
    cover_letter_tone: Mapped[str | None] = mapped_column(String)  # professional | friendly | concise

    hh_application_id: Mapped[str | None] = mapped_column(String)  # ID отклика в HH.ru

    sent_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    rejection_reason: Mapped[str | None] = mapped_column(String)
    employer_feedback: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="applications")
    vacancy: Mapped["Vacancy"] = relationship("Vacancy", back_populates="application")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="application")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id: Mapped[str] = mapped_column(String, ForeignKey("applications.id"), nullable=False)

    role: Mapped[str] = mapped_column(String, nullable=False)  # employer | candidate | ai_draft
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # AI draft lifecycle
    is_approved: Mapped[bool | None] = mapped_column(Boolean)
    approved_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    sent_to_hh: Mapped[bool] = mapped_column(Boolean, default=False)

    hh_message_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application: Mapped["Application"] = relationship("Application", back_populates="messages")
