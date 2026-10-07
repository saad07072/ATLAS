from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from backend.app.agent.providers.models import (
    LLMHealthStatus,
    LLMRequest,
    LLMResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    LLMToolCallRequest,
    LLMToolResult,
)


class LLMProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the provider's configured default model name."""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a text response from the configured provider."""

    @abstractmethod
    def generate_structured(
        self,
        request: LLMStructuredRequest,
    ) -> LLMStructuredResponse:
        """Generate a structured response validated against the supplied schema."""

    @abstractmethod
    def call_tools(
        self,
        tool_calls: list[LLMToolCallRequest],
    ) -> list[LLMToolResult]:
        """Provide a tool-call abstraction for future agent execution layers."""

    @abstractmethod
    def stream(self, request: LLMRequest) -> Iterator[str]:
        """Stream output when the provider supports it. Deferred for later phases."""

    @abstractmethod
    def health_check(self) -> LLMHealthStatus:
        """Validate the capabilities and configuration of the provider."""
