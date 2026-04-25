from pydantic_settings import BaseSettings
from functools import lru_cache
from pydantic import model_validator


class Settings(BaseSettings):
    database_url: str = ""
    postgres_user: str = "postgres"
    postgres_password: str = "1234"
    postgres_host: str = "127.0.0.1"
    postgres_port: str = "5432"
    postgres_db: str = "postgres"
    redis_url: str = "redis://localhost:6379"

    # HH.ru
    hh_client_id: str = ""
    hh_client_secret: str = ""
    hh_redirect_uri: str = "http://localhost:8000/api/v1/auth/hh/callback"

    # Superjob
    superjob_client_id: str = ""
    superjob_client_secret: str = ""
    superjob_redirect_uri: str = "http://localhost:8000/api/v1/auth/superjob/callback"

    # Работа.ру
    rabota_ru_client_id: str = ""
    rabota_ru_client_secret: str = ""
    rabota_ru_redirect_uri: str = "http://localhost:8000/api/v1/auth/rabota_ru/callback"

    # Авито
    avito_client_id: str = ""
    avito_client_secret: str = ""
    avito_redirect_uri: str = "http://localhost:8000/api/v1/auth/avito/callback"

    # LinkedIn
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/api/v1/auth/linkedin/callback"

    # OpenAI API
    openai_api_key: str = ""

    # Jooble API
    jooble_api_key: str = ""

    # JWT
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080

    # App
    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"

    # Stripe (international payments)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro: str = ""   # price_xxx from Stripe dashboard
    stripe_price_team: str = ""  # price_xxx from Stripe dashboard

    # YooKassa (Russian payments)
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""

    # Rate limits (AI requests per day per user) — sync with frontend billing page
    rate_limit_free: int = 5
    rate_limit_pro: int = 50
    rate_limit_team: int = 500

    # Scheduler settings
    scan_interval_hours: int = 6  # how often background scan runs per user

    # SMTP primary (Яндекс)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "TalentFlows"

    # SMTP fallback (Mail.ru)
    smtp2_host: str = ""
    smtp2_port: int = 587
    smtp2_user: str = ""
    smtp2_password: str = ""
    smtp2_from: str = ""
    smtp2_from_name: str = "TalentFlows"

    @model_validator(mode="after")
    def build_database_url(self):
        if self.database_url:
            return self
        self.database_url = (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return self

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
