from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import GoogleConnectionStatus
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.runtime import get_google_oauth_service

router = APIRouter(prefix="/google")


class GoogleOAuthCallbackResponse(BaseModel):
    status: str
    message: str


@router.get("/status", response_model=GoogleConnectionStatus)
def google_connection_status(
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleConnectionStatus:
    configured, connected = oauth.connection_status()
    return GoogleConnectionStatus(configured=configured, connected=connected)


@router.get("/oauth/start")
def google_oauth_start(
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> RedirectResponse:
    try:
        return RedirectResponse(oauth.authorization_url(), status_code=302)
    except GoogleIntegrationError as exc:
        raise _safe_oauth_error(exc) from None


@router.get("/oauth/callback", response_model=GoogleOAuthCallbackResponse)
def google_oauth_callback(
    code: str | None = Query(default=None, max_length=4096),
    state: str = Query(min_length=1, max_length=512),
    error: str | None = Query(default=None, max_length=100),
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleOAuthCallbackResponse:
    try:
        oauth.handle_callback(code=code, state=state, provider_error=error)
    except GoogleIntegrationError as exc:
        raise _safe_oauth_error(exc) from None
    return GoogleOAuthCallbackResponse(
        status="connected",
        message="Google account connected successfully.",
    )


def _safe_oauth_error(error: GoogleIntegrationError) -> ApplicationError:
    if error.code in {
        "invalid_oauth_state",
        "authorization_denied",
        "invalid_authorization_code",
    }:
        status_code = 400
    elif error.code == "configuration_error":
        status_code = 503
    else:
        status_code = 502
    return ApplicationError(
        error.safe_message,
        code=error.code,
        status_code=status_code,
    )
