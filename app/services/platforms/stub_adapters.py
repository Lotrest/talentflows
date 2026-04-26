import logging
import httpx
from app.models.user import User
from app.services.platforms.base import PlatformAdapter, PlatformVacancy, PlatformVacancyDetail, PlatformResume

logger = logging.getLogger(__name__)


class SuperjobAdapter(PlatformAdapter):
    key = "superjob"
    integration_mode = "official_api"
    supports_oauth = True

    _OAUTH_URL = "https://www.superjob.ru/authorize/"
    _TOKEN_URL = "https://api.superjob.ru/2.0/oauth2/access_token"
    _API_BASE = "https://api.superjob.ru/2.0"

    def get_oauth_url(self, state: str) -> str:
        from app.core.config import settings
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": settings.superjob_client_id,
            "redirect_uri": settings.superjob_redirect_uri,
            "state": state,
        }
        return f"{self._OAUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": settings.superjob_client_id,
                "client_secret": settings.superjob_client_secret,
                "code": code,
                "redirect_uri": settings.superjob_redirect_uri,
            })
            resp.raise_for_status()
            return resp.json()

    async def do_refresh_token(self, rt: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": settings.superjob_client_id,
                "client_secret": settings.superjob_client_secret,
            })
            resp.raise_for_status()
            return resp.json()

    async def get_platform_user_info(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/user/current/",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "id": str(data.get("id", "")),
                "email": data.get("email", ""),
                "name": data.get("firstName", ""),
            }

    def _build_queries(self, raw: str) -> list[str]:
        clean = (raw or "").strip()
        if len(clean) < 3:
            clean = "разработчик"
        first_word = clean.split()[0]
        expanded = f"{first_word} разработчик" if first_word.lower() not in ("разработчик", "developer") else first_word
        seen: set[str] = set()
        result: list[str] = []
        for q in [clean, expanded, first_word, "разработчик"]:
            if q and q not in seen:
                seen.add(q)
                result.append(q)
        return result

    async def search_vacancies(self, connection, user: User, query: str, per_page: int = 50) -> list[PlatformVacancy]:
        queries = self._build_queries(query)
        # 0 = вся Россия, 4 = Москва, 14 = СПб
        towns = [0, 4, 14]

        seen_ids: set[str] = set()
        all_raw: list[dict] = []

        collect_done = False
        for q in queries:
            if collect_done:
                break
            for town in towns:
                if collect_done:
                    break
                for page in range(3):
                    if len(all_raw) >= per_page * 2:
                        collect_done = True
                        break
                    params: dict = {"keyword": q, "count": 20, "page": page}
                    if town != 0:
                        params["town"] = town
                    try:
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(
                                f"{self._API_BASE}/vacancies/",
                                params=params,
                                headers=self._auth_headers(connection),
                                timeout=10.0,
                            )
                            resp.raise_for_status()
                            data = resp.json()
                        page_items = data.get("objects", [])
                        if not page_items:
                            break
                        for item in page_items:
                            eid = str(item["id"])
                            if eid not in seen_ids:
                                seen_ids.add(eid)
                                all_raw.append(item)
                    except Exception as e:
                        logger.warning("superjob search q=%r town=%s page=%s: %s", q, town, page, e)
                        break

        items: list[PlatformVacancy] = []
        for item in all_raw[:per_page]:
            schedule = item.get("work_schedule", {}).get("title", "").lower()
            work_format = "remote" if "удален" in schedule else "office"
            items.append(PlatformVacancy(
                external_id=str(item["id"]),
                title=item.get("profession", ""),
                company=item.get("firm_name", ""),
                salary_from=item.get("payment_from") or None,
                salary_to=item.get("payment_to") or None,
                salary_currency=item.get("currency", "rub").upper(),
                city=item.get("town", {}).get("title"),
                work_format=work_format,
                url=item.get("link"),
            ))
        return items

    def _auth_headers(self, connection=None) -> dict:
        from app.core.config import settings
        h = {"X-Api-App-Id": settings.superjob_client_secret}
        if connection and connection.access_token:
            h["Authorization"] = f"Bearer {connection.access_token}"
        return h

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/vacancies/{external_id}/",
                headers=self._auth_headers(connection),
            )
            resp.raise_for_status()
            data = resp.json()
        obj = data.get("objects", [{}])[0] if data.get("objects") else data
        skills = [s.strip() for s in obj.get("keywords", "").split(",") if s.strip()]
        return PlatformVacancyDetail(
            description=obj.get("candidat", "") or obj.get("work", "") or "",
            skills_required=skills,
        )

    async def get_resumes(self, connection) -> list[PlatformResume]:
        if not connection:
            return []
        params = {}
        if connection.platform_user_id:
            params["user_id"] = connection.platform_user_id
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/resumes/",
                params=params,
                headers=self._auth_headers(connection),
            )
            logger.info("superjob get_resumes: status=%s user_id=%s", resp.status_code, connection.platform_user_id)
            resp.raise_for_status()
            data = resp.json()
        return [
            PlatformResume(
                id=str(r["id"]),
                title=r.get("profession", "Резюме"),
                status=r.get("status", {}).get("title", "") if isinstance(r.get("status"), dict) else "",
                url=r.get("link", ""),
                updated_at=str(r.get("date_published", "")),
            )
            for r in data.get("objects", [])
        ]

    async def apply_to_vacancy(self, connection, vacancy_id: str, resume_id: str, cover_letter: str) -> dict:
        if not connection or not resume_id:
            logger.warning("superjob apply_to_vacancy: missing connection or resume_id")
            return {}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._API_BASE}/responses/",
                json={"vacancy_id": int(vacancy_id), "resume_id": int(resume_id), "text": cover_letter},
                headers=self._auth_headers(connection),
            )
            logger.info("superjob apply_to_vacancy: status=%s vacancy=%s resume=%s", resp.status_code, vacancy_id, resume_id)
            resp.raise_for_status()
            return resp.json()


