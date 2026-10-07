from fastapi import FastAPI

from backend.app.config.settings import settings
from backend.app.core.error_handlers import register_exception_handlers


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)
register_exception_handlers(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/api/v1/health")
async def api_health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }