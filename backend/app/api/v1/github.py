from uuid import UUID

from fastapi import APIRouter, Depends

from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.models import GitHubConnectionStatus
from backend.app.integrations.github.runtime import get_github_authentication
from backend.app.security.identity import get_authenticated_user_id

router = APIRouter(prefix="/github")


@router.get("/status", response_model=GitHubConnectionStatus)
def github_connection_status(
    _user_id: UUID = Depends(get_authenticated_user_id),
    authentication: GitHubAppAuthentication = Depends(get_github_authentication),
) -> GitHubConnectionStatus:
    configured = authentication.configured
    return GitHubConnectionStatus(
        configured=configured,
        connected=False,
        actions_enabled=False,
    )