class RabotaRuAdapter(PlatformAdapter):
    key = "rabota_ru"
    integration_mode = "official_api"
    supports_oauth = True

    _OAUTH_URL = "https://accounts.rabota.ru/oauth/authorize"
    _TOKEN_URL = "https://accounts.rabota.ru/oauth/token"
    _API_BASE = "https://api.rabota.ru/v1"

    def get_oauth_url(self, state: str) -> str:
        from app.core.config import settings
        params = {
            "response_type": "code",
            "client_id": settings.rabota_ru_client_id,
            "redirect_uri": settings.rabota_ru_redirect_uri,
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self._OAUTH_URL}?{query}"

    async def exchange_code(self, code: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": settings.rabota_ru_client_id,
                "client_secret": settings.rabota_ru_client_secret,
                "code": code,
                "redirect_uri": settings.rabota_ru_redirect_uri,
            })
            resp.raise_for_status()
            return resp.json()

    async def do_refresh_token(self, rt: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": settings.rabota_ru_client_id,
                "client_secret": settings.rabota_ru_client_secret,
            })
            resp.raise_for_status()
            return resp.json()

    async def get_platform_user_info(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/account/info",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "id": str(data.get("id", "")),
                "email": data.get("email", ""),
                "name": data.get("name", ""),
            }

    async def search_vacancies(self, connection, user: User, query: str, per_page: int = 50) -> list[PlatformVacancy]:
        if not connection:
            return []
        params: dict = {
            "query": query,
            "limit": min(per_page, 100),
            "offset": 0,
        }
        if user.salary_from:
            params["salary_from"] = user.salary_from
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/vacancy",
                params=params,
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        items: list[PlatformVacancy] = []
        for item in data.get("vacancies", data.get("items", [])):
            salary = item.get("salary", {}) or {}
            items.append(PlatformVacancy(
                external_id=str(item.get("id", "")),
                title=item.get("title", ""),
                company=item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else item.get("company", ""),
                salary_from=salary.get("from"),
                salary_to=salary.get("to"),
                salary_currency="RUR",
                city=item.get("city", {}).get("name", "") if isinstance(item.get("city"), dict) else item.get("city", ""),
                work_format=None,
                url=item.get("url"),
            ))
        return items

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        if not connection:
            return PlatformVacancyDetail()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/vacancy/{external_id}",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return PlatformVacancyDetail(
            description=data.get("description", "") or data.get("requirements", "") or "",
            skills_required=[],
        )

    async def get_resumes(self, connection) -> list[PlatformResume]:
        if not connection:
            return []
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/resumes",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            PlatformResume(
                id=str(r.get("id", "")),
                title=r.get("title", "Резюме"),
                status="",
                url=r.get("url", ""),
                updated_at=r.get("updated_at", ""),
            )
            for r in data.get("resumes", data.get("items", []))
        ]


