from __future__ import annotations

import logging
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.agent.agent import ChatAgent, ChatAgentError
from backend.app.agent.models import ChatRequest
from backend.app.agent.providers.errors import (
    ProviderAPIError,
    ProviderTimeoutError,
)
from backend.app.api.v1.github import router as github_router
from backend.app.api.v1.google import router as google_router
from backend.app.config.settings import settings
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.logging_config import SensitiveDataRedactingFormatter, redact_sensitive_text
from backend.app.core.security_middleware import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from backend.app.evaluation.models import (
    CaseEvaluationResult,
    EvaluationCategory,
)
from backend.app.security.identity import get_authenticated_user_id
from backend.app.security.rate_limit import InMemoryRateLimiter


class FailingLLMProvider:
    def __init__(self, exc: Exception | None = None, response_content: Any = None) -> None:
        self.exc = exc
        self.response_content = response_content

    def generate(self, _request: Any) -> SimpleNamespace:
        if self.exc:
            raise self.exc
        return SimpleNamespace(content=self.response_content)


def run_reliability_error_suite() -> list[CaseEvaluationResult]:
    results: list[CaseEvaluationResult] = []
    category = EvaluationCategory.RELIABILITY_ERROR
    suite_name = "reliability_and_error_handling"

    # RE-01: LLM Provider Timeout Error Handling
    t0 = perf_counter()
    provider = FailingLLMProvider(exc=ProviderTimeoutError("Connection timed out to provider."))
    agent = ChatAgent(provider=provider)
    handled_safely = False
    try:
        agent.respond(ChatRequest(message="Summarize this project"))
    except ChatAgentError:
        handled_safely = True
    duration = (perf_counter() - t0) * 1000

    results.append(
        CaseEvaluationResult(
            case_id="RE-01",
            suite=suite_name,
            category=category,
            name="LLM provider timeout safe recovery",
            description="Evaluates that model gateway timeouts raise safe ChatAgentError without leaking credentials.",
            passed=handled_safely,
            actual_output={"handled_safely": handled_safely},
            failure_reason=None if handled_safely else "Timeout was not encapsulated in ChatAgentError.",
            duration_ms=round(duration, 2),
            safety_critical=False,
            critical_invariant_violated=False,
        )
    )

    # RE-02: LLM Provider 5xx Service Error Handling
    t0 = perf_counter()
    provider = FailingLLMProvider(exc=ProviderAPIError("Upstream model service 503 unavailable."))
    agent = ChatAgent(provider=provider)
    handled_safely = False
    try:
        agent.respond(ChatRequest(message="Write a note"))
    except ChatAgentError:
        handled_safely = True
    duration = (perf_counter() - t0) * 1000

    results.append(
        CaseEvaluationResult(
            case_id="RE-02",
            suite=suite_name,
            category=category,
            name="LLM provider 5xx service outage encapsulation",
            description="Evaluates that upstream provider 5xx errors are caught and transformed to safe application errors.",
            passed=handled_safely,
            actual_output={"handled_safely": handled_safely},
            failure_reason=None if handled_safely else "Upstream 5xx was not handled safely.",
            duration_ms=round(duration, 2),
            safety_critical=False,
            critical_invariant_violated=False,
        )
    )

    # RE-03: Malformed Model Output (Empty / Whitespace)
    t0 = perf_counter()
    provider = FailingLLMProvider(response_content="   ")
    agent = ChatAgent(provider=provider)
    caught_invalid = False
    try:
        agent.respond(ChatRequest(message="Generate text"))
    except ChatAgentError as exc:
        if "invalid response" in str(exc).lower():
            caught_invalid = True
    duration = (perf_counter() - t0) * 1000

    results.append(
        CaseEvaluationResult(
            case_id="RE-03",
            suite=suite_name,
            category=category,
            name="Empty/malformed LLM output rejection",
            description="Evaluates that blank or whitespace-only model responses are rejected as invalid responses.",
            passed=caught_invalid,
            actual_output={"caught_invalid": caught_invalid},
            failure_reason=None if caught_invalid else "Blank model output was accepted.",
            duration_ms=round(duration, 2),
            safety_critical=False,
            critical_invariant_violated=False,
        )
    )

    # RE-04: Oversized Model Output (> 8000 Characters)
    t0 = perf_counter()
    oversized = "a" * 8001
    provider = FailingLLMProvider(response_content=oversized)
    agent = ChatAgent(provider=provider)
    caught_oversized = False
    try:
        agent.respond(ChatRequest(message="Generate text"))
    except ChatAgentError as exc:
        if "invalid response" in str(exc).lower():
            caught_oversized = True
    duration = (perf_counter() - t0) * 1000

    results.append(
        CaseEvaluationResult(
            case_id="RE-04",
            suite=suite_name,
            category=category,
            name="Oversized LLM response containment",
            description="Evaluates that responses exceeding the 8,000 character maximum limit are rejected.",
            passed=caught_oversized,
            actual_output={"caught_oversized": caught_oversized},
            failure_reason=None if caught_oversized else "Oversized model response was not rejected.",
            duration_ms=round(duration, 2),
            safety_critical=False,
            critical_invariant_violated=False,
        )
    )

    # RE-05: Rate Limiter Sliding Window Enforcement
    t0 = perf_counter()
    limiter = InMemoryRateLimiter()
    # 2 requests per 60 seconds
    key = "eval:rate_limit_test"
    allow1, _, _, _ = limiter.check(key, limit=2, window_seconds=60)
    allow2, _, _, _ = limiter.check(key, limit=2, window_seconds=60)
    allow3, rem, reset_secs, retry_after = limiter.check(key, limit=2, window_seconds=60)
    duration = (perf_counter() - t0) * 1000
    passed = (
        allow1 is True
        and allow2 is True
        and allow3 is False
        and rem == 0
        and retry_after > 0
    )
    results.append(
        CaseEvaluationResult(
            case_id="RE-05",
            suite=suite_name,
            category=category,
            name="Sliding-window rate limiter quota exhaustion",
            description="Evaluates that requests beyond quota are throttled with accurate retry_after duration.",
            passed=passed,
            actual_output={"allow1": allow1, "allow2": allow2, "allow3": allow3, "retry_after": retry_after},
            failure_reason=None if passed else "Rate limiter failed to throttle after quota was reached.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=not passed,
        )
    )

    # RE-06: Request Size Limit Middleware Protection
    t0 = perf_counter()
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_body_size=500)
    app.add_middleware(SecurityHeadersMiddleware)
    register_exception_handlers(app)

    @app.post("/test-size")
    async def echo_endpoint(payload: dict[str, str]) -> dict[str, str]:
        return payload

    with TestClient(app) as client:
        res = client.post("/test-size", json={"data": "x" * 1000})
        status_code = res.status_code
        err_code = res.json().get("error", {}).get("code")
        content_type_options = res.headers.get("X-Content-Type-Options")

    duration = (perf_counter() - t0) * 1000
    passed = (
        status_code == 413
        and err_code == "payload_too_large"
        and content_type_options == "nosniff"
    )
    results.append(
        CaseEvaluationResult(
            case_id="RE-06",
            suite=suite_name,
            category=category,
            name="Request body size limit middleware enforcement",
            description="Evaluates that payloads exceeding max body size return HTTP 413 with security headers intact.",
            passed=passed,
            actual_output={"status_code": status_code, "error_code": err_code, "nosniff": content_type_options},
            failure_reason=None if passed else "Oversized request was not rejected with 413 and security headers.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=not passed,
        )
    )

    # RE-07: Sensitive Data Log Redaction Verification
    t0 = perf_counter()
    test_message = (
        "OAuth received code=4/0AY0e-gSecretAuthCode123 "
        "User supplied Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig "
        '{"client_secret": "my_secret_999", "password": "super_secret_pw"}'
    )
    redacted = redact_sensitive_text(test_message)
    duration = (perf_counter() - t0) * 1000

    secret_found = (
        "my_secret_999" in redacted
        or "super_secret_pw" in redacted
        or "4/0AY0e-gSecretAuthCode123" in redacted
        or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" in redacted
    )
    passed = not secret_found and '"client_secret": "[REDACTED]"' in redacted and "code=[REDACTED]" in redacted
    results.append(
        CaseEvaluationResult(
            case_id="RE-07",
            suite=suite_name,
            category=category,
            name="Automated sensitive data log redaction",
            description="Evaluates that Bearer tokens, JWTs, OAuth codes, and passwords are redacted across strings and JSON.",
            passed=passed,
            actual_output={"secrets_found_in_log": secret_found, "redacted_sample": redacted[:100]},
            failure_reason=None if passed else "Log redaction failed to scrub sensitive credentials.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=secret_found,
        )
    )

    # RE-08: Third-Party Integrations Disabled Safeguard
    t0 = perf_counter()
    int_app = FastAPI()
    int_app.include_router(google_router, prefix="/api/v1")
    int_app.include_router(github_router, prefix="/api/v1")
    int_app.dependency_overrides[get_authenticated_user_id] = lambda: "ef3e7347-a8e9-4d63-90cf-a21d5c855515"

    with TestClient(int_app) as client:
        g_res = client.get("/api/v1/google/status")
        gh_res = client.get("/api/v1/github/status")
        g_actions = g_res.json().get("actions_enabled")
        gh_actions = gh_res.json().get("actions_enabled")

    duration = (perf_counter() - t0) * 1000
    passed = g_actions is False and gh_actions is False
    critical_violated = g_actions is True or gh_actions is True
    results.append(
        CaseEvaluationResult(
            case_id="RE-08",
            suite=suite_name,
            category=category,
            name="Integration actions disabled safety invariant",
            description="Evaluates that Google and GitHub integrations report actions_enabled=False to prevent unauthorized side-effects.",
            passed=passed,
            actual_output={"google_actions": g_actions, "github_actions": gh_actions},
            failure_reason=None if passed else "Integration actions were unexpectedly enabled.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=critical_violated,
        )
    )

    return results
