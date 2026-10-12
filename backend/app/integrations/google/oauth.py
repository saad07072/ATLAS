from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from backend.app.config.settings import Settings, settings
from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import GoogleCredentials, OAuthTokenResponse
from backend.app.integrations.google.token_store import (
    GoogleCredentialStore,
    credential_expiry,
)
from backend.app.integrations.google.transport import HttpTransport, UrllibTransport

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
OAUTH_STATE_TTL_SECONDS = 600
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
)


@dataclass(frozen=True)
class GoogleOAuthAuthorization:
    url: str
    state: str
    browser_binding: str


def google_oauth_cookie_name(state: str) -> str:
    state_digest = hashlib.sha256(state.encode("utf-8")).hexdigest()[:32]
    return f"atlas_google_oauth_{state_digest}"


class GoogleOAuthService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        *,
        transport: HttpTransport | None = None,
        token_store: GoogleCredentialStore | None = None,
    ) -> None:
        self.settings = configured_settings
        self.transport = transport or UrllibTransport()
        self._store = token_store

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.google_oauth_client_id
            and self.settings.google_oauth_client_secret
            and self.settings.google_oauth_redirect_uri
            and self.settings.google_token_encryption_key
            and (self._store is not None or self.settings.database_url)
        )

    def authorization_request(self, user_id: str) -> GoogleOAuthAuthorization:
        self._require_configuration()
        state = secrets.token_urlsafe(32)
        browser_binding = secrets.token_urlsafe(32)
        self._token_store().store_state(
            user_id,
            state,
            hashlib.sha256(browser_binding.encode("utf-8")).hexdigest(),
            expires_at=time.time() + OAUTH_STATE_TTL_SECONDS,
        )
        query = urlencode(
            {
                "client_id": self.settings.google_oauth_client_id,
                "redirect_uri": self.settings.google_oauth_redirect_uri,
                "response_type": "code",
                "scope": " ".join(GOOGLE_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
        return GoogleOAuthAuthorization(
            url=f"{AUTHORIZATION_URL}?{query}",
            state=state,
            browser_binding=browser_binding,
        )

    def handle_callback(
        self,
        *,
        code: str | None,
        state: str,
        browser_binding: str | None,
        provider_error: str | None = None,
    ) -> str:
        self._require_configuration()
        if (
            not state
            or len(state) > 512
            or not browser_binding
            or len(browser_binding) > 512
        ):
            raise GoogleIntegrationError(
                "invalid_oauth_state",
                "Google authorization could not be validated. Please try again.",
            )
        binding_hash = hashlib.sha256(
            browser_binding.encode("utf-8")
        ).hexdigest()
        user_id = self._token_store().consume_state(
            state,
            binding_hash,
            now=time.time(),
        )
        if user_id is None:
            raise GoogleIntegrationError(
                "invalid_oauth_state",
                "Google authorization could not be validated. Please try again.",
            )
        if provider_error:
            raise GoogleIntegrationError(
                "authorization_denied",
                "Google authorization was not completed.",
            )
        if not code or len(code) > 4096:
            raise GoogleIntegrationError(
                "invalid_authorization_code",
                "Google authorization returned an invalid code.",
            )

        payload = self._token_request(
            {
                "code": code,
                "client_id": self.settings.google_oauth_client_id,
                "client_secret": self.settings.google_oauth_client_secret,
                "redirect_uri": self.settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        try:
            token = OAuthTokenResponse.model_validate(payload)
        except ValidationError:
            raise GoogleIntegrationError(
                "invalid_token_response",
                "Google returned an invalid authentication response.",
            ) from None

        scopes = self._validate_scopes(token.scope)
        previous = self._token_store().load_credentials(user_id)
        refresh_token = token.refresh_token or (
            previous.refresh_token if previous else None
        )
        if not refresh_token:
            raise GoogleIntegrationError(
                "reauthentication_required",
                "Google did not provide offline access. Please reconnect the account.",
            )
        credentials = GoogleCredentials(
            access_token=token.access_token,
            refresh_token=refresh_token,
            token_type=token.token_type,
            expires_at=credential_expiry(token.expires_in),
            scopes=scopes,
        )
        self._token_store().save_credentials(user_id, credentials)
        return user_id

    def access_token(self, user_id: str) -> str:
        credentials = self._token_store().load_credentials(user_id)
        if credentials is None:
            raise GoogleIntegrationError(
                "not_connected",
                "Google is not connected. Connect the account first.",
            )
        if not credentials.is_expired():
            return credentials.access_token
        if not credentials.refresh_token:
            raise GoogleIntegrationError(
                "reauthentication_required",
                "Google authorization expired. Please reconnect the account.",
            )
        return self.refresh_access_token(user_id, credentials).access_token

    def refresh_access_token(
        self,
        user_id: str,
        credentials: GoogleCredentials | None = None,
    ) -> GoogleCredentials:
        current = credentials or self._token_store().load_credentials(user_id)
        if current is None or not current.refresh_token:
            raise GoogleIntegrationError(
                "reauthentication_required",
                "Google authorization expired. Please reconnect the account.",
            )
        return self._refresh(user_id, current)

    def connection_status(self, user_id: str) -> tuple[bool, bool]:
        if not self.configured:
            return False, False
        return True, self._token_store().load_credentials(user_id) is not None

    def disconnect(self, user_id: str) -> None:
        credentials = self._token_store().load_credentials(user_id)
        self._token_store().delete_credentials(user_id)
        if credentials is None:
            return
        token = credentials.refresh_token or credentials.access_token
        try:
            response = self.transport.request(
                "POST",
                REVOKE_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=urlencode({"token": token}).encode("utf-8"),
                timeout=self.settings.google_api_timeout_seconds,
            )
        except GoogleIntegrationError:
            raise GoogleIntegrationError(
                "revocation_unavailable",
                "The Google connection was removed locally, but provider revocation could not be confirmed.",
            ) from None
        if response.status_code < 200 or response.status_code >= 300:
            raise GoogleIntegrationError(
                "revocation_unavailable",
                "The Google connection was removed locally, but provider revocation could not be confirmed.",
            )

    def _refresh(
        self,
        user_id: str,
        current: GoogleCredentials,
    ) -> GoogleCredentials:
        self._require_configuration()
        try:
            payload = self._token_request(
                {
                    "client_id": self.settings.google_oauth_client_id,
                    "client_secret": self.settings.google_oauth_client_secret,
                    "refresh_token": current.refresh_token,
                    "grant_type": "refresh_token",
                }
            )
        except GoogleIntegrationError as exc:
            if exc.code == "reauthentication_required":
                self._token_store().delete_credentials(user_id)
                raise
            raise
        try:
            token = OAuthTokenResponse.model_validate(payload)
        except ValidationError:
            raise GoogleIntegrationError(
                "invalid_token_response",
                "Google returned an invalid authentication response.",
            ) from None
        refreshed = GoogleCredentials(
            access_token=token.access_token,
            refresh_token=token.refresh_token or current.refresh_token,
            token_type=token.token_type,
            expires_at=credential_expiry(token.expires_in),
            scopes=self._validate_scopes(token.scope, fallback=current.scopes),
        )
        self._token_store().save_credentials(user_id, refreshed)
        return refreshed

    def _token_request(self, fields: dict[str, str | None]) -> dict[str, Any]:
        body = urlencode({key: value for key, value in fields.items() if value}).encode()
        try:
            response = self.transport.request(
                "POST",
                TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=body,
                timeout=self.settings.google_api_timeout_seconds,
            )
        except GoogleIntegrationError:
            raise GoogleIntegrationError(
                "oauth_network_error",
                "Google authentication service could not be reached.",
            ) from None
        if response.status_code < 200 or response.status_code >= 300:
            if response.status_code in {400, 401}:
                raise GoogleIntegrationError(
                    "reauthentication_required",
                    "Google authorization expired or was revoked. Please reconnect the account.",
                )
            raise GoogleIntegrationError(
                "oauth_failed",
                "Google authentication could not be completed. Please try again.",
            )
        try:
            payload = json.loads(response.body)
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise GoogleIntegrationError(
                "invalid_token_response",
                "Google returned an invalid authentication response.",
            ) from None

    def _require_configuration(self) -> None:
        if not self.configured:
            raise GoogleIntegrationError(
                "configuration_error",
                "Google OAuth is not configured.",
            )
        try:
            self._token_store()
        except GoogleIntegrationError:
            raise

    @staticmethod
    def _validate_scopes(
        scope: str,
        *,
        fallback: list[str] | None = None,
    ) -> list[str]:
        scopes = scope.split() if scope else fallback or []
        if not scopes or set(scopes) != set(GOOGLE_SCOPES):
            raise GoogleIntegrationError(
                "insufficient_scopes",
                "Google authorization included unsupported or missing permissions. Please reconnect the account.",
            )
        return scopes

    def _token_store(self) -> GoogleCredentialStore:
        if self._store is None:
            from backend.app.integrations.google.repository import (
                PostgresGoogleCredentialStore,
            )
            self._store = PostgresGoogleCredentialStore(
                self.settings.database_url,
                self.settings.google_token_encryption_key,
            )
        return self._store
