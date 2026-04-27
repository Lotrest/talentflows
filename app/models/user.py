from sqlalchemy import String, Boolean, Integer, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import uuid


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    plan: Mapped[str] = mapped_column(String, default="free")  # free | pro | team

    # Subscription tracking
    stripe_customer_id: Mapped[str | None] = mapped_column(String, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, unique=True)
    subscription_status: Mapped[str] = mapped_column(String, default="inactive")  # active | trialing | inactive | canceled
    subscription_current_period_end: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    # Profile data
    skills: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[str | None] = mapped_column(String)
    salary_from: Mapped[int | None] = mapped_column(Integer)
    salary_to: Mapped[int | None] = mapped_column(Integer)
    city: Mapped[str | None] = mapped_column(String)
    work_formats: Mapped[list] = mapped_column(JSON, default=list)  # office | hybrid | remote
    experience_years: Mapped[int | None] = mapped_column(Integer)

    # Agent settings
    tone: Mapped[str] = mapped_column(String, default="professional")
    auto_reply: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_send: Mapped[bool] = mapped_column(Boolean, default=False)
    include_salary: Mapped[bool] = mapped_column(Boolean, default=True)
    personalize: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_instructions: Mapped[str | None] = mapped_column(String)

    # Scoring & apply settings
    score_threshold: Mapped[int] = mapped_column(Integer, default=60)   # min score to show vacancy
    daily_apply_limit: Mapped[int] = mapped_column(Integer, default=20) # max applies per day
    target_role: Mapped[str | None] = mapped_column(String)             # "Python разработчик", "Data Engineer"
    rejected_companies: Mapped[list] = mapped_column(JSON, default=list) # companies user always skips

    # Resume
    resume_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_path: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_uploaded_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Email/password auth
    hashed_password: Mapped[str | None] = mapped_column(String)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_code: Mapped[str | None] = mapped_column(String)
    email_code_expires: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    vacancies: Mapped[list["Vacancy"]] = relationship("Vacancy", back_populates="user")
    applications: Mapped[list["Application"]] = relationship("Application", back_populates="user")
