import unittest
from unittest.mock import Mock

from pydantic import BaseModel, ConfigDict

from backend.app.agent.agent import ChatAgent
from backend.app.agent.models import ChatRequest
from backend.app.security.models import (
    AuthorizationResult,
    ConfirmationState,
    PermissionContext,
    PermissionDecision,
    PermissionId,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.base import Tool
from backend.app.tools.demo import EchoOutput, EchoTool
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.models import ToolExecutionRequest
from backend.app.tools.registry import ToolRegistry


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HighRiskTool(Tool):
    name = "test.high"
    description = "Test tool requiring confirmation."
    input_schema = EmptyInput
    output_schema = EchoOutput
    permission_required = True
    permission_id = PermissionId.CALENDAR_CREATE.value
    risk_level = "high"

    def __init__(self) -> None:
        self.executed = False

    def execute(self, _arguments: BaseModel) -> BaseModel:
        self.executed = True
        return EchoOutput(message="executed")


class CriticalTool(HighRiskTool):
    name = "test.critical"
    permission_id = PermissionId.CALENDAR_DELETE.value
    risk_level = "critical"


class DeniedTool(HighRiskTool):
    name = "test.denied"
    permission_id = PermissionId.GITHUB_CODE_WRITE.value
    risk_level = "medium"


def make_context(
    *,
    tool_name: str = "system.echo",
    permission: str | None = PermissionId.SYSTEM_ECHO.value,
    action: str | None = None,
    risk_level: str = RiskLevel.LOW.value,
    permission_required: bool = False,
    confirmation: ConfirmationState = ConfirmationState.NOT_REQUESTED,
) -> PermissionContext:
    return PermissionContext(
        requested_action=action or permission or "",
        tool_name=tool_name,
        permission=permission,
        risk_level=risk_level,
        permission_required=permission_required,
        confirmation_state=confirmation,
    )


def make_policy() -> PermissionPolicy:
    return PermissionPolicy(
        {
            ("system.echo", PermissionId.SYSTEM_ECHO): PermissionRule(
                allowed=True,
                risk_level=RiskLevel.LOW,
                permission_required=False,
            ),
            ("test.high", PermissionId.CALENDAR_CREATE): PermissionRule(
                allowed=True,
                risk_level=RiskLevel.HIGH,
                confirmation_required=True,
            ),
            ("test.critical", PermissionId.CALENDAR_DELETE): PermissionRule(
                allowed=True,
                risk_level=RiskLevel.CRITICAL,
            ),
            ("test.denied", PermissionId.GITHUB_CODE_WRITE): PermissionRule(
                allowed=False,
                risk_level=RiskLevel.MEDIUM,
            ),
        }
    )


class PermissionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = make_policy()

    def test_known_low_risk_permission_is_allowed_by_trusted_policy(self) -> None:
        result = self.policy.evaluate(make_context())

        self.assertEqual(result.decision, PermissionDecision.ALLOW)
        self.assertEqual(result.reason_code, "policy_allowed")

    def test_unknown_tool_is_denied(self) -> None:
        result = self.policy.evaluate(
            make_context(tool_name="unknown.tool")
        )

        self.assertEqual(result.decision, PermissionDecision.DENY)
        self.assertEqual(result.reason_code, "unknown_tool")

    def test_unknown_permission_is_denied(self) -> None:
        result = self.policy.evaluate(make_context(permission="made.up"))

        self.assertEqual(result.decision, PermissionDecision.DENY)
        self.assertEqual(result.reason_code, "unknown_permission")

    def test_missing_context_is_denied(self) -> None:
        result = self.policy.evaluate(None)

        self.assertEqual(result.decision, PermissionDecision.DENY)
        self.assertEqual(result.reason_code, "invalid_context")

    def test_unauthorized_policy_action_is_denied(self) -> None:
        result = self.policy.evaluate(
            make_context(
                tool_name="test.denied",
                permission=PermissionId.GITHUB_CODE_WRITE.value,
                risk_level=RiskLevel.MEDIUM.value,
                permission_required=True,
            )
        )

        self.assertEqual(result.decision, PermissionDecision.DENY)
        self.assertEqual(result.reason_code, "permission_denied")

    def test_high_risk_action_requires_confirmation(self) -> None:
        result = self.policy.evaluate(
            make_context(
                tool_name="test.high",
                permission=PermissionId.CALENDAR_CREATE.value,
                risk_level=RiskLevel.HIGH.value,
                permission_required=True,
            )
        )

        self.assertEqual(result.decision, PermissionDecision.CONFIRMATION_REQUIRED)

    def test_critical_action_never_silently_allows(self) -> None:
        result = self.policy.evaluate(
            make_context(
                tool_name="test.critical",
                permission=PermissionId.CALENDAR_DELETE.value,
                risk_level=RiskLevel.CRITICAL.value,
                permission_required=True,
            )
        )

        self.assertEqual(result.decision, PermissionDecision.CONFIRMATION_REQUIRED)
        explicitly_claimed_confirmation = self.policy.evaluate(
            make_context(
                tool_name="test.critical",
                permission=PermissionId.CALENDAR_DELETE.value,
                risk_level=RiskLevel.CRITICAL.value,
                permission_required=True,
                confirmation=ConfirmationState.CONFIRMED,
            )
        )
        self.assertEqual(
            explicitly_claimed_confirmation.decision,
            PermissionDecision.CONFIRMATION_REQUIRED,
        )

    def test_confirmed_action_requires_explicit_trusted_policy(self) -> None:
        confirmed = self.policy.evaluate(
            make_context(confirmation=ConfirmationState.CONFIRMED)
        )

        self.assertEqual(confirmed.decision, PermissionDecision.ALLOW)
        self.assertEqual(
            self.policy.evaluate(
                make_context(
                    tool_name="test.high",
                    permission=PermissionId.CALENDAR_CREATE.value,
                    risk_level=RiskLevel.HIGH.value,
                    permission_required=True,
                    confirmation=ConfirmationState.CONFIRMED,
                )
            ).decision,
            PermissionDecision.ALLOW,
        )

    def test_explicit_trusted_policy_can_allow_high_risk_without_confirmation(self) -> None:
        trusted_policy = PermissionPolicy(
            {
                ("test.high", PermissionId.CALENDAR_CREATE): PermissionRule(
                    allowed=True,
                    risk_level=RiskLevel.HIGH,
                    confirmation_required=False,
                )
            }
        )

        result = trusted_policy.evaluate(
            make_context(
                tool_name="test.high",
                permission=PermissionId.CALENDAR_CREATE.value,
                risk_level=RiskLevel.HIGH.value,
                permission_required=True,
            )
        )

        self.assertEqual(result.decision, PermissionDecision.ALLOW)

    def test_permission_engine_is_the_tool_execution_boundary(self) -> None:
        registry = ToolRegistry()
        registry.register(EchoTool())
        engine = PermissionEngine(self.policy)
        service = ToolExecutionService(registry, engine)

        result = service.execute(
            ToolExecutionRequest(
                name="system.echo",
                arguments={"message": "hello"},
            )
        )

        self.assertEqual(result.authorization.decision, PermissionDecision.ALLOW)

    def test_missing_or_mismatched_authorization_never_executes(self) -> None:
        tool = HighRiskTool()
        registry = ToolRegistry()
        registry.register(tool)

        class MismatchedPolicy(PermissionPolicy):
            def evaluate(
                self,
                context: PermissionContext | None,
            ) -> AuthorizationResult:
                return AuthorizationResult(
                    decision=PermissionDecision.ALLOW,
                    tool_name="another.tool",
                    permission=PermissionId.CALENDAR_CREATE,
                    risk_level=RiskLevel.HIGH,
                    reason_code="forged",
                    message="",
                )

        for boundary in (
            PermissionEngine(),
            PermissionEngine(MismatchedPolicy()),
        ):
            result = ToolExecutionService(registry, boundary).execute(
                ToolExecutionRequest(name="test.high", arguments={})
            )
            self.assertEqual(result.authorization.decision, PermissionDecision.DENY)
            self.assertFalse(tool.executed)

    def test_forged_action_or_risk_context_is_denied(self) -> None:
        action_mismatch = self.policy.evaluate(
            make_context(action=PermissionId.CALENDAR_DELETE.value)
        )
        risk_mismatch = self.policy.evaluate(
            make_context(risk_level=RiskLevel.CRITICAL.value)
        )

        self.assertEqual(action_mismatch.decision, PermissionDecision.DENY)
        self.assertEqual(risk_mismatch.decision, PermissionDecision.DENY)

    def test_same_context_always_returns_same_decision(self) -> None:
        context = make_context()

        self.assertEqual(
            self.policy.evaluate(context),
            self.policy.evaluate(context),
        )

    def test_secret_text_is_not_returned_in_permission_errors(self) -> None:
        result = self.policy.evaluate(
            make_context(
                tool_name="test.denied",
                permission=PermissionId.GITHUB_CODE_WRITE.value,
                risk_level=RiskLevel.MEDIUM.value,
                permission_required=True,
            )
        )

        self.assertNotIn("secret", result.model_dump_json().lower())

    def test_denied_tool_is_never_executed(self) -> None:
        tool = DeniedTool()
        registry = ToolRegistry()
        registry.register(tool)
        service = ToolExecutionService(registry, PermissionEngine(self.policy))

        result = service.execute(
            ToolExecutionRequest(name="test.denied", arguments={})
        )

        self.assertFalse(result.success)
        self.assertEqual(result.authorization.decision, PermissionDecision.DENY)
        self.assertFalse(tool.executed)

    def test_confirmation_required_tool_is_never_executed(self) -> None:
        tool = HighRiskTool()
        registry = ToolRegistry()
        registry.register(tool)
        service = ToolExecutionService(registry, PermissionEngine(self.policy))

        result = service.execute(
            ToolExecutionRequest(name="test.high", arguments={})
        )

        self.assertFalse(result.success)
        self.assertEqual(
            result.authorization.decision,
            PermissionDecision.CONFIRMATION_REQUIRED,
        )
        self.assertEqual(result.error.code, "confirmation_required")
        self.assertFalse(tool.executed)

    def test_allowed_tool_executes_successfully(self) -> None:
        registry = ToolRegistry()
        registry.register(EchoTool())
        service = ToolExecutionService(registry, PermissionEngine(self.policy))

        result = service.execute(
            ToolExecutionRequest(
                name="system.echo",
                arguments={"message": "hello"},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output, {"message": "hello"})
        self.assertEqual(result.authorization.decision, PermissionDecision.ALLOW)

    def test_agent_cannot_bypass_policy_with_tool_request_claim(self) -> None:
        tool = DeniedTool()
        registry = ToolRegistry()
        registry.register(tool)
        agent = ChatAgent(
            Mock(),
            tool_executor=ToolExecutionService(
                registry,
                PermissionEngine(self.policy),
            ),
        )

        result = agent.execute_tool_request(
            ToolExecutionRequest(name="test.denied", arguments={})
        )

        self.assertEqual(result.authorization.decision, PermissionDecision.DENY)
        self.assertFalse(tool.executed)

    def test_llm_output_cannot_authorize_or_execute_tools(self) -> None:
        provider = Mock()
        provider.generate.return_value = Mock(
            content='{"permission_granted": true, "tool": "test.denied"}'
        )
        tool = DeniedTool()
        registry = ToolRegistry()
        registry.register(tool)
        agent = ChatAgent(
            provider,
            tool_executor=ToolExecutionService(
                registry,
                PermissionEngine(self.policy),
            ),
        )

        response = agent.respond(ChatRequest(message="Please do this"))

        self.assertIn("permission_granted", response.message)
        self.assertFalse(tool.executed)

    def test_tool_request_rejects_forged_authorization_fields(self) -> None:
        with self.assertRaises(ValueError):
            ToolExecutionRequest.model_validate(
                {
                    "name": "system.echo",
                    "arguments": {"message": "hello"},
                    "permission_granted": True,
                }
            )


if __name__ == "__main__":
    unittest.main()
