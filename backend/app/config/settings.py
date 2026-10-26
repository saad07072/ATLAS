from pathlib import Path
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    app_name: str = "ATLAS"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    log_level: LogLevel = "INFO"

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> bool:
        if isinstance(value, str):
            val_lower = value.strip().lower()
            if val_lower in {"true", "1", "yes", "on", "debug", "dev", "development"}:
                return True
            if val_lower in {"false", "0", "no", "off", "release", "prod", "production"}:
                return False
        return bool(value)

    @field_validator("google_token_encryption_key", mode="before")
    @classmethod
    def parse_encryption_key(cls, value: Any) -> Any:
        if isinstance(value, str):
            val = value.strip().strip("'\"")
            if len(val) == 43 and not val.endswith("="):
                val += "="
            return val
        return value

    llm_provider: str = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3
    llm_max_output_tokens: int = 2048
    llm_temperature: float = 0.2
    llm_default_system_instruction: str | None = None

    google_oauth_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("google_oauth_client_id", "google_client_id"),
    )
    google_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "google_oauth_client_secret", "google_client_secret"
        ),
    )
    google_oauth_redirect_uri: str | None = Field(
        default="http://127.0.0.1:8001/api/v1/google/oauth/callback",
        validation_alias=AliasChoices(
            "google_oauth_redirect_uri", "google_redirect_uri"
        ),
    )
    google_token_encryption_key: str | None = None
    google_api_timeout_seconds: float = 15.0

    github_app_id: str | None = None
    github_installation_id: str | None = None
    github_private_key: str | None = Field(default=None, repr=False)
    github_private_key_path: str | None = None
    github_api_timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    database_url: str | None = Field(default=None, repr=False)
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = Field(default=None, repr=False)

    # Rate Limiting & Security Hardening
    rate_limit_enabled: bool = True
    rate_limit_chat: str = "60/minute"
    rate_limit_workflows: str = "30/minute"
    rate_limit_confirmations: str = "30/minute"
    rate_limit_oauth: str = "20/minute"
    rate_limit_authenticated_default: str = "120/minute"
    rate_limit_unauthenticated_default: str = "60/minute"

    trust_proxy_headers: bool = False
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    enable_hsts: bool = False
    max_request_body_bytes: int = 1_048_576  # 1 MB

    model_config = SettingsConfigDict(
        env_file=(str(Path(__file__).resolve().parent.parent.parent / ".env"), "backend/.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()