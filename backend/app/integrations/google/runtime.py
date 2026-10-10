from functools import lru_cache

from backend.app.config.settings import settings
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.service import GoogleApiClient
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.factory import create_tool_execution_service


@lru_cache(maxsize=1)
def get_google_oauth_service() -> GoogleOAuthService:
    return GoogleOAuthService(settings)


@lru_cache(maxsize=1)
def get_google_api_client() -> GoogleApiClient:
    return GoogleApiClient(
        oauth=get_google_oauth_service(),
        settings=settings,
    )


@lru_cache(maxsize=1)
def get_google_tool_executor() -> ToolExecutionService:
    return create_tool_execution_service([])
