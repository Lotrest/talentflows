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

# Fallback locations to broaden search when user location returns nothing
_FALLBACK_LOCATIONS = ["Poland", "Germany", "Netherlands"]


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


def _build_queries(raw: str) -> list[str]:
    """Build a ranked list of query variants from user keywords."""
    clean = (raw or "").strip()
    if len(clean) < 3:
        clean = "developer"

    first_word = clean.split()[0]
    expanded = f"{first_word} developer" if first_word.lower() != "developer" else "developer"

    seen: set[str] = set()
    result: list[str] = []
    for q in [clean, expanded, first_word, "developer"]:
        if q and q not in seen:
            seen.add(q)
            result.append(q)
    return result


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

        queries = _build_queries(query)
        user_location = _resolve_location(user)

        # Unique ordered locations: user's first, then fallbacks
        locations: list[str] = []
        for loc in [user_location] + _FALLBACK_LOCATIONS:
            if loc not in locations:
                locations.append(loc)

        url = f"{self._API_BASE}/{settings.jooble_api_key}"
        page = random.randint(1, 5)

        logger.info(
            "Jooble search: queries=%r locations=%r page=%d",
            queries, locations, page,
        )

        seen_links: set[str] = set()
        all_raw: list[dict] = []

        async def _fetch(keywords: str, loc: str) -> list:
            body = {"keywords": keywords, "location": loc, "page": page, "resultonpage": 20}
            resp = await client.post(url, json=body, timeout=15.0)
            resp.raise_for_status()
            jobs = resp.json().get("jobs") or []
            logger.info("Jooble _fetch: keywords=%r loc=%r → %d results", keywords, loc, len(jobs))
            return jobs

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for q in queries:
                    for loc in locations:
                        if len(all_raw) >= per_page * 2:
                            break
                        try:
                            jobs = await _fetch(q, loc)
                            for job in jobs:
                                link = job.get("link") or ""
                                if link and link not in seen_links:
                                    seen_links.add(link)
                                    all_raw.append(job)
                        except Exception as e:
                            logger.warning("Jooble _fetch failed q=%r loc=%r: %s", q, loc, e)
                    if len(all_raw) >= per_page:
                        break
        except Exception as e:
            logger.error("Jooble search failed: %s", e)
            return []

        logger.info("Jooble search done: %d unique results before trim", len(all_raw))

        items: list[PlatformVacancy] = []
        for item in all_raw[:per_page]:
            link = item.get("link") or ""

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
