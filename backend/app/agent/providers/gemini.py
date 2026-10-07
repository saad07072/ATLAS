from __future__ import annotations

import json
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from backend.app.agent.providers.base import LLMProvider
from backend.app.agent.providers.errors import (
    InvalidStructuredOutputError,
    ProviderAPIError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    RetryExhaustedError,
)
from backend.app.agent.providers.models import (
    LLMHealthStatus,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    LLMToolCallRequest,
    LLMToolResult,
    LLMUsage,
)
from backend.app.config.settings import Settings


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or Settings()
        if not self.settings.gemini_api_key:
            raise ProviderConfigurationError("GEMINI_API_KEY is not configured.")

        self.model_name = self.settings.gemini_model
        self.timeout = max(1.0, float(self.settings.llm_timeout_seconds))
        self.max_retries = max(0, int(self.settings.llm_max_retries))
        self.client = client or genai.Client(api_key=self.settings.gemini_api_key)

    @property
    def model_name(self) -> str:
        return self._model_name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self._model_name = value or "gemini-2.0-flash"

    def generate(self, request: LLMRequest) -> LLMResponse:
        def _operation() -> LLMResponse:
            response = self.client.models.generate_content(
                model=request.model or self.model_name,
                contents=self._to_contents(request.messages),
                config=self._build_config(request),
            )
            return self._map_response(response, request.model or self.model_name)

        return self._retry(_operation, "generate")

    def generate_structured(
        self,
        request: LLMStructuredRequest,
    ) -> LLMStructuredResponse:
        schema = self._normalize_schema(request.response_schema)

        def _operation() -> LLMStructuredResponse:
            response = self.client.models.generate_content(
                model=request.model or self.model_name,
                contents=self._to_contents(request.messages),
                config=self._build_config(request, schema=schema),
            )
            parsed = self._parse_structured_payload(response)
            return LLMStructuredResponse(
                content=json.dumps(parsed, ensure_ascii=False),
                model=request.model or self.model_name,
                finish_reason=self._extract_finish_reason(response),
                usage=self._extract_usage(response),
                parsed=parsed,
            )

        return self._retry(_operation, "generate_structured")

    def call_tools(
        self,
        tool_calls: list[LLMToolCallRequest],
    ) -> list[LLMToolResult]:
        return [
            LLMToolResult(
                name=call.name,
                content=(
                    "Tool execution is intentionally deferred to the ATLAS agent layer; "
                    "provider adapters do not execute external actions."
                ),
                success=False,
            )
            for call in tool_calls
        ]

    def stream(self, request: LLMRequest):
        raise NotImplementedError("Streaming is intentionally deferred to later phases.")

    def health_check(self) -> LLMHealthStatus:
        if not self.settings.gemini_api_key:
            raise ProviderConfigurationError("GEMINI_API_KEY is not configured.")

        return LLMHealthStatus(
            provider="gemini",
            healthy=True,
            model=self.model_name,
            message="Gemini provider configured successfully.",
        )

    def _build_config(
        self,
        request: LLMRequest,
        *,
        schema: dict[str, Any] | None = None,
    ) -> types.GenerateContentConfig:
        config_kwargs: dict[str, Any] = {
            "temperature": request.temperature,
            "max_output_tokens": (
                request.max_output_tokens
                if request.max_output_tokens is not None
                else self.settings.llm_max_output_tokens
            ),
            "system_instruction": (
                request.system_instruction
                or self.settings.llm_default_system_instruction
            ),
        }

        if schema:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = schema

        return types.GenerateContentConfig(**config_kwargs)

    def _to_contents(self, messages: list[LLMMessage]) -> list[str]:
        return [message.content for message in messages]

    def _map_response(
        self,
        response: Any,
        model_name: str,
    ) -> LLMResponse:
        content = self._extract_text(response)
        return LLMResponse(
            content=content,
            model=model_name,
            finish_reason=self._extract_finish_reason(response),
            usage=self._extract_usage(response),
        )

    def _extract_text(self, response: Any) -> str:
        if hasattr(response, "text") and response.text:
            return str(response.text)

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            text_chunks = []
            for part in parts:
                if getattr(part, "text", None):
                    text_chunks.append(str(part.text))
            if text_chunks:
                return "".join(text_chunks)

        return ""

    def _extract_finish_reason(self, response: Any) -> str | None:
        try:
            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                return None
            finish_reason = getattr(candidates[0], "finish_reason", None)
            if finish_reason is None:
                return None
            if hasattr(finish_reason, "name"):
                return str(finish_reason.name)
            return str(finish_reason)
        except (AttributeError, TypeError, IndexError):
            return None

    def _extract_usage(self, response: Any) -> LLMUsage | None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None

        return LLMUsage(
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "completion_token_count", None),
            total_tokens=getattr(usage, "total_token_count", None),
        )

    def _normalize_schema(
        self,
        schema: dict[str, Any] | type[Any] | None,
    ) -> dict[str, Any] | None:
        if schema is None:
            return None
        if isinstance(schema, dict):
            return schema
        if hasattr(schema, "model_json_schema"):
            return schema.model_json_schema()
        raise InvalidStructuredOutputError(
            "Structured output schemas must be either a JSON schema dict or a Pydantic model."
        )

    def _parse_structured_payload(self, response: Any) -> dict[str, Any]:
        payload = getattr(response, "parsed", None)
        if payload is not None:
            if hasattr(payload, "model_dump"):
                return payload.model_dump()
            if isinstance(payload, dict):
                return payload

        text = self._extract_text(response)
        if not text:
            raise InvalidStructuredOutputError(
                "Structured generation returned no parseable content."
            )

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidStructuredOutputError(
                "Structured output did not contain valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise InvalidStructuredOutputError(
                "Structured output must decode to a JSON object."
            )

        return parsed

    def _retry(self, operation, operation_name: str):
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                return operation()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                translated = self._translate_exception(exc)
                if attempt >= self.max_retries + 1:
                    raise RetryExhaustedError(
                        f"{operation_name} failed after {self.max_retries + 1} attempts."
                    ) from translated
                if not self._is_retryable(translated):
                    raise translated
                time.sleep(min(2**attempt, 8))

        if last_error is not None:
            raise self._translate_exception(last_error)

        raise RetryExhaustedError(f"{operation_name} failed without a captured error.")

    def _translate_exception(self, exc: Exception) -> Exception:
        if isinstance(exc, ProviderConfigurationError):
            return exc
        if isinstance(exc, ProviderAuthenticationError):
            return exc
        if isinstance(exc, ProviderTimeoutError):
            return exc
        if isinstance(exc, ProviderRateLimitError):
            return exc
        if isinstance(exc, InvalidStructuredOutputError):
            return exc

        status = (
            getattr(exc, "status", None)
            or getattr(exc, "status_code", None)
            or getattr(exc, "code", None)
        )
        message = str(exc).lower()

        if isinstance(exc, TimeoutError):
            return ProviderTimeoutError("Gemini request timed out.")
        if status == 401 or "api key" in message or "unauthorized" in message:
            return ProviderAuthenticationError("Gemini authentication failed.")
        if status == 429 or "rate limit" in message:
            return ProviderRateLimitError("Gemini rate limit exceeded.")
        if status in {400, 500} or isinstance(exc, (APIError, ClientError, ServerError)):
            return ProviderAPIError(f"Gemini API request failed: {exc}")

        return ProviderAPIError(f"Gemini provider request failed: {exc}")

    def _is_retryable(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (ProviderTimeoutError, ProviderRateLimitError, ProviderAPIError),
        )
