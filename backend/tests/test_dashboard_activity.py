import json
import unittest
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import FastAPI
from starlette.types import Message, Scope

from backend.app.api.v1.dashboard import router as dashboard_router
from backend.app.api.v1.workflows import router as workflows_router
from backend.app.conversations.errors import ConversationStoreUnavailable
from backend.app.conversations.models import ConversationRecord
from backend.app.conversations.runtime import get_conversation_service
from backend.app.conversations.service import ConversationService
from backend.tests.test_conversations import InMemoryConversationRepository
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.runtime import get_github_authentication
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.runtime import get_google_oauth_service
from backend.app.security.identity import get_optional_authenticated_user_id
from backend.app.security.models import (
    ConfirmationState,
    PermissionDecision,
    PermissionId,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.demo import EchoTool
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.registry import ToolRegistry
from backend.app.workflows.engine import WorkflowEngine
from backend.app.workflows.models import (
    StepStatus,
    WorkflowDefinition,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowStepDefinition,
)
from backend.app.workflows.repository import InMemoryWorkflowRepository
from backend.app.workflows.runtime import get_workflow_service
from backend.app.workflows.service import WorkflowService
from backend.app.workflows.tools import (
    DataExtractionTool,
    HighRiskActionTool,
    VerifyTool,
)
from backend.app.workflows.validator import WorkflowValidator

USER_A = UUID("ef3e7347-a8e9-4d63-90cf-a21d5c855515")
USER_B = UUID("43ad3973-5d96-4608-8b7b-3e774106429a")


def create_test_workflow_service() -> tuple[WorkflowService, InMemoryWorkflowRepository]:
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(VerifyTool())
    registry.register(DataExtractionTool())
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
        ("planner.extract", PermissionId.TEST_RECORD): PermissionRule(
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
    tool_executor = ToolExecutionService(registry, permission_engine)
    repository = InMemoryWorkflowRepository()
    validator = WorkflowValidator(registry)
    engine = WorkflowEngine(repository, tool_executor, permission_engine)
    service = WorkflowService(repository, validator, engine)
    return service, repository


class FakeGoogleOAuthService:
    def __init__(self, connected: bool = True) -> None:
        self._connected = connected

    def connection_status(self, user_id: str) -> tuple[bool, bool]:
        return True, self._connected


class FakeGitHubAppAuthentication:
    def __init__(self, configured: bool = True) -> None:
        self.configured = configured


def create_test_app(
    workflow_service: WorkflowService,
    conversation_service: ConversationService | None = None,
    google_oauth: Any = None,
    github_auth: Any = None,
    user_id: UUID | None = USER_A,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(workflows_router, prefix="/api/v1")

    conv_svc = conversation_service or ConversationService(InMemoryConversationRepository())
    g_oauth = google_oauth or FakeGoogleOAuthService()
    gh_auth = github_auth or FakeGitHubAppAuthentication()

    app.dependency_overrides[get_workflow_service] = lambda: workflow_service
    app.dependency_overrides[get_conversation_service] = lambda: conv_svc
    app.dependency_overrides[get_google_oauth_service] = lambda: g_oauth
    app.dependency_overrides[get_github_authentication] = lambda: gh_auth
    app.dependency_overrides[get_optional_authenticated_user_id] = lambda: user_id
    return app


async def api_request(
    app: FastAPI,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    encoded_body = json.dumps(body).encode() if body is not None else b""
    parsed = urlsplit(path)
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"),
        "query_string": parsed.query.encode("ascii"),
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("testserver", 50000),
        "server": ("testserver", 80),
    }
    messages: list[Message] = []
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": encoded_body, "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    await app(scope, receive, send)
    status_code = next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status_code, json.loads(response_body.decode()) if response_body else {}


class DashboardAndActivityApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.wf_service, self.wf_repository = create_test_workflow_service()
        self.conv_repository = InMemoryConversationRepository()
        self.conv_service = ConversationService(self.conv_repository)
        self.app = create_test_app(
            self.wf_service,
            self.conv_service,
            user_id=USER_A,
        )

    async def test_unauthenticated_dashboard_request_is_rejected(self) -> None:
        unauth_app = create_test_app(self.wf_service, self.conv_service, user_id=None)
        status, body = await api_request(unauth_app, "GET", "/api/v1/dashboard")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "authentication_required")

    async def test_unauthenticated_events_request_is_rejected(self) -> None:
        unauth_app = create_test_app(self.wf_service, self.conv_service, user_id=None)
        status, body = await api_request(unauth_app, "GET", "/api/v1/workflows/events")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "authentication_required")

    async def test_dashboard_metrics_and_real_event_feed(self) -> None:
        # Create a completed workflow
        wf1_def = WorkflowDefinition(
            title="Extraction and verification task",
            user_request="Extract and verify",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Extract",
                    tool_name="planner.extract",
                    arguments={"text": "Data", "field_name": "k"},
                ),
                WorkflowStepDefinition(
                    step_id="step-2",
                    title="Verify",
                    tool_name="system.verify",
                    arguments={"item": "k", "expected_value": "Data", "actual_value": "Data"},
                    dependencies=["step-1"],
                ),
            ],
        )
        wf1 = self.wf_service.create_workflow(str(USER_A), wf1_def)
        self.wf_service.start_workflow(str(USER_A), wf1.id)

        # Create a pending approval workflow (high-risk step)
        wf2_def = WorkflowDefinition(
            title="High-risk sensitive workflow",
            user_request="Needs authorization",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-high",
                    title="High-risk action",
                    tool_name="test.action.high_risk",
                    arguments={"action_name": "delete_staging"},
                ),
            ],
        )
        wf2 = self.wf_service.create_workflow(str(USER_A), wf2_def)
        self.wf_service.start_workflow(str(USER_A), wf2.id)

        # Create a conversation
        self.conv_service.create(str(USER_A), "Research discussion session")

        # Query dashboard endpoint
        status, dashboard = await api_request(self.app, "GET", "/api/v1/dashboard")
        self.assertEqual(status, 200)

        # Check workflow counts
        counts = dashboard["workflow_counts"]
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["completed"], 1)
        self.assertEqual(counts["waiting_for_confirmation"], 1)
        self.assertEqual(counts["running"], 0)

        # Check pending approvals
        pending = dashboard["pending_approvals"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], wf2.id)
        self.assertEqual(pending[0]["title"], "High-risk sensitive workflow")

        # Check recent conversations
        convs = dashboard["recent_conversations"]
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["title"], "Research discussion session")

        # Check connected services (Google & GitHub actions disabled)
        services = dashboard["connected_services"]
        self.assertEqual(len(services), 2)
        for svc in services:
            self.assertFalse(svc["actions_enabled"])

        # Check recent activity feed
        activity = dashboard["recent_activity"]
        self.assertGreaterEqual(len(activity), 2)
        event_types = [ev["event_type"] for ev in activity]
        self.assertIn("confirmation_required", event_types)
        self.assertIn("workflow_completed", event_types)

        # Verify event records include workflow_title
        first_event = activity[0]
        self.assertIsNotNone(first_event.get("workflow_title"))

    async def test_paginated_user_events_api(self) -> None:
        # Create a workflow to generate events
        wf_def = WorkflowDefinition(
            title="Batch event generator",
            user_request="Emit events",
            steps=[
                WorkflowStepDefinition(
                    step_id="s1",
                    title="Echo",
                    tool_name="system.echo",
                    arguments={"message": "Event 1"},
                ),
            ],
        )
        wf = self.wf_service.create_workflow(str(USER_A), wf_def)
        self.wf_service.start_workflow(str(USER_A), wf.id)

        # Request with limit=2
        status, res = await api_request(self.app, "GET", "/api/v1/workflows/events?limit=2&offset=0")
        self.assertEqual(status, 200)
        self.assertLessEqual(len(res["items"]), 2)
        self.assertGreaterEqual(res["total"], 2)

        # Verify timestamps are descending (newest first)
        timestamps = [ev["created_at"] for ev in res["items"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    async def test_cross_user_dashboard_and_activity_isolation(self) -> None:
        # User A creates a workflow
        wf_def = WorkflowDefinition(
            title="User A private task",
            user_request="User A only",
            steps=[
                WorkflowStepDefinition(
                    step_id="s1",
                    title="Echo",
                    tool_name="system.echo",
                    arguments={"message": "private"},
                ),
            ],
        )
        wf = self.wf_service.create_workflow(str(USER_A), wf_def)
        self.wf_service.start_workflow(str(USER_A), wf.id)

        # User B queries dashboard
        user_b_app = create_test_app(self.wf_service, self.conv_service, user_id=USER_B)
        status, dashboard_b = await api_request(user_b_app, "GET", "/api/v1/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(dashboard_b["workflow_counts"]["total"], 0)
        self.assertEqual(dashboard_b["running_workflows"], [])
        self.assertEqual(dashboard_b["pending_approvals"], [])
        self.assertEqual(dashboard_b["recent_activity"], [])

        # User B queries activity events
        status, events_b = await api_request(user_b_app, "GET", "/api/v1/workflows/events")
        self.assertEqual(status, 200)
        self.assertEqual(events_b["total"], 0)
        self.assertEqual(events_b["items"], [])

    async def test_dashboard_gracefully_handles_unavailable_conversations_store(self) -> None:
        # Mock a conversation service that throws store unavailable
        class FailingConvService:
            def list(self, *args: Any, **kwargs: Any) -> Any:
                raise ConversationStoreUnavailable("PostgreSQL connection down")

        app = create_test_app(
            self.wf_service,
            conversation_service=FailingConvService(),  # type: ignore[arg-type]
            user_id=USER_A,
        )
        status, dashboard = await api_request(app, "GET", "/api/v1/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(dashboard["recent_conversations"], [])

    def test_workflow_counts_aggregation(self) -> None:
        # Verify count_by_status returns correct counts
        counts = self.wf_service.get_workflow_counts(str(USER_A))
        self.assertEqual(counts["total"], 0)
        self.assertEqual(counts["draft"], 0)

        # Create workflows for USER_A
        wf_def = WorkflowDefinition(
            title="Draft Task",
            user_request="test",
            steps=[
                WorkflowStepDefinition(
                    step_id="s1",
                    title="Echo",
                    tool_name="system.echo",
                    arguments={"message": "hello"},
                )
            ],
        )
        wf1 = self.wf_service.create_workflow(str(USER_A), wf_def)
        self.wf_service.start_workflow(str(USER_A), wf1.id)

        wf2 = self.wf_service.create_workflow(str(USER_A), wf_def)

        counts_a = self.wf_service.get_workflow_counts(str(USER_A))
        self.assertEqual(counts_a["total"], 2)
        self.assertEqual(counts_a["completed"], 1)
        self.assertEqual(counts_a["draft"], 1)

        # USER_B has 0
        counts_b = self.wf_service.get_workflow_counts(str(USER_B))
        self.assertEqual(counts_b["total"], 0)


if __name__ == "__main__":
    unittest.main()

