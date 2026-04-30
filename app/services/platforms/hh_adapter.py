import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)
from app.models.user import User
from app.services.platforms.base import PlatformAdapter, PlatformVacancy, PlatformVacancyDetail, PlatformResume

HH_API_BASE = "https://api.hh.ru"
HH_AUTH_URL = "https://hh.ru/oauth/authorize"
HH_TOKEN_URL = "https://hh.ru/oauth/token"
HH_HEADERS = {"HH-User-Agent": "TalentFlows/1.0 (akuninm2@gmail.com)"}


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
            "scope": "resume negotiations",
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
            logger.info("HH exchange_code status=%s body=%s", resp.status_code, resp.text)
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
        auth_headers = {**HH_HEADERS}
        if connection and connection.access_token:
            auth_headers["Authorization"] = f"Bearer {connection.access_token}"

        schedule_map = {"remote": "remote", "fullDay": "office", "flexible": "hybrid", "shift": "office"}

        # Try suitable_vacancies endpoint (requires auth, bypasses IP restrictions on public search)
        if "Authorization" in auth_headers:
            try:
                resumes = await self.get_resumes(connection)
            except Exception as e:
                logger.warning("HH get_resumes failed (IP block?): %s", e)
                resumes = []

            if resumes:
                resume_id = resumes[0].id
                logger.info("HH: using suitable_vacancies for resume=%s", resume_id)
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{HH_API_BASE}/resumes/{resume_id}/suitable_vacancies",
                        params={"per_page": min(per_page, 50)},
                        headers=auth_headers,
                    )
                    logger.info("HH /suitable_vacancies status=%s", resp.status_code)
                    if resp.is_success:
                        data = resp.json()
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
                    logger.warning("HH suitable_vacancies failed: %s %s", resp.status_code, resp.text)

        # Fallback: vacancy search — use auth token if available (server IPs get 403 without it)
        params: dict = {
            "text": query or "python",
            "area": 1,
            "per_page": min(per_page, 50),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{HH_API_BASE}/vacancies",
                params=params,
                headers=auth_headers,
            )
            logger.info("HH /vacancies status=%s url=%s", resp.status_code, resp.url)
            if not resp.is_success:
                logger.error("HH /vacancies error %s body: %s", resp.status_code, resp.text)
                resp.raise_for_status()
            data = resp.json()

        items = []
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
        detail_headers = {**HH_HEADERS}
        if connection and connection.access_token:
            detail_headers["Authorization"] = f"Bearer {connection.access_token}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{HH_API_BASE}/vacancies/{external_id}",
                headers=detail_headers,
            )
            if not resp.is_success:
                logger.error("HH /vacancies/%s error: %s", external_id, resp.text)
                resp.raise_for_status()
            detail = resp.json()
        return PlatformVacancyDetail(
            description=detail.get("description", "") or "",
            skills_required=[s["name"] for s in detail.get("key_skills", [])],
        )

    async def get_resumes(self, connection) -> list[PlatformResume]:
        token = connection.access_token if connection else None
        logger.info("HH get_resumes: token_present=%s token_prefix=%s", bool(token), (token or "")[:10])
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{HH_API_BASE}/resumes/mine",
                    headers={"Authorization": f"Bearer {token}", **HH_HEADERS},
                )
                logger.info("HH get_resumes status=%s body=%s", resp.status_code, resp.text)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error("HH get_resumes exception: type=%s repr=%s", type(e).__name__, repr(e))
            raise
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
