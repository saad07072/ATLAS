from fastapi import APIRouter

from backend.app.api.health import router as health_router
from backend.app.api.v1.chat import router as chat_router
from backend.app.api.v1.github import router as github_router
from backend.app.api.v1.google import router as google_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(chat_router)
router.include_router(google_router)
router.include_router(github_router)
