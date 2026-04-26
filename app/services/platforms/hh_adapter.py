import httpx
from app.core.config import settings
from app.models.user import User
from app.services.platforms.base import PlatformAdapter, PlatformVacancy, PlatformVacancyDetail, PlatformResume

HH_API_BASE = "https://api.hh.ru"
HH_AUTH_URL = "https://hh.ru/oauth/authorize"
HH_TOKEN_URL = "https://hh.ru/oauth/token"
HH_HEADERS = {"User-Agent": "Applai/1.0 (akuninm2@gmail.com)"}


class HHAdapter(PlatformAdapter):
    key = "hh"
    integration_mode = "official_api"
    supports_oauth = True

    def get_oauth_url(self, state: str) -> str:
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": settings.hh_client_id,
            "redirect_uri": settings.hh_redirect_uri,
            "state": state,
            "scope": "resume",
        }
        return f"{HH_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(HH_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": settings.hh_client_id,
                "client_secret": settings.hh_client_secret,
                "code": code,
                "redirect_uri": settings.hh_redirect_uri,
            })
            resp.raise_for_status()
            return resp.json()

    async def do_refresh_token(self, rt: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(HH_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
            })
            resp.raise_for_status()
            return resp.json()

    async def get_platform_user_info(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{HH_API_BASE}/me",
                headers={"Authorization": f"Bearer {access_token}", **HH_HEADERS},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "id": str(data["id"]),
                "email": data.get("email") or f"hh_{data['id']}@hh.ru",
                "name": data.get("first_name", ""),
            }

    async def search_vacancies(
        self,
        connection,
        user: User,
        query: str,
        per_page: int = 50,
    ) -> list[PlatformVacancy]:
        search_text = query

        params: dict = {
            "text": search_text,
            "area": "1",
            "per_page": per_page,
            "page": 0,
            "only_with_salary": "false",
        }
        if user.salary_from:
            params["salary"] = user.salary_from
            params["only_with_salary"] = "true"

        # Map user experience to HH experience filter
        exp_years = user.experience_years or 0
        if exp_years == 0:
            params["experience"] = "noExperience"
        elif exp_years < 3:
            params["experience"] = "between1And3"
        elif exp_years < 6:
            params["experience"] = "between3And6"
        else:
            params["experience"] = "moreThan6"

        # Map work formats to HH schedule filter (pick first preferred)
        fmt_map = {"remote": "remote", "office": "fullDay", "hybrid": "flexible"}
        formats = user.work_formats or []
        if formats and formats[0] in fmt_map:
            params["schedule"] = fmt_map[formats[0]]

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{HH_API_BASE}/vacancies",
                params=params,
                headers=HH_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

        schedule_map = {"remote": "remote", "fullDay": "office", "flexible": "hybrid", "shift": "office"}
        items: list[PlatformVacancy] = []
        for item in data.get("items", []):
            salary = item.get("salary") or {}
            schedule_id = item.get("schedule", {}).get("id", "")
            items.append(PlatformVacancy(
                external_id=item["id"],
                title=item.get("name", ""),
                company=item.get("employer", {}).get("name", ""),
                salary_from=salary.get("from"),
                salary_to=salary.get("to"),
                salary_currency=salary.get("currency", "RUR"),
                city=item.get("area", {}).get("name"),
                work_format=schedule_map.get(schedule_id),
                url=item.get("alternate_url"),
            ))
        return items

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{HH_API_BASE}/vacancies/{external_id}",
                headers={"Authorization": f"Bearer {connection.access_token}", **HH_HEADERS},
            )
            resp.raise_for_status()
            detail = resp.json()
        return PlatformVacancyDetail(
            description=detail.get("description", "") or "",
            skills_required=[s["name"] for s in detail.get("key_skills", [])],
        )

    async def get_resumes(self, connection) -> list[PlatformResume]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{HH_API_BASE}/resumes/mine",
                headers={"Authorization": f"Bearer {connection.access_token}", **HH_HEADERS},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            PlatformResume(
                id=r["id"],
                title=r.get("title") or r.get("profession") or "Без названия",
                status=r.get("status", {}).get("name", ""),
                url=r.get("alternate_url", ""),
                updated_at=r.get("updated_at", ""),
            )
            for r in data.get("items", [])
        ]

    async def apply_to_vacancy(
        self,
        connection,
        vacancy_id: str,
        resume_id: str,
        cover_letter: str,
    ) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HH_API_BASE}/negotiations",
                json={"vacancy_id": vacancy_id, "resume_id": resume_id, "cover_letter": cover_letter},
                headers={"Authorization": f"Bearer {connection.access_token}", **HH_HEADERS},
            )
            resp.raise_for_status()
            return resp.json()

    async def send_message(self, connection, negotiation_id: str, message: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HH_API_BASE}/negotiations/{negotiation_id}/messages",
                json={"message": message},
                headers={"Authorization": f"Bearer {connection.access_token}", **HH_HEADERS},
            )
            resp.raise_for_status()
            return resp.json()
