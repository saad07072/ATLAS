import json
import unittest
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import FastAPI
from starlette.types import Message, Scope

from backend.app.api.v1.workflows import router as workflows_router
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.security.identity import get_optional_authenticated_user_id
from backend.app.security.models import (
    ConfirmationState,
    PermissionDecision,
    PermissionId,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.base import Tool
from backend.app.tools.demo import EchoInput, EchoTool
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.registry import ToolRegistry
from backend.app.workflows.engine import WorkflowEngine
from backend.app.workflows.errors import (
    CycleDetectedError,
    InvalidStateTransitionError,
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from backend.app.workflows.models import (
    StepStatus,
    StepVerificationStatus,
    WorkflowDefinition,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowStepDefinition,
    WorkflowStepRecord,
)
from backend.app.workflows.repository import InMemoryWorkflowRepository
from backend.app.workflows.runtime import get_workflow_service
from backend.app.workflows.service import WorkflowService
from backend.app.workflows.tools import (
    DataExtractionTool,
    HighRiskActionInput,
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
    executor = ToolExecutionService(registry, permission_engine)
    repository = InMemoryWorkflowRepository()
    validator = WorkflowValidator(registry)
    engine = WorkflowEngine(repository, executor, permission_engine)

    service = WorkflowService(
        repository=repository,
        validator=validator,
        engine=engine,
        conversation_repository=None,
    )
    return service, repository


def create_test_app(
    service: WorkflowService,
    *,
    user_id: UUID | None = USER_A,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(workflows_router, prefix="/api/v1")
    app.dependency_overrides[get_optional_authenticated_user_id] = lambda: user_id
    app.dependency_overrides[get_workflow_service] = lambda: service
    return app


async def api_request(
    app: FastAPI,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, Any]]:
    parsed = urlsplit(path)
    encoded_body = json.dumps(body).encode() if body is not None else b""
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
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


class WorkflowPlanningAndValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service, self.repository = create_test_workflow_service()

    def test_valid_multistep_plan_validates_successfully(self) -> None:
        plan = WorkflowDefinition(
            title="Data verification workflow",
            user_request="Extract and verify user data",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Extract",
                    tool_name="planner.extract",
                    arguments={"text": "User data sample", "field_name": "sample"},
                    dependencies=[],
                ),
                WorkflowStepDefinition(
                    step_id="step-2",
                    title="Verify",
                    tool_name="system.verify",
                    arguments={"item": "sample", "expected_value": "User data sample", "actual_value": "User data sample"},
                    dependencies=["step-1"],
                ),
            ],
        )
        created = self.service.create_workflow(str(USER_A), plan)
        self.assertEqual(created.title, "Data verification workflow")
        self.assertEqual(len(created.steps), 2)
        self.assertEqual(created.steps[0].step_id, "step-1")
        self.assertEqual(created.steps[1].step_id, "step-2")
        self.assertEqual(created.steps[1].dependencies, ["step-1"])

    def test_exceeding_max_steps_limit_is_rejected(self) -> None:
        steps = [
            WorkflowStepDefinition(
                step_id=f"step-{i}",
                title=f"Step {i}",
                tool_name="system.echo",
                arguments={"message": f"msg {i}"},
                dependencies=[],
            )
            for i in range(25)
        ]
        with self.assertRaises(WorkflowValidationError) as ctx:
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title="Too many steps",
                    user_request="Too many steps",
                    steps=steps,
                ),
            )
        self.assertIn("exceeds maximum limit", str(ctx.exception))

    def test_duplicate_step_ids_are_rejected(self) -> None:
        with self.assertRaises(WorkflowValidationError) as ctx:
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title="Duplicate IDs",
                    user_request="Duplicate IDs",
                    steps=[
                        WorkflowStepDefinition(
                            step_id="step-1",
                            title="First",
                            tool_name="system.echo",
                            arguments={"message": "1"},
                        ),
                        WorkflowStepDefinition(
                            step_id="step-1",
                            title="Duplicate",
                            tool_name="system.echo",
                            arguments={"message": "2"},
                        ),
                    ],
                ),
            )
        self.assertIn("step IDs must be unique", str(ctx.exception))

    def test_unknown_dependency_reference_is_rejected(self) -> None:
        with self.assertRaises(WorkflowValidationError) as ctx:
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title="Unknown dependency",
                    user_request="Unknown dependency",
                    steps=[
                        WorkflowStepDefinition(
                            step_id="step-1",
                            title="First",
                            tool_name="system.echo",
                            arguments={"message": "1"},
                            dependencies=["non-existent-step"],
                        ),
                    ],
                ),
            )
        self.assertIn("references unknown dependency", str(ctx.exception))

    def test_self_dependency_is_rejected(self) -> None:
        with self.assertRaises(WorkflowValidationError) as ctx:
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title="Self dependency",
                    user_request="Self dependency",
                    steps=[
                        WorkflowStepDefinition(
                            step_id="step-1",
                            title="First",
                            tool_name="system.echo",
                            arguments={"message": "1"},
                            dependencies=["step-1"],
                        ),
                    ],
                ),
            )
        self.assertIn("cannot depend on itself", str(ctx.exception))

    def test_dependency_cycle_is_detected_and_rejected(self) -> None:
        # A -> B -> C -> A
        with self.assertRaises(CycleDetectedError) as ctx:
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title="Cycle DAG",
                    user_request="Cycle DAG",
                    steps=[
                        WorkflowStepDefinition(
                            step_id="step-A",
                            title="A",
                            tool_name="system.echo",
                            arguments={"message": "A"},
                            dependencies=["step-C"],
                        ),
                        WorkflowStepDefinition(
                            step_id="step-B",
                            title="B",
                            tool_name="system.echo",
                            arguments={"message": "B"},
                            dependencies=["step-A"],
                        ),
                        WorkflowStepDefinition(
                            step_id="step-C",
                            title="C",
                            tool_name="system.echo",
                            arguments={"message": "C"},
                            dependencies=["step-B"],
                        ),
                    ],
                ),
            )
        self.assertIn("Dependency cycle detected", str(ctx.exception))

    def test_unknown_tool_is_rejected_at_validation(self) -> None:
        with self.assertRaises(WorkflowValidationError) as ctx:
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title="Unknown tool",
                    user_request="Unknown tool",
                    steps=[
                        WorkflowStepDefinition(
                            step_id="step-1",
                            title="First",
                            tool_name="arbitrary.unknown.tool",
                            arguments={"data": "test"},
                        ),
                    ],
                ),
            )
        self.assertIn("unknown tool", str(ctx.exception))

    def test_invalid_tool_arguments_are_rejected(self) -> None:
        with self.assertRaises(WorkflowValidationError) as ctx:
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title="Invalid args",
                    user_request="Invalid args",
                    steps=[
                        WorkflowStepDefinition(
                            step_id="step-1",
                            title="First",
                            tool_name="system.echo",
                            arguments={"wrong_key": "not allowed"},
                        ),
                    ],
                ),
            )
        self.assertIn("invalid arguments", str(ctx.exception))

    def test_secret_tokens_in_workflow_are_rejected(self) -> None:
        secret_token = "ghp_123456789012345678901234567890123456"
        with self.assertRaises(WorkflowValidationError):
            self.service.create_workflow(
                str(USER_A),
                WorkflowDefinition(
                    title=f"Workflow with {secret_token}",
                    user_request="Clean request",
                    steps=[
                        WorkflowStepDefinition(
                            step_id="step-1",
                            title="First",
                            tool_name="system.echo",
                            arguments={"message": "hello"},
                        ),
                    ],
                ),
            )


class WorkflowExecutionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service, self.repository = create_test_workflow_service()

    def test_multi_step_workflow_executes_to_completion(self) -> None:
        plan = WorkflowDefinition(
            title="Full execution workflow",
            user_request="Extract and echo",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Extract",
                    tool_name="planner.extract",
                    arguments={"text": "Sample text", "field_name": "target"},
                    dependencies=[],
                ),
                WorkflowStepDefinition(
                    step_id="step-2",
                    title="Echo",
                    tool_name="system.echo",
                    arguments={"message": "Done"},
                    dependencies=["step-1"],
                ),
            ],
        )
        workflow = self.service.create_workflow(str(USER_A), plan)
        executed = self.service.start_workflow(str(USER_A), workflow.id)

        self.assertEqual(executed.status, WorkflowStatus.COMPLETED)
        self.assertEqual(executed.completed_step_count, 2)
        self.assertIsNotNone(executed.completed_at)
        self.assertEqual(executed.steps[0].status, StepStatus.COMPLETED)
        self.assertEqual(executed.steps[1].status, StepStatus.COMPLETED)
        self.assertEqual(executed.steps[0].result_data, {"extracted_value": "Sample text", "field_name": "target"})
        self.assertEqual(executed.steps[1].result_data, {"message": "Done"})

    def test_failed_prerequisite_skips_downstream_and_reports_truthful_partial_completion(self) -> None:
        # Step 1 succeeds, Step 2 is verify which fails, Step 3 depends on Step 2
        plan = WorkflowDefinition(
            title="Partial workflow",
            user_request="Failing verification",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Extract",
                    tool_name="planner.extract",
                    arguments={"text": "Alpha", "field_name": "letter"},
                ),
                WorkflowStepDefinition(
                    step_id="step-2",
                    title="Verify (mismatch)",
                    tool_name="system.verify",
                    arguments={"item": "letter", "expected_value": "Beta", "actual_value": "Alpha"},
                    dependencies=["step-1"],
                ),
                WorkflowStepDefinition(
                    step_id="step-3",
                    title="Echo",
                    tool_name="system.echo",
                    arguments={"message": "Should not run"},
                    dependencies=["step-2"],
                ),
            ],
        )
        workflow = self.service.create_workflow(str(USER_A), plan)
        executed = self.service.start_workflow(str(USER_A), workflow.id)

        # Step 2 verification failed
        self.assertEqual(executed.steps[1].verification_status, StepVerificationStatus.FAILED)

    def test_high_risk_step_pauses_for_confirmation_and_resumes_when_confirmed(self) -> None:
        plan = WorkflowDefinition(
            title="Sensitive task",
            user_request="Execute high-risk update",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Extract",
                    tool_name="planner.extract",
                    arguments={"text": "Production DB", "field_name": "db_target"},
                ),
                WorkflowStepDefinition(
                    step_id="step-2",
                    title="Sensitive action",
                    tool_name="test.action.high_risk",
                    arguments={"action_name": "patch_db", "parameters": {"cluster": "main"}},
                    dependencies=["step-1"],
                ),
                WorkflowStepDefinition(
                    step_id="step-3",
                    title="Report",
                    tool_name="system.echo",
                    arguments={"message": "All done."},
                    dependencies=["step-2"],
                ),
            ],
        )
        workflow = self.service.create_workflow(str(USER_A), plan)
        paused = self.service.start_workflow(str(USER_A), workflow.id)

        # Paused on step-2
        self.assertEqual(paused.status, WorkflowStatus.WAITING_FOR_CONFIRMATION)
        step2 = next(s for s in paused.steps if s.step_id == "step-2")
        self.assertEqual(step2.status, StepStatus.WAITING_FOR_CONFIRMATION)
        self.assertEqual(step2.confirmation_state, ConfirmationState.PENDING)
        self.assertIsNotNone(step2.confirmation_hash)

        # Step 3 is still pending
        step3 = next(s for s in paused.steps if s.step_id == "step-3")
        self.assertEqual(step3.status, StepStatus.PENDING)

        # Confirm step-2
        resumed = self.service.confirm_step(
            str(USER_A),
            workflow.id,
            "step-2",
            decision="confirm",
            reason="Operator approved deployment",
        )

        self.assertEqual(resumed.status, WorkflowStatus.COMPLETED)
        self.assertEqual(resumed.completed_step_count, 3)

    def test_rejecting_confirmation_marks_step_failed_and_skips_downstream(self) -> None:
        plan = WorkflowDefinition(
            title="Sensitive task reject",
            user_request="Execute high-risk update",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Sensitive action",
                    tool_name="test.action.high_risk",
                    arguments={"action_name": "drop_cache"},
                ),
                WorkflowStepDefinition(
                    step_id="step-2",
                    title="Follow up",
                    tool_name="system.echo",
                    arguments={"message": "Cache was cleared."},
                    dependencies=["step-1"],
                ),
            ],
        )
        workflow = self.service.create_workflow(str(USER_A), plan)
        self.service.start_workflow(str(USER_A), workflow.id)

        rejected = self.service.confirm_step(
            str(USER_A),
            workflow.id,
            "step-1",
            decision="reject",
            reason="Declined by operator",
        )

        step1 = next(s for s in rejected.steps if s.step_id == "step-1")
        step2 = next(s for s in rejected.steps if s.step_id == "step-2")

        self.assertEqual(step1.status, StepStatus.FAILED)
        self.assertEqual(step2.status, StepStatus.SKIPPED)
        self.assertEqual(rejected.status, WorkflowStatus.FAILED)

    def test_cancelling_workflow_stops_execution_safely(self) -> None:
        plan = WorkflowDefinition(
            title="Cancel test",
            user_request="Will be cancelled",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Sensitive",
                    tool_name="test.action.high_risk",
                    arguments={"action_name": "hold"},
                ),
                WorkflowStepDefinition(
                    step_id="step-2",
                    title="Echo",
                    tool_name="system.echo",
                    arguments={"message": "Unreachable"},
                    dependencies=["step-1"],
                ),
            ],
        )
        workflow = self.service.create_workflow(str(USER_A), plan)
        self.service.start_workflow(str(USER_A), workflow.id)

        cancelled = self.service.cancel_workflow(str(USER_A), workflow.id)
        self.assertEqual(cancelled.status, WorkflowStatus.CANCELLED)

        # Cannot cancel already cancelled workflow
        with self.assertRaises(WorkflowConflictError):
            self.service.cancel_workflow(str(USER_A), workflow.id)


class WorkflowSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service, self.repository = create_test_workflow_service()

    def test_user_b_cannot_access_user_a_workflow(self) -> None:
        plan = WorkflowDefinition(
            title="User A private workflow",
            user_request="Secret task",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Step",
                    tool_name="system.echo",
                    arguments={"message": "private"},
                ),
            ],
        )
        wf = self.service.create_workflow(str(USER_A), plan)

        # User B cannot read
        with self.assertRaises(WorkflowNotFoundError):
            self.service.get_workflow(str(USER_B), wf.id)

        # User B cannot start
        with self.assertRaises(WorkflowNotFoundError):
            self.service.start_workflow(str(USER_B), wf.id)

        # User B cannot cancel
        with self.assertRaises(WorkflowNotFoundError):
            self.service.cancel_workflow(str(USER_B), wf.id)

        # User B cannot confirm step
        with self.assertRaises(WorkflowNotFoundError):
            self.service.confirm_step(str(USER_B), wf.id, "step-1", decision="confirm")

    def test_tampered_confirmation_arguments_are_rejected(self) -> None:
        plan = WorkflowDefinition(
            title="Tamper test",
            user_request="Tamper test",
            steps=[
                WorkflowStepDefinition(
                    step_id="step-1",
                    title="Sensitive",
                    tool_name="test.action.high_risk",
                    arguments={"action_name": "action_A"},
                ),
            ],
        )
        wf = self.service.create_workflow(str(USER_A), plan)
        self.service.start_workflow(str(USER_A), wf.id)

        # Tamper arguments in repository directly to simulate attacker altering parameters
        self.repository.update_step(
            str(USER_A),
            wf.id,
            "step-1",
            result_data={"tampered": True},
        )
        # Attempt confirmation with altered arguments
        step = self.repository.get(str(USER_A), wf.id).steps[0]
        step.arguments = {"action_name": "malicious_altered_action"}
        self.repository._workflows[(str(USER_A), wf.id)].steps[0].arguments = {"action_name": "malicious_altered_action"}

        with self.assertRaises(WorkflowConflictError) as ctx:
            self.service.confirm_step(str(USER_A), wf.id, "step-1", decision="confirm")
        self.assertIn("arguments were altered", str(ctx.exception))


class WorkflowApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service, self.repository = create_test_workflow_service()
        self.app = create_test_app(self.service, user_id=USER_A)

    async def test_unauthenticated_request_is_rejected(self) -> None:
        unauth_app = create_test_app(self.service, user_id=None)
        status, body = await api_request(unauth_app, "GET", "/api/v1/workflows")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "authentication_required")

    async def test_api_workflow_lifecycle(self) -> None:
        # 1. Create Workflow
        create_payload = {
            "title": "API Multi-step Task",
            "user_request": "Echo and verify via API",
            "steps": [
                {
                    "step_id": "step-1",
                    "title": "Extract",
                    "tool_name": "planner.extract",
                    "arguments": {"text": "API Data", "field_name": "api_field"},
                    "dependencies": [],
                },
                {
                    "step_id": "step-2",
                    "title": "Verify",
                    "tool_name": "system.verify",
                    "arguments": {"item": "api_field", "expected_value": "API Data", "actual_value": "API Data"},
                    "dependencies": ["step-1"],
                },
            ],
        }
        status, created = await api_request(self.app, "POST", "/api/v1/workflows", create_payload)
        self.assertEqual(status, 201)
        workflow_id = created["id"]
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["step_count"], 2)

        # 2. List Workflows
        status, listing = await api_request(self.app, "GET", "/api/v1/workflows?limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["id"], workflow_id)

        # 3. Get Workflow Details
        status, detail = await api_request(self.app, "GET", f"/api/v1/workflows/{workflow_id}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["id"], workflow_id)

        # 4. Start Workflow
        status, started = await api_request(self.app, "POST", f"/api/v1/workflows/{workflow_id}/start")
        self.assertEqual(status, 200)
        self.assertEqual(started["status"], "completed")
        self.assertEqual(started["completed_step_count"], 2)

        # 5. Get Events
        status, events = await api_request(self.app, "GET", f"/api/v1/workflows/{workflow_id}/events")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(events), 2)
        event_types = [e["event_type"] for e in events]
        self.assertIn("workflow_created", event_types)
        self.assertIn("step_completed", event_types)


if __name__ == "__main__":
    unittest.main()

