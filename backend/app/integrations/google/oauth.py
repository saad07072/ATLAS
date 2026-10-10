from __future__ import annotations

import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from backend.app.config.settings import Settings, settings
from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import GoogleCredentials, OAuthTokenResponse
from backend.app.integrations.google.token_store import (
    EncryptedSQLiteTokenStore,
    credential_expiry,
)
from backend.app.integrations.google.transport import HttpTransport, UrllibTransport

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_STATE_TTL_SECONDS = 600
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
)


class GoogleOAuthService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        *,
        transport: HttpTransport | None = None,
        token_store: EncryptedSQLiteTokenStore | None = None,
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
        )

    def authorization_url(self) -> str:
        self._require_configuration()
        state = secrets.token_urlsafe(32)
        self._token_store().store_state(
            state,
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
                "include_granted_scopes": "true",
                "state": state,
            }
        )
        return f"{AUTHORIZATION_URL}?{query}"

    def handle_callback(
        self,
        *,
        code: str | None,
        state: str,
        provider_error: str | None = None,
    ) -> None:
        self._require_configuration()
        if not state or len(state) > 512:
            raise GoogleIntegrationError(
                "invalid_oauth_state",
                "Google authorization could not be validated. Please try again.",
            )
        if not self._token_store().consume_state(state, now=time.time()):
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

        previous = self._token_store().load_credentials()
        refresh_token = token.refresh_token or (
            previous.refresh_token if previous else None
        )
        credentials = GoogleCredentials(
            access_token=token.access_token,
            refresh_token=refresh_token,
            token_type=token.token_type,
            expires_at=credential_expiry(token.expires_in),
            scopes=token.scope.split() or list(GOOGLE_SCOPES),
        )
        self._token_store().save_credentials(credentials)

    def access_token(self) -> str:
        credentials = self._token_store().load_credentials()
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
        return self.refresh_access_token(credentials).access_token

    def refresh_access_token(
        self,
        credentials: GoogleCredentials | None = None,
    ) -> GoogleCredentials:
        current = credentials or self._token_store().load_credentials()
        if current is None or not current.refresh_token:
            raise GoogleIntegrationError(
                "reauthentication_required",
                "Google authorization expired. Please reconnect the account.",
            )
        return self._refresh(current)

    def connection_status(self) -> tuple[bool, bool]:
        if not self.configured:
            return False, False
        try:
            return True, self._token_store().load_credentials() is not None
        except GoogleIntegrationError:
            return False, False

    def _refresh(self, current: GoogleCredentials) -> GoogleCredentials:
        self._require_configuration()
        payload = self._token_request(
            {
                "client_id": self.settings.google_oauth_client_id,
                "client_secret": self.settings.google_oauth_client_secret,
                "refresh_token": current.refresh_token,
                "grant_type": "refresh_token",
            }
        )
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
            scopes=token.scope.split() or current.scopes,
        )
        self._token_store().save_credentials(refreshed)
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

    def _token_store(self) -> EncryptedSQLiteTokenStore:
        if self._store is None:
            encryption_key = self.settings.google_token_encryption_key
            if not encryption_key:
                raise GoogleIntegrationError(
                    "configuration_error",
                    "Google token encryption is not configured.",
                )
            self._store = EncryptedSQLiteTokenStore(
                self.settings.google_token_db_path,
                encryption_key,
            )
        return self._store
