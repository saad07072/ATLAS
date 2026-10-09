from __future__ import annotations

import base64
import json
import re
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.config.settings import Settings, settings
from backend.app.integrations.github.errors import (
    GitHubIntegrationError,
    normalize_github_status,
)
from backend.app.integrations.github.transport import HttpTransport, UrllibTransport

GITHUB_API_BASE = "https://api.github.com"
JWT_LIFETIME_SECONDS = 540
TOKEN_REFRESH_LEEWAY_SECONDS = 60


class _InstallationToken(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token: str = Field(min_length=1, repr=False)
    expires_at: datetime


class GitHubAppAuthentication:
    def __init__(
        self,
        configured_settings: Settings = settings,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self.settings = configured_settings
        self.transport = transport or UrllibTransport()
        self._lock = threading.Lock()
        self._private_key: rsa.RSAPrivateKey | None = None
        self._cached_token: _InstallationToken | None = None

    @property
    def configured(self) -> bool:
        if not (
            self._valid_id(self.settings.github_app_id)
            and self._valid_id(self.settings.github_installation_id)
        ):
            return False
        try:
            self._load_private_key()
        except GitHubIntegrationError:
            return False
        return True

    def installation_token(self) -> str:
        self._require_configuration()
        with self._lock:
            now = datetime.now(timezone.utc)
            if self._cached_token is not None and not self._cached_token_expiring(
                self._cached_token, now
            ):
                return self._cached_token.token

            token = self._request_installation_token()
            if self._cached_token_expiring(token, datetime.now(timezone.utc)):
                raise GitHubIntegrationError(
                    "invalid_authentication_response",
                    "GitHub returned an expired installation token.",
                )
            self._cached_token = token
            return token.token

    def create_app_jwt(self, *, now: int | None = None) -> str:
        self._require_configuration()
        current_time = int(time.time()) if now is None else now
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iat": current_time - 60,
            "exp": current_time + JWT_LIFETIME_SECONDS,
            "iss": self.settings.github_app_id,
        }
        signing_input = ".".join(
            (
                self._base64url(json.dumps(header, separators=(",", ":")).encode()),
                self._base64url(json.dumps(payload, separators=(",", ":")).encode()),
            )
        )
        try:
            signature = self._load_private_key().sign(
                signing_input.encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (TypeError, ValueError, UnsupportedAlgorithm):
            raise GitHubIntegrationError(
                "configuration_error",
                "The configured GitHub App private key could not sign a token.",
            ) from None
        return f"{signing_input}.{self._base64url(signature)}"

    def _request_installation_token(self) -> _InstallationToken:
        jwt = self.create_app_jwt()
        body = json.dumps({}).encode("utf-8")
        try:
            response = self.transport.request(
                "POST",
                f"{GITHUB_API_BASE}/app/installations/"
                f"{self.settings.github_installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {jwt}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Content-Type": "application/json",
                },
                body=body,
                timeout=self.settings.github_api_timeout_seconds,
            )
        except GitHubIntegrationError:
            raise
        except Exception:
            raise GitHubIntegrationError(
                "network_error",
                "GitHub authentication could not be completed.",
            ) from None

        if response.status_code < 200 or response.status_code >= 300:
            raise normalize_github_status(
                response.status_code,
                rate_limit_remaining=self._header(
                    response.headers, "X-RateLimit-Remaining"
                ),
            )
        try:
            payload: Any = json.loads(response.body)
            return _InstallationToken.model_validate(payload)
        except (ValidationError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
            raise GitHubIntegrationError(
                "invalid_authentication_response",
                "GitHub returned an invalid authentication response.",
            ) from None

    def _require_configuration(self) -> None:
        if not self._valid_id(self.settings.github_app_id):
            raise GitHubIntegrationError(
                "configuration_error",
                "A valid GitHub App ID is required.",
            )
        if not self._valid_id(self.settings.github_installation_id):
            raise GitHubIntegrationError(
                "configuration_error",
                "A valid GitHub App installation ID is required.",
            )
        self._load_private_key()

    def _load_private_key(self) -> rsa.RSAPrivateKey:
        if self._private_key is not None:
            return self._private_key
        key_text = self.settings.github_private_key
        if key_text:
            key_bytes = key_text.replace("\\n", "\n").encode("utf-8")
        elif self.settings.github_private_key_path:
            try:
                key_bytes = Path(self.settings.github_private_key_path).read_bytes()
            except OSError:
                raise GitHubIntegrationError(
                    "configuration_error",
                    "The configured GitHub App private key is unavailable.",
                ) from None
        else:
            raise GitHubIntegrationError(
                "configuration_error",
                "A GitHub App private key is required.",
            )
        try:
            key = serialization.load_pem_private_key(key_bytes, password=None)
        except (TypeError, ValueError, UnsupportedAlgorithm):
            raise GitHubIntegrationError(
                "configuration_error",
                "The configured GitHub App private key is invalid.",
            ) from None
        if not isinstance(key, rsa.RSAPrivateKey):
            raise GitHubIntegrationError(
                "configuration_error",
                "The GitHub App private key must be an RSA key.",
            )
        self._private_key = key
        return key

    @staticmethod
    def _cached_token_expiring(
        token: _InstallationToken,
        now: datetime,
    ) -> bool:
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            return True
        return expires_at <= now + timedelta(seconds=TOKEN_REFRESH_LEEWAY_SECONDS)

    @staticmethod
    def _valid_id(value: str | None) -> bool:
        return value is not None and re.fullmatch(r"[1-9][0-9]*", value) is not None

    @staticmethod
    def _base64url(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        return next(
            (value for key, value in headers.items() if key.lower() == name.lower()),
            None,
        )
