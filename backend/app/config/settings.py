from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    app_name: str = "ATLAS"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    log_level: LogLevel = "INFO"

    llm_provider: str = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3
    llm_max_output_tokens: int = 2048
    llm_temperature: float = 0.2
    llm_default_system_instruction: str | None = None

    model_config = SettingsConfigDict(
        env_file="backend/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()