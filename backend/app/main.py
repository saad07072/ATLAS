import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from backend.app.api.health import router as health_router
from backend.app.api.v1.router import router as api_v1_router
from backend.app.config.settings import settings
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.logging_config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    logger.info(
        "Starting %s %s in %s mode",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def redact_google_oauth_callback_query(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    response = await call_next(request)
    if request.url.path == "/api/v1/google/oauth/callback":
        request.scope["query_string"] = b""
    return response


register_exception_handlers(app)
app.include_router(health_router)
app.include_router(api_v1_router)
