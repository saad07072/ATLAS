from fastapi import APIRouter, Depends

from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.models import GitHubConnectionStatus
from backend.app.integrations.github.runtime import get_github_authentication

router = APIRouter(prefix="/github")


@router.get("/status", response_model=GitHubConnectionStatus)
def github_connection_status(
    authentication: GitHubAppAuthentication = Depends(get_github_authentication),
) -> GitHubConnectionStatus:
    configured = authentication.configured
    return GitHubConnectionStatus(configured=configured, connected=configured)
