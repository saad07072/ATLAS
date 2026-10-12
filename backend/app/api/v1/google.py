from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import GoogleConnectionStatus
from backend.app.integrations.google.oauth import (
    GoogleOAuthService,
    google_oauth_cookie_name,
)
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
    user_id: UUID = Depends(get_authenticated_user_id),
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleConnectionStatus:
    try:
        configured, connected = oauth.connection_status(str(user_id))
    except GoogleIntegrationError as exc:
        raise _google_error(exc) from exc
    return GoogleConnectionStatus(
        configured=configured,
        connected=connected,
        actions_enabled=False,
    )


@router.get("/oauth/start", response_model=GoogleOAuthStartResponse)
def google_oauth_start(
    response: Response,
    user_id: UUID = Depends(get_authenticated_user_id),
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleOAuthStartResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        authorization = oauth.authorization_request(str(user_id))
    except GoogleIntegrationError as exc:
        raise _google_error(exc) from exc
    response.set_cookie(
        key=google_oauth_cookie_name(authorization.state),
        value=authorization.browser_binding,
        max_age=600,
        httponly=True,
        secure=urlparse(oauth.settings.google_oauth_redirect_uri or "").scheme
        == "https",
        samesite="lax",
        path="/api/v1/google/oauth/callback",
    )
    return GoogleOAuthStartResponse(authorization_url=authorization.url)


@router.get("/oauth/callback", response_model=GoogleOAuthCallbackResponse)
def google_oauth_callback(
    request: Request,
    response: Response,
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
    code: str | None = Query(default=None, max_length=4096),
    state: str = Query(min_length=1, max_length=512),
    error: str | None = Query(default=None, max_length=100),
) -> GoogleOAuthCallbackResponse:
    response.headers["Cache-Control"] = "no-store"
    binding_cookie = request.cookies.get(google_oauth_cookie_name(state))
    try:
        oauth.handle_callback(
            code=code,
            state=state,
            browser_binding=binding_cookie,
            provider_error=error,
        )
    except GoogleIntegrationError as exc:
        raise _google_error(exc) from exc
    response.delete_cookie(
        key=google_oauth_cookie_name(state),
        path="/api/v1/google/oauth/callback",
    )
    return GoogleOAuthCallbackResponse(
        status="connected",
        message="Google account connected.",
    )


@router.delete("/connection", response_model=GoogleOAuthCallbackResponse)
def google_disconnect(
    user_id: UUID = Depends(get_authenticated_user_id),
    oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleOAuthCallbackResponse:
    try:
        oauth.disconnect(str(user_id))
    except GoogleIntegrationError as exc:
        raise _google_error(exc) from exc
    return GoogleOAuthCallbackResponse(
        status="disconnected",
        message="Google account disconnected.",
    )


def _google_error(error: GoogleIntegrationError) -> ApplicationError:
    if error.code in {"invalid_oauth_state", "invalid_authorization_code"}:
        status_code = 400
    elif error.code in {"authorization_denied", "insufficient_scopes"}:
        status_code = 403
    elif error.code == "reauthentication_required":
        status_code = 409
    elif error.code in {
        "configuration_error",
        "credential_store_error",
        "oauth_network_error",
        "revocation_unavailable",
    }:
        status_code = 503
    else:
        status_code = 502
    return ApplicationError(
        error.safe_message,
        code=error.code,
        status_code=status_code,
    )
