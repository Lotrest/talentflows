import logging
import random
import httpx
from app.models.user import User
from app.services.platforms.base import PlatformAdapter, PlatformVacancy, PlatformVacancyDetail, PlatformResume

logger = logging.getLogger(__name__)

_CIS_CITIES = {
    "москва", "moscow", "санкт-петербург", "спб", "st.petersburg",
    "almaty", "алматы", "астана", "нур-султан", "минск", "киев", "київ",
    "новосибирск", "екатеринбург", "казань", "нижний новгород",
}

_CITY_TO_COUNTRY = {
    "warsaw": "Poland", "krakow": "Poland", "gdansk": "Poland", "poznan": "Poland", "wroclaw": "Poland",
    "berlin": "Germany", "munich": "Germany", "hamburg": "Germany", "frankfurt": "Germany",
    "amsterdam": "Netherlands", "rotterdam": "Netherlands",
    "prague": "Czech Republic",
    "budapest": "Hungary",
    "vienna": "Austria",
    "barcelona": "Spain", "madrid": "Spain",
    "lisbon": "Portugal",
}


def _resolve_location(user: User) -> str:
    if not user.city:
        return "Poland"
    city = user.city.lower().strip()
    if city in _CIS_CITIES:
        return "Poland"
    country = _CITY_TO_COUNTRY.get(city)
    if country:
        return country
    return user.city


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

        location = _resolve_location(user)
        url = f"{self._API_BASE}/{settings.jooble_api_key}"

        page = random.randint(1, 5)

        async def _fetch(keywords: str, loc: str) -> list:
            body = {"keywords": keywords, "location": loc, "page": page, "resultonpage": min(per_page, 20)}
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json().get("jobs") or []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                jobs = await _fetch(query or "developer", location)
                if not jobs:
                    jobs = await _fetch(query or "developer", "Poland")
                if not jobs:
                    jobs = await _fetch("developer", "Poland")
        except Exception as e:
            logger.error("Jooble search failed: %s", e)
            return []

        seen: set[str] = set()
        items: list[PlatformVacancy] = []
        for item in jobs:
            link = item.get("link") or ""
            if not link or link in seen:
                continue
            seen.add(link)

            salary_str: str = item.get("salary", "") or ""
            salary_from = None
            if salary_str:
                digits = "".join(c for c in salary_str if c.isdigit() or c == " ").split()
                if digits:
                    try:
                        salary_from = int(digits[0])
                    except ValueError:
                        pass

            t = (item.get("type") or "").lower()
            snippet = (item.get("snippet") or "").lower()
            is_remote = any(x in t + " " + snippet for x in ["remote", "удал", "home", "anywhere"])

            items.append(PlatformVacancy(
                external_id=str(item.get("id", "")),
                title=item.get("title", ""),
                company=item.get("company", ""),
                salary_from=salary_from,
                salary_to=None,
                salary_currency=None,
                city=item.get("location", ""),
                work_format="remote" if is_remote else None,
                url=link,
            ))
        return items

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        return PlatformVacancyDetail()

    async def get_resumes(self, connection) -> list[PlatformResume]:
        return []
