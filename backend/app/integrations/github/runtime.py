from functools import lru_cache

from backend.app.config.settings import settings
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.service import GitHubApiClient
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.factory import create_tool_execution_service


@lru_cache(maxsize=1)
def get_github_authentication() -> GitHubAppAuthentication:
    return GitHubAppAuthentication(settings)


@lru_cache(maxsize=1)
def get_github_api_client() -> GitHubApiClient:
    return GitHubApiClient(get_github_authentication(), settings)


@lru_cache(maxsize=1)
def get_tool_executor() -> ToolExecutionService:
    return create_tool_execution_service([])
