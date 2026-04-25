import httpx
from app.models.user import User
from app.services.platforms.base import PlatformAdapter, PlatformVacancy, PlatformVacancyDetail, PlatformResume


class SuperjobAdapter(PlatformAdapter):
    key = "superjob"
    integration_mode = "official_api"
    supports_oauth = True

    _OAUTH_URL = "https://www.superjob.ru/authorize/"
    _TOKEN_URL = "https://api.superjob.ru/oauth2/access_token/"
    _API_BASE = "https://api.superjob.ru/2.0"

    def get_oauth_url(self, state: str) -> str:
        from app.core.config import settings
        params = {
            "response_type": "code",
            "client_id": settings.superjob_client_id,
            "redirect_uri": settings.superjob_redirect_uri,
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self._OAUTH_URL}?{query}"

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

    async def search_vacancies(self, connection, user: User, query: str, per_page: int = 50) -> list[PlatformVacancy]:
        if not connection:
            return []
        params: dict = {
            "keyword": query,
            "count": min(per_page, 100),
            "page": 0,
        }
        if user.salary_from:
            params["payment_from"] = user.salary_from
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/vacancies/",
                params=params,
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        items: list[PlatformVacancy] = []
        for item in data.get("objects", []):
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

    async def get_vacancy_detail(self, connection, external_id: str) -> PlatformVacancyDetail:
        if not connection:
            return PlatformVacancyDetail()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/vacancies/{external_id}/",
                headers={"Authorization": f"Bearer {connection.access_token}"},
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
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._API_BASE}/candidates/resumes/",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
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
