from pydantic import BaseModel
from datetime import datetime


class CoverLetterRequest(BaseModel):
    vacancy_id: str
    tone: str = "professional"


class CoverLetterOut(BaseModel):
    cover_letter: str
    tone: str


class VacancyInApplication(BaseModel):
    title: str
    company: str
    salary_from: int | None = None
    salary_to: int | None = None
    salary_currency: str | None = None
    score: int | None = None
    platform: str
    url: str | None = None

    model_config = {"from_attributes": True}


class ApplicationOut(BaseModel):
    id: str
    vacancy_id: str
    status: str
    cover_letter: str | None
    sent_at: datetime | None
    viewed_at: datetime | None
    replied_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    vacancy: VacancyInApplication | None = None

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    application_id: str
    role: str
    content: str
    is_approved: bool | None
    sent_to_hh: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApproveMessageRequest(BaseModel):
    message_id: str
    send_immediately: bool = False
