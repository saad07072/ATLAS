from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from google.genai.errors import APIError

from backend.app.agent.providers.errors import RetryExhaustedError, ProviderTimeoutError
from backend.app.agent.providers.factory import get_llm_provider
from backend.app.agent.providers.gemini import GeminiProvider
from backend.app.agent.providers.local_offline import LocalOfflineProvider
from backend.app.agent.providers.resilient import ResilientLLMProvider
from backend.app.agent.providers.models import (
    LLMMessage,
    LLMRequest,
    LLMStructuredRequest,
)
from backend.app.config.settings import Settings


class LLMProviderTests(unittest.TestCase):
    def test_settings_include_llm_provider_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configured = Settings(_env_file=None)

        self.assertEqual(configured.llm_provider, "gemini")
        self.assertEqual(configured.gemini_model, "gemini-flash-latest")
        self.assertEqual(configured.llm_timeout_seconds, 30.0)
        self.assertEqual(configured.llm_max_retries, 3)
        self.assertEqual(configured.llm_max_output_tokens, 2048)

    def test_factory_returns_gemini_provider(self) -> None:
        fake_settings = Settings(
            _env_file=None,
            llm_provider="gemini",
            gemini_api_key="test-key",
        )

        with patch("backend.app.agent.providers.factory.settings", fake_settings):
            provider = get_llm_provider()

        self.assertIsInstance(provider, GeminiProvider)

    def test_gemini_generate_maps_response_to_provider_model(self) -> None:
        fake_settings = Settings(
            _env_file=None,
            gemini_api_key="test-key",
            gemini_model="gemini-2.0-flash",
        )
        provider = GeminiProvider(settings=fake_settings)

        mock_sdk_response = Mock()
        mock_sdk_response.text = "hello from gemini"
        mock_candidate = Mock()
        mock_candidate.finish_reason = "STOP"
        mock_candidate.content = Mock(parts=[Mock(text="hello from gemini")])
        mock_sdk_response.candidates = [mock_candidate]
        mock_sdk_response.usage_metadata = Mock(
            prompt_token_count=10,
            completion_token_count=5,
            total_token_count=15,
        )

        provider.client = Mock()
        provider.client.models.generate_content.return_value = mock_sdk_response

        response = provider.generate(
            LLMRequest(
                messages=[LLMMessage(role="user", content="Say hello")],
                temperature=0.3,
                max_output_tokens=128,
            )
        )

        self.assertEqual(response.content, "hello from gemini")
        self.assertEqual(response.model, "gemini-2.0-flash")
        self.assertEqual(response.finish_reason, "STOP")
        self.assertIsNotNone(response.usage)
        self.assertEqual(response.usage.total_tokens, 15)

    def test_gemini_generate_structured_deserializes_json_payload(self) -> None:
        fake_settings = Settings(
            _env_file=None,
            gemini_api_key="test-key",
            gemini_model="gemini-2.0-flash",
        )
        provider = GeminiProvider(settings=fake_settings)

        mock_sdk_response = Mock()
        mock_sdk_response.text = '{"status": "ok", "count": 2}'
        mock_sdk_response.parsed = {"status": "ok", "count": 2}
        mock_sdk_response.candidates = [
            Mock(
                finish_reason="STOP",
                content=Mock(parts=[Mock(text='{"status": "ok", "count": 2}')]),
            )
        ]
        mock_sdk_response.usage_metadata = Mock(
            prompt_token_count=12,
            completion_token_count=8,
            total_token_count=20,
        )

        provider.client = Mock()
        provider.client.models.generate_content.return_value = mock_sdk_response

        request = LLMStructuredRequest(
            messages=[LLMMessage(role="user", content="Return structured JSON")],
            response_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["status", "count"],
            },
        )

        result = provider.generate_structured(request)

        self.assertEqual(result.parsed["status"], "ok")
        self.assertEqual(result.parsed["count"], 2)
        self.assertEqual(result.model, "gemini-2.0-flash")
        self.assertEqual(result.finish_reason, "STOP")

    def test_retry_exhaustion_raises_provider_error(self) -> None:
        fake_settings = Settings(
            _env_file=None,
            gemini_api_key="test-key",
            gemini_model="gemini-2.0-flash",
            llm_max_retries=2,
        )
        provider = GeminiProvider(settings=fake_settings)
        provider.client = Mock()
        provider.client.models.generate_content.side_effect = APIError(
            429,
            {"error": {"message": "rate limit exceeded"}},
        )

        with self.assertRaises(RetryExhaustedError):
            provider.generate(
                LLMRequest(
                    messages=[LLMMessage(role="user", content="trigger retry")],
                )
            )

    def test_factory_returns_local_provider(self) -> None:
        fake_settings = Settings(_env_file=None, llm_provider="local")
        with patch("backend.app.agent.providers.factory.settings", fake_settings):
            provider = get_llm_provider()
        self.assertIsInstance(provider, LocalOfflineProvider)

    def test_factory_returns_resilient_provider_when_enabled(self) -> None:
        fake_settings = Settings(
            _env_file=None,
            llm_provider="gemini",
            gemini_api_key="test-key",
            offline_fallback_enabled=True,
        )
        with patch("backend.app.agent.providers.factory.settings", fake_settings):
            provider = get_llm_provider()
        self.assertIsInstance(provider, ResilientLLMProvider)

    def test_local_offline_provider_generate_heuristic(self) -> None:
        provider = LocalOfflineProvider()
        response = provider.generate(
            LLMRequest(messages=[LLMMessage(role="user", content="hello jarvis")])
        )
        self.assertIn("Local Offline", response.content)
        self.assertEqual(response.finish_reason, "stop")

    def test_resilient_provider_falls_back_on_primary_failure(self) -> None:
        mock_primary = Mock()
        mock_primary.generate.side_effect = ProviderTimeoutError("Cloud connection timed out")
        fallback = LocalOfflineProvider()
        resilient = ResilientLLMProvider(primary=mock_primary, fallback=fallback, fallback_enabled=True)
        response = resilient.generate(
            LLMRequest(messages=[LLMMessage(role="user", content="what can you do")])
        )
        self.assertIn("Local Offline", response.content)


if __name__ == "__main__":
    unittest.main()