class AvitoAdapter(PlatformAdapter):
    key = "avito"
    integration_mode = "official_api"
    supports_oauth = True

    _OAUTH_URL = "https://www.avito.ru/oauth"
    _TOKEN_URL = "https://api.avito.ru/token"
    _API_BASE = "https://api.avito.ru"

    def get_oauth_url(self, state: str) -> str:
        from app.core.config import settings
        params = {
            "response_type": "code",
            "client_id": settings.avito_client_id,
            "redirect_uri": settings.avito_redirect_uri,
            "state": state,
            "scope": "job:read job:write",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self._OAUTH_URL}?{query}"

    async def exchange_code(self, code: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": settings.avito_client_id,
                "client_secret": settings.avito_client_secret,
                "code": code,
                "redirect_uri": settings.avito_redirect_uri,
            })
            resp.raise_for_status()
            return resp.json()

    async def do_refresh_token(self, rt: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": settings.avito_client_id,
                "client_secret": settings.avito_client_secret,
            })
            resp.raise_for_status()
            return resp.json()

    async def get_platform_user_info(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/core/v1/accounts/self",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "id": str(data.get("id", "")),
                "email": data.get("email", ""),
                "name": data.get("name", ""),
            }

    async def search_vacancies(self, connection, user: User, query: str, per_page: int = 50) -> list[PlatformVacancy]:
        if not connection:
            return []
        params: dict = {
            "query": query,
            "limit": min(per_page, 25),
            "offset": 0,
            "category": "job",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/job/v1/vacancies",
                params=params,
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        items: list[PlatformVacancy] = []
        for item in data.get("vacancies", []):
            salary = item.get("salary", {}) or {}
            items.append(PlatformVacancy(
                external_id=str(item.get("id", "")),
                title=item.get("title", ""),
                company=item.get("employer", {}).get("name", "") if isinstance(item.get("employer"), dict) else "",
                salary_from=salary.get("from"),
                salary_to=salary.get("to"),
                salary_currency=salary.get("currency", "RUR"),
                city=item.get("address", {}).get("city", "") if isinstance(item.get("address"), dict) else "",
                work_format=None,
                url=item.get("url"),
            ))
        return items

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        if not connection:
            return PlatformVacancyDetail()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/job/v1/vacancies/{external_id}",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return PlatformVacancyDetail(
            description=data.get("description", ""),
            skills_required=[],
        )

    async def get_resumes(self, connection) -> list[PlatformResume]:
        # Авито не поддерживает хранение резюме через API
        return []


class LinkedInAdapter(PlatformAdapter):
    key = "linkedin"
    integration_mode = "official_api"
    supports_oauth = True

    _OAUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    _TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    _API_BASE = "https://api.linkedin.com/v2"

    def get_oauth_url(self, state: str) -> str:
        from app.core.config import settings
        params = {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "state": state,
            "scope": "r_liteprofile r_emailaddress w_member_social",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self._OAUTH_URL}?{query}"

    async def exchange_code(self, code: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
                "code": code,
                "redirect_uri": settings.linkedin_redirect_uri,
            })
            resp.raise_for_status()
            return resp.json()

    async def do_refresh_token(self, rt: str) -> dict:
        from app.core.config import settings
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            })
            resp.raise_for_status()
            return resp.json()

    async def get_platform_user_info(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            email_resp = await client.get(
                f"{self._API_BASE}/emailAddress?q=members&projection=(elements*(handle~))",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            email = ""
            if email_resp.is_success:
                elements = email_resp.json().get("elements", [])
                if elements:
                    email = elements[0].get("handle~", {}).get("emailAddress", "")
            return {
                "id": data.get("id", ""),
                "email": email or f"linkedin_{data.get('id', '')}@linkedin.com",
                "name": data.get("localizedFirstName", ""),
            }

    async def search_vacancies(self, connection, user: User, query: str, per_page: int = 50) -> list[PlatformVacancy]:
        # LinkedIn Jobs API закрыт для сторонних приложений с 2023 года.
        # Подключение через OAuth работает, но программный поиск/отклик недоступен.
        return []

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        return PlatformVacancyDetail()
