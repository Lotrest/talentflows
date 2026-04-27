from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class UserProfile(BaseModel):
    skills: list[str] = []
    keywords: str | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    city: str | None = None
    work_formats: list[str] = []
    experience_years: int | None = None
    target_role: str | None = None
    score_threshold: int | None = None    # 0-100, default 60
    daily_apply_limit: int | None = None  # max applies/day, default 20
    rejected_companies: list[str] | None = None


class UserToneSettings(BaseModel):
    tone: str = "professional"
    auto_reply: bool = True
    auto_send: bool = False
    include_salary: bool = True
    personalize: bool = True
    custom_instructions: str | None = None


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    plan: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserProfileOut(UserOut):
    skills: list[str] = []
    keywords: str | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    city: str | None = None
    work_formats: list[str] = []
    experience_years: int | None = None
    target_role: str | None = None
    score_threshold: int = 60
    daily_apply_limit: int = 20
    rejected_companies: list[str] = []
    tone: str = "professional"
    auto_reply: bool = True
    auto_send: bool = False
    include_salary: bool = True
    personalize: bool = True
    custom_instructions: str | None = None
    resume: Optional["ResumeInfo"] = None


class ResumeInfo(BaseModel):
    filename: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
