from __future__ import annotations

import logging
from collections.abc import Iterator

from backend.app.agent.providers.base import LLMProvider
from backend.app.agent.providers.errors import LLMProviderError
from backend.app.agent.providers.models import (
    LLMHealthStatus,
    LLMRequest,
    LLMResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    LLMToolCallRequest,
    LLMToolResult,
)

logger = logging.getLogger(__name__)


class ResilientLLMProvider(LLMProvider):
    """Provider wrapper that attempts a primary provider and seamlessly falls back to a local offline provider on network or API failures."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        fallback_enabled: bool = True,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.fallback_enabled = fallback_enabled

    @property
    def model_name(self) -> str:
        return self.primary.model_name

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.fallback_enabled:
            return self.primary.generate(request)
        try:
            return self.primary.generate(request)
        except LLMProviderError as exc:
            logger.warning("Primary LLM provider failed (%s). Engaging Local Offline Fallback.", exc)
            return self.fallback.generate(request)

    def generate_structured(self, request: LLMStructuredRequest) -> LLMStructuredResponse:
        if not self.fallback_enabled:
            return self.primary.generate_structured(request)
        try:
            return self.primary.generate_structured(request)
        except LLMProviderError as exc:
            logger.warning("Primary structured LLM failed (%s). Engaging Local Offline Fallback.", exc)
            return self.fallback.generate_structured(request)

    def call_tools(self, tool_calls: list[LLMToolCallRequest]) -> list[LLMToolResult]:
        try:
            return self.primary.call_tools(tool_calls)
        except Exception:
            return self.fallback.call_tools(tool_calls)

    def stream(self, request: LLMRequest) -> Iterator[str]:
        try:
            yield from self.primary.stream(request)
        except Exception:
            yield from self.fallback.stream(request)

    def health_check(self) -> LLMHealthStatus:
        primary_health = self.primary.health_check()
        if primary_health.healthy:
            return primary_health
        fallback_health = self.fallback.health_check()
        return LLMHealthStatus(
            provider=f"{self.primary.model_name}->{self.fallback.model_name}",
            healthy=fallback_health.healthy,
            model=fallback_health.model,
            message=f"Primary offline ({primary_health.message}); Fallback active: {fallback_health.message}",
        )
