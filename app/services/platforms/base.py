from dataclasses import dataclass, field
from app.models.user import User


@dataclass
class PlatformVacancy:
    external_id: str
    title: str
    company: str
    salary_from: int | None = None
    salary_to: int | None = None
    salary_currency: str = "RUR"
    city: str | None = None
    work_format: str | None = None
    url: str | None = None


@dataclass
class PlatformVacancyDetail:
    description: str = ""
    skills_required: list[str] = field(default_factory=list)


@dataclass
class PlatformResume:
    id: str
    title: str
    status: str = ""
    url: str = ""
    updated_at: str = ""


class PlatformAdapter:
    """
    Base class for all platform adapters.

    Each adapter handles one job platform (HH, Superjob, etc.).
    Subclasses override only what they support.
    """

    key: str = ""
    integration_mode: str = "official_api"
    supports_oauth: bool = False

    # --- OAuth methods (override if supports_oauth = True) ---

    def get_oauth_url(self, state: str) -> str:
        raise NotImplementedError(f"{self.key} does not support OAuth")

    async def exchange_code(self, code: str) -> dict:
        raise NotImplementedError

    async def do_refresh_token(self, rt: str) -> dict:
        raise NotImplementedError

    async def get_platform_user_info(self, access_token: str) -> dict:
        """Return dict with keys: id, email, name"""
        raise NotImplementedError

    # --- Core methods ---

    async def is_connected(self, connection) -> bool:
        """connection is PlatformConnection | None"""
        return connection is not None and bool(getattr(connection, "access_token", None))

    async def search_vacancies(
        self,
        connection,
        user: User,
        query: str,
        per_page: int = 50,
    ) -> list[PlatformVacancy]:
        return []

    async def get_vacancy_detail(
        self,
        connection,
        external_id: str,
    ) -> PlatformVacancyDetail:
        return PlatformVacancyDetail()

    async def get_resumes(self, connection) -> list[PlatformResume]:
        raise NotImplementedError(f"{self.key} does not support resume listing")

    async def apply_to_vacancy(
        self,
        connection,
        vacancy_id: str,
        resume_id: str,
        cover_letter: str,
    ) -> dict:
        return {}

    async def send_message(
        self,
        connection,
        negotiation_id: str,
        message: str,
    ) -> dict:
        return {}
