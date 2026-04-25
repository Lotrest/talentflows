from fastapi import APIRouter
from app.api.v1 import auth, profile, vacancies, applications, analytics, platforms, billing

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(profile.router)
router.include_router(vacancies.router)
router.include_router(applications.router)
router.include_router(analytics.router)
router.include_router(platforms.router)
router.include_router(billing.router)
