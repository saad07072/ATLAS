from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.google.models import GoogleConnectionStatus
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.runtime import get_google_oauth_service
from backend.app.security.identity import get_authenticated_user_id

router = APIRouter(prefix="/google")


class GoogleOAuthCallbackResponse(BaseModel):
    status: str
    message: str


class GoogleOAuthStartResponse(BaseModel):
    authorization_url: str


@router.get("/status", response_model=GoogleConnectionStatus)
def google_connection_status(
    _user_id: UUID = Depends(get_authenticated_user_id),
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleConnectionStatus:
    return GoogleConnectionStatus(
        configured=oauth.configured,
        connected=False,
        actions_enabled=False,
    )


@router.get("/oauth/start", response_model=GoogleOAuthStartResponse)
def google_oauth_start(
    _user_id: UUID = Depends(get_authenticated_user_id),
) -> GoogleOAuthStartResponse:
    raise _integration_unavailable()


@router.get("/oauth/callback", response_model=GoogleOAuthCallbackResponse)
def google_oauth_callback(
    code: str | None = Query(default=None, max_length=4096),
    state: str = Query(min_length=1, max_length=512),
    error: str | None = Query(default=None, max_length=100),
) -> GoogleOAuthCallbackResponse:
    del code, state, error
    raise _integration_unavailable()


def _integration_unavailable() -> ApplicationError:
    return ApplicationError(
        "Google actions are unavailable until per-user connections are supported.",
        code="integration_ownership_unavailable",
        status_code=503,
    )
