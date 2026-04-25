from pydantic import BaseModel
from datetime import datetime


class VacancyOut(BaseModel):
    id: str
    platform: str
    integration_mode: str
    external_id: str | None
    hh_id: str | None
    title: str
    company: str
    salary_from: int | None
    salary_to: int | None
    salary_currency: str
    city: str | None
    work_format: str | None
    experience_required: str | None
    skills_required: list[str]
    url: str | None
    score: int | None
    score_breakdown: dict | None
    score_explanation: str | None
    # State machine: scored → new → shown → approved/rejected → applying → applied/error
    status: str
    apply_error: str | None
    is_applied: bool
    found_at: datetime
    applied_at: datetime | None

    model_config = {"from_attributes": True}


class VacancyListOut(BaseModel):
    items: list[VacancyOut]
    total: int
    page: int
    per_page: int
