from sqlalchemy import String, Integer, Boolean, JSON, DateTime, ForeignKey, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import uuid


class Vacancy(Base):
    __tablename__ = "vacancies"
    __table_args__ = (
        Index("ix_vacancies_user_score", "user_id", "score"),
        Index("ix_vacancies_user_found_at", "user_id", "found_at"),
        Index("ix_vacancies_user_archived", "user_id", "is_archived"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Platform metadata
    platform: Mapped[str] = mapped_column(String, default="hh")
    integration_mode: Mapped[str] = mapped_column(String, default="official_api")
    external_id: Mapped[str | None] = mapped_column(String, index=True)

    # Data from platform API
    hh_id: Mapped[str | None] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str] = mapped_column(String, nullable=False)
    salary_from: Mapped[int | None] = mapped_column(Integer)
    salary_to: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str] = mapped_column(String, default="RUR")
    city: Mapped[str | None] = mapped_column(String)
    work_format: Mapped[str | None] = mapped_column(String)  # remote | office | hybrid
    experience_required: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    skills_required: Mapped[list] = mapped_column(JSON, default=list)
    url: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    # AI scoring
    score: Mapped[int | None] = mapped_column(Integer)  # 0-100
    score_breakdown: Mapped[dict | None] = mapped_column(JSON)  # {skills, salary, experience, format}
    score_explanation: Mapped[str | None] = mapped_column(Text)

    # State machine: scored → new → shown → approved/rejected → applying → applied/error
    status: Mapped[str] = mapped_column(String, default="scored", index=True)
    apply_error: Mapped[str | None] = mapped_column(String)  # last apply error message
    applied_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    is_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    found_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="vacancies")
    application: Mapped["Application | None"] = relationship("Application", back_populates="vacancy", uselist=False)
