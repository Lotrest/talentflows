import httpx
from app.models.user import User
from app.services.platforms.base import PlatformAdapter, PlatformVacancy, PlatformVacancyDetail, PlatformResume


class JoobleAdapter(PlatformAdapter):
    key = "jooble"
    integration_mode = "api_key"
    supports_oauth = False

    _API_BASE = "https://jooble.org/api"

    async def is_connected(self, connection) -> bool:
        from app.core.config import settings
        return bool(settings.jooble_api_key)

    async def search_vacancies(self, connection, user: User, query: str, per_page: int = 50) -> list[PlatformVacancy]:
        from app.core.config import settings
        if not settings.jooble_api_key:
            return []

        body: dict = {
            "keywords": query,
            "resultonpage": min(per_page, 20),
        }
        if user.city:
            body["location"] = user.city
        if user.salary_from:
            body["salary"] = user.salary_from

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._API_BASE}/{settings.jooble_api_key}",
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []

        items: list[PlatformVacancy] = []
        for item in data.get("jobs", []):
            salary_str: str = item.get("salary", "") or ""
            salary_from = None
            if salary_str:
                digits = "".join(c for c in salary_str if c.isdigit() or c == " ").split()
                if digits:
                    try:
                        salary_from = int(digits[0])
                    except ValueError:
                        pass

            items.append(PlatformVacancy(
                external_id=str(item.get("id", "")),
                title=item.get("title", ""),
                company=item.get("company", ""),
                salary_from=salary_from,
                salary_to=None,
                salary_currency="RUR",
                city=item.get("location", ""),
                work_format="remote" if "удалён" in (item.get("type", "").lower()) else None,
                url=item.get("link"),
            ))
        return items

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        return PlatformVacancyDetail()

    async def get_resumes(self, connection) -> list[PlatformResume]:
        return []
