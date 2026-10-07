from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.config.settings import settings


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
    )
