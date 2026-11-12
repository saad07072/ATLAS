from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Iterator

from backend.app.agent.providers.base import LLMProvider
from backend.app.agent.providers.models import (
    LLMHealthStatus,
    LLMRequest,
    LLMResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    LLMToolCallRequest,
    LLMToolResult,
    LLMUsage,
)
from backend.app.config.settings import Settings

logger = logging.getLogger(__name__)


class LocalOfflineProvider(LLMProvider):
    """Local offline LLM provider supporting local Ollama or built-in deterministic heuristic synthesis."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        self.base_url = (
            getattr(settings, "ollama_base_url", "http://127.0.0.1:11434")
            if settings
            else "http://127.0.0.1:11434"
        )
        self.model = (
            getattr(settings, "ollama_model", "llama3")
            if settings
            else "llama3"
        )

    @property
    def model_name(self) -> str:
        return f"local-offline:{self.model}"

    def _query_ollama(self, prompt: str, timeout: float = 3.0) -> str | None:
        """Attempt to query local Ollama server if running."""
        try:
            url = f"{self.base_url.rstrip('/')}/api/generate"
            payload = json.dumps(
                {"model": self.model, "prompt": prompt, "stream": False}
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("response", "").strip()
                    if text:
                        return text
        except Exception as exc:
            logger.debug("Ollama local query not available: %s", exc)
        return None

    def _synthesize_local_response(self, user_prompt: str) -> str:
        """Local heuristic synthesis when offline and without Ollama daemon."""
        lower = user_prompt.lower()
        if any(g in lower for g in ["hello", "hi", "hey", "good morning", "good evening", "greetings"]):
            return (
                "Good day, sir. ATLAS Local Offline Core is operational. "
                "Host desktop controls, hardware vitals, and workflow protocols are fully accessible."
            )
        if any(h in lower for h in ["help", "what can you do", "capabilities"]):
            return (
                "I am running in Local Offline Mode, sir. All core workstation controls remain operational: "
                "inspecting system vitals, launching and closing applications, adjusting volume and media playback, "
                "locking the screen, and executing custom multi-app workflow protocols."
            )
        if "who are you" in lower:
            return "I am ATLAS, your autonomous task assistant, currently executing in Local Offline Mode."

        return (
            "I have acknowledged your request, sir. I am currently operating in Local Offline Mode without cloud neural synthesis. "
            "All physical workstation actions, application controls, and hardware diagnostics remain active and standing by."
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        prompt = ""
        for m in reversed(request.messages):
            if m.role == "user":
                prompt = m.content
                break
        if not prompt and request.messages:
            prompt = request.messages[-1].content

        ollama_reply = self._query_ollama(prompt)
        if ollama_reply:
            return LLMResponse(
                content=ollama_reply,
                model=self.model_name,
                finish_reason="stop",
                usage=LLMUsage(
                    input_tokens=len(prompt.split()),
                    output_tokens=len(ollama_reply.split()),
                ),
            )

        content = self._synthesize_local_response(prompt)
        return LLMResponse(
            content=content,
            model="local-offline:heuristic",
            finish_reason="stop",
            usage=LLMUsage(input_tokens=10, output_tokens=25),
        )

    def generate_structured(self, request: LLMStructuredRequest) -> LLMStructuredResponse:
        content = self.generate(request).content
        return LLMStructuredResponse(
            content=content,
            model=self.model_name,
            parsed={"status": "offline_acknowledged", "message": content},
        )

    def call_tools(self, tool_calls: list[LLMToolCallRequest]) -> list[LLMToolResult]:
        return [
            LLMToolResult(
                name=tc.name,
                content=json.dumps({"status": "offline_standby"}),
                success=True,
            )
            for tc in tool_calls
        ]

    def stream(self, request: LLMRequest) -> Iterator[str]:
        yield self.generate(request).content

    def health_check(self) -> LLMHealthStatus:
        ollama_active = self._query_ollama("test", timeout=1.0) is not None
        return LLMHealthStatus(
            provider="local_offline",
            healthy=True,
            model=self.model_name if ollama_active else "local-offline:heuristic",
            message="Local offline engine healthy" + (" (Ollama active)" if ollama_active else " (Heuristic mode)"),
        )
