from functools import lru_cache

from backend.app.config.settings import settings
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.service import GitHubApiClient
from backend.app.integrations.github.tools import create_github_tools
from backend.app.integrations.google.runtime import get_google_api_client
from backend.app.integrations.google.tools import create_google_tools
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
    google_tools = create_google_tools(get_google_api_client())
    github_tools = create_github_tools(get_github_api_client())
    return create_tool_execution_service(google_tools + github_tools)
