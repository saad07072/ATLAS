from __future__ import annotations

import logging
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.agent.agent import ChatAgent
from backend.app.agent.models import ChatRequest, ChatResponse
from backend.app.agent.providers.base import LLMProvider, LLMResponse
from backend.app.api.v1.chat import get_chat_agent, router as chat_router
from backend.app.api.v1.github import router as github_router
from backend.app.api.v1.google import router as google_router
from backend.app.api.v1.workflows import router as workflows_router
from backend.app.config.settings import settings
from backend.app.conversations.models import ConversationRecord
from backend.app.conversations.runtime import get_conversation_service
from backend.app.conversations.service import ConversationService
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.logging_config import SensitiveDataRedactingFormatter, redact_sensitive_text
from backend.app.core.security_middleware import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.runtime import get_github_authentication
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.runtime import get_google_oauth_service
from backend.app.security.identity import (
    get_access_token_verifier,
    get_authenticated_user_id,
    get_optional_authenticated_user_id,
    require_authenticated_user_id,
)
from backend.app.security.models import (
    ConfirmationState,
    PermissionDecision,
    PermissionId,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.security.rate_limit import (
    InMemoryRateLimiter,
    parse_rate_limit,
    rate_limiter_instance,
    resolve_client_identity,
)
from backend.app.tools.demo import EchoTool
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.registry import ToolRegistry
from backend.app.workflows.engine import WorkflowEngine
from backend.app.workflows.models import (
    StepConfirmationRequest,
    WorkflowDefinition,
    WorkflowStepDefinition,
)
from backend.app.workflows.repository import InMemoryWorkflowRepository
from backend.app.workflows.runtime import get_workflow_service
from backend.app.workflows.service import WorkflowService
from backend.app.workflows.tools import HighRiskActionTool, VerifyTool
from backend.app.workflows.validator import WorkflowValidator
from backend.tests.test_conversations import InMemoryConversationRepository

USER_A = UUID("ef3e7347-a8e9-4d63-90cf-a21d5c855515")
USER_B = UUID("43ad3973-5d96-4608-8b7b-3e774106429a")


class MockLLMProvider:
    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.call_count += 1
        return SimpleNamespace(content="Secure response.")


def create_test_workflow_service() -> tuple[WorkflowService, InMemoryWorkflowRepository]:
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(VerifyTool())
    registry.register(HighRiskActionTool())

    policy = PermissionPolicy({
        ("system.echo", PermissionId.SYSTEM_ECHO): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.LOW,
            permission_required=False,
        ),
        ("system.verify", PermissionId.TEST_RECORD): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.LOW,
            permission_required=False,
        ),
        ("test.action.high_risk", PermissionId.TEST_RECORD): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.HIGH,
            permission_required=True,
            confirmation_required=True,
        ),
    })
    permission_engine = PermissionEngine(policy)
    executor = ToolExecutionService(registry, permission_engine)
    repository = InMemoryWorkflowRepository()
    validator = WorkflowValidator(registry)
    engine = WorkflowEngine(repository, executor, permission_engine)
    service = WorkflowService(repository, validator, engine)
    return service, repository


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        rate_limiter_instance.reset()
        self.original_rate_limit_enabled = settings.rate_limit_enabled
        self.original_chat_limit = settings.rate_limit_chat
        self.original_workflows_limit = settings.rate_limit_workflows
        self.original_confirmations_limit = settings.rate_limit_confirmations
        self.original_trust_proxy = settings.trust_proxy_headers
        self.original_trusted_proxies = settings.trusted_proxies

        settings.rate_limit_enabled = True

        # Setup mock LLM & agent
        self.mock_llm = MockLLMProvider()
        self.tool_executor = ToolExecutionService(ToolRegistry(), PermissionEngine(PermissionPolicy({})))
        self.chat_agent = ChatAgent(
            provider=self.mock_llm,
            secret=None,
            tool_executor=self.tool_executor,
            memory_service=None,
        )

        # Setup conversation repo & service
        self.conv_repo = InMemoryConversationRepository()
        self.conv_service = ConversationService(self.conv_repo)

        # Setup workflow service
        self.wf_service, self.wf_repo = create_test_workflow_service()

        # Build FastAPI test app
        self.app = FastAPI()
        self.app.add_middleware(RequestSizeLimitMiddleware, max_body_size=1024)
        self.app.add_middleware(SecurityHeadersMiddleware)
        register_exception_handlers(self.app)

        self.app.include_router(chat_router, prefix="/api/v1")
        self.app.include_router(workflows_router, prefix="/api/v1")
        self.app.include_router(google_router, prefix="/api/v1")
        self.app.include_router(github_router, prefix="/api/v1")

        # Dependency overrides
        self.current_user: UUID | None = USER_A
        self.app.dependency_overrides[get_chat_agent] = lambda: self.chat_agent
        self.app.dependency_overrides[get_conversation_service] = lambda: self.conv_service
        self.app.dependency_overrides[get_workflow_service] = lambda: self.wf_service
        self.app.dependency_overrides[get_optional_authenticated_user_id] = lambda: self.current_user
        self.app.dependency_overrides[get_authenticated_user_id] = lambda: (
            self.current_user if self.current_user else self._raise_401()
        )
        self.app.dependency_overrides[require_authenticated_user_id] = lambda: (
            self.current_user if self.current_user else self._raise_401()
        )

    def tearDown(self) -> None:
        rate_limiter_instance.reset()
        settings.rate_limit_enabled = self.original_rate_limit_enabled
        settings.rate_limit_chat = self.original_chat_limit
        settings.rate_limit_workflows = self.original_workflows_limit
        settings.rate_limit_confirmations = self.original_confirmations_limit
        settings.trust_proxy_headers = self.original_trust_proxy
        settings.trusted_proxies = self.original_trusted_proxies

    @staticmethod
    def _raise_401() -> None:
        from backend.app.core.exceptions import ApplicationError
        raise ApplicationError("Authentication required", code="authentication_required", status_code=401)

    # 1. Rate Limiting Tests
    def test_chat_rate_limiting_triggers_429_and_retry_after_headers(self) -> None:
        settings.rate_limit_chat = "2/minute"
        with TestClient(self.app) as client:
            conv = self.conv_service.create(str(USER_A), "Test Conv")

            # 1st request -> allowed
            res1 = client.post("/api/v1/chat", json={"message": "msg 1", "conversation_id": conv.id})
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(res1.headers.get("X-RateLimit-Limit"), "2")
            self.assertEqual(res1.headers.get("X-RateLimit-Remaining"), "1")

            # 2nd request -> allowed
            res2 = client.post("/api/v1/chat", json={"message": "msg 2", "conversation_id": conv.id})
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.headers.get("X-RateLimit-Remaining"), "0")

            # 3rd request -> rate limit exceeded (429)
            res3 = client.post("/api/v1/chat", json={"message": "msg 3", "conversation_id": conv.id})
            self.assertEqual(res3.status_code, 429)
            self.assertIn("Retry-After", res3.headers)
            self.assertTrue(int(res3.headers["Retry-After"]) > 0)
            self.assertEqual(res3.headers.get("X-RateLimit-Remaining"), "0")
            body = res3.json()
            self.assertEqual(body["error"]["code"], "rate_limit_exceeded")
            self.assertIn("Rate limit exceeded for chat", body["error"]["message"])

    def test_rate_limited_chat_does_not_invoke_llm(self) -> None:
        settings.rate_limit_chat = "1/minute"
        with TestClient(self.app) as client:
            conv = self.conv_service.create(str(USER_A), "Test Conv")

            # First call succeeds and increments LLM call count
            client.post("/api/v1/chat", json={"message": "msg 1", "conversation_id": conv.id})
            self.assertEqual(self.mock_llm.call_count, 1)

            # Second call throttled at dependency stage
            res2 = client.post("/api/v1/chat", json={"message": "msg 2", "conversation_id": conv.id})
            self.assertEqual(res2.status_code, 429)

            # Verify LLM was NOT invoked a second time!
            self.assertEqual(self.mock_llm.call_count, 1)

    def test_rate_limiting_isolated_per_authenticated_user(self) -> None:
        settings.rate_limit_chat = "1/minute"
        with TestClient(self.app) as client:
            conv_a = self.conv_service.create(str(USER_A), "User A Conv")
            conv_b = self.conv_service.create(str(USER_B), "User B Conv")

            # User A uses quota
            self.current_user = USER_A
            res_a1 = client.post("/api/v1/chat", json={"message": "hello from A", "conversation_id": conv_a.id})
            self.assertEqual(res_a1.status_code, 200)

            res_a2 = client.post("/api/v1/chat", json={"message": "another from A", "conversation_id": conv_a.id})
            self.assertEqual(res_a2.status_code, 429)

            # User B still has fresh quota!
            self.current_user = USER_B
            res_b1 = client.post("/api/v1/chat", json={"message": "hello from B", "conversation_id": conv_b.id})
            self.assertEqual(res_b1.status_code, 200)

    def test_workflow_start_and_confirmation_rate_limiting(self) -> None:
        settings.rate_limit_workflows = "1/minute"
        settings.rate_limit_confirmations = "1/minute"

        with TestClient(self.app) as client:
            wf_def = WorkflowDefinition(
                title="Rate Limit WF",
                user_request="run",
                steps=[
                    WorkflowStepDefinition(
                        step_id="step_echo",
                        title="Echo",
                        tool_name="system.echo",
                        arguments={"message": "hi"},
                    )
                ],
            )
            wf1 = self.wf_service.create_workflow(str(USER_A), wf_def)

            # Start 1st workflow -> 200
            res1 = client.post(f"/api/v1/workflows/{wf1.id}/start")
            self.assertEqual(res1.status_code, 200)

            # Start 2nd workflow -> 429
            wf2 = self.wf_service.create_workflow(str(USER_A), wf_def)
            res2 = client.post(f"/api/v1/workflows/{wf2.id}/start")
            self.assertEqual(res2.status_code, 429)
            self.assertEqual(res2.json()["error"]["code"], "rate_limit_exceeded")

    def test_rate_limit_can_be_disabled(self) -> None:
        settings.rate_limit_enabled = False
        settings.rate_limit_chat = "1/minute"
        with TestClient(self.app) as client:
            conv = self.conv_service.create(str(USER_A), "Test Conv")
            res1 = client.post("/api/v1/chat", json={"message": "msg 1", "conversation_id": conv.id})
            res2 = client.post("/api/v1/chat", json={"message": "msg 2", "conversation_id": conv.id})
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(res2.status_code, 200)

    def test_anonymous_ip_resolution_rejects_spoofed_forwarded_for_when_proxy_untrusted(self) -> None:
        settings.trust_proxy_headers = False
        request = SimpleNamespace(
            client=SimpleNamespace(host="192.168.1.50"),
            headers={"x-forwarded-for": "10.0.0.1"},
        )
        # Should NOT trust the spoofed 10.0.0.1 header
        identity = resolve_client_identity(request, user_id=None)  # type: ignore[arg-type]
        self.assertEqual(identity, "ip:192.168.1.50")

    def test_anonymous_ip_resolution_trusts_forwarded_for_from_trusted_proxy(self) -> None:
        settings.trust_proxy_headers = True
        settings.trusted_proxies = ["127.0.0.1", "10.0.0.2"]
        request = SimpleNamespace(
            client=SimpleNamespace(host="10.0.0.2"),
            headers={"x-forwarded-for": "203.0.113.195, 10.0.0.2"},
        )
        identity = resolve_client_identity(request, user_id=None)  # type: ignore[arg-type]
        self.assertEqual(identity, "ip:203.0.113.195")

    # 2. Security Headers & CORS Tests
    def test_security_headers_present_on_responses(self) -> None:
        with TestClient(self.app) as client:
            res = client.get("/api/v1/workflows")
            self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
            self.assertEqual(res.headers.get("Permissions-Policy"), "geolocation=(), camera=(), microphone=(self)")
            self.assertEqual(res.headers.get("X-Permitted-Cross-Domain-Policies"), "none")
            self.assertIn("default-src 'none'", res.headers.get("Content-Security-Policy", ""))

    # 3. Request Body Size Limits
    def test_request_exceeding_max_body_size_returns_413(self) -> None:
        with TestClient(self.app) as client:
            # Our app setup has max_body_size=1024 bytes (1 KB)
            oversized_message = "x" * 2000
            res = client.post("/api/v1/chat", json={"message": oversized_message})
            self.assertEqual(res.status_code, 413)
            body = res.json()
            self.assertEqual(body["error"]["code"], "payload_too_large")
            self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")

    # 4. Sensitive Data Log Redaction
    def test_sensitive_data_log_redaction(self) -> None:
        sample_log = (
            "User authorized with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig "
            "password=my_secret_pass "
            "code=4/0AY0e-gSecretAuthCode123 "
            '{"client_secret": "json_secret_val", "auth_token": "bearer_999"}'
        )
        redacted = redact_sensitive_text(sample_log)
        self.assertNotIn("my_secret_pass", redacted)
        self.assertNotIn("4/0AY0e-gSecretAuthCode123", redacted)
        self.assertNotIn("json_secret_val", redacted)
        self.assertNotIn("bearer_999", redacted)
        self.assertIn("password=[REDACTED]", redacted)
        self.assertIn("code=[REDACTED]", redacted)
        self.assertIn('"client_secret": "[REDACTED]"', redacted)
        self.assertIn('"auth_token": "[REDACTED]"', redacted)
        self.assertIn("Bearer [REDACTED]", redacted)

    def test_redacting_formatter_redacts_log_record(self) -> None:
        formatter = SensitiveDataRedactingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="API response contained Bearer secret_token_xyz and api_key=super_secret_key",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        self.assertNotIn("secret_token_xyz", formatted)
        self.assertNotIn("super_secret_key", formatted)
        self.assertIn("Bearer [REDACTED]", formatted)
        self.assertIn("api_key=[REDACTED]", formatted)

    # 5. Integration Execution Safety
    def test_google_and_github_actions_strictly_disabled(self) -> None:
        with TestClient(self.app) as client:
            res_gh = client.get("/api/v1/github/status")
            self.assertEqual(res_gh.status_code, 200)
            self.assertFalse(res_gh.json()["actions_enabled"])

            res_g = client.get("/api/v1/google/status")
            self.assertEqual(res_g.status_code, 200)
            self.assertFalse(res_g.json()["actions_enabled"])


if __name__ == "__main__":
    unittest.main()
