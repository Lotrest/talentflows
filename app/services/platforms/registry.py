from app.services.platforms.base import PlatformAdapter
from app.services.platforms.hh_adapter import HHAdapter
from app.services.platforms.stub_adapters import SuperjobAdapter, RabotaRuAdapter, AvitoAdapter, LinkedInAdapter
from app.services.platforms.jooble_adapter import JoobleAdapter
from app.core.config import settings

def _is_configured(*keys: str) -> bool:
    return all(k for k in keys)

_ADAPTERS: dict[str, PlatformAdapter] = {
    "hh": HHAdapter(),
}

if _is_configured(settings.jooble_api_key):
    _ADAPTERS["jooble"] = JoobleAdapter()

if _is_configured(settings.superjob_client_id, settings.superjob_client_secret):
    _ADAPTERS["superjob"] = SuperjobAdapter()

if _is_configured(settings.rabota_ru_client_id, settings.rabota_ru_client_secret):
    _ADAPTERS["rabota_ru"] = RabotaRuAdapter()

if _is_configured(settings.avito_client_id, settings.avito_client_secret):
    _ADAPTERS["avito"] = AvitoAdapter()

if _is_configured(settings.linkedin_client_id, settings.linkedin_client_secret):
    _ADAPTERS["linkedin"] = LinkedInAdapter()


def get_platform_adapter(key: str) -> PlatformAdapter | None:
    return _ADAPTERS.get(key)


def list_supported_platforms() -> list[str]:
    return sorted(_ADAPTERS.keys())
