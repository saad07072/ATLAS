import unittest
from unittest.mock import Mock

from pydantic import BaseModel, ConfigDict, Field

from backend.app.agent.agent import ChatAgent, ChatAgentError
from backend.app.security.models import (
    AuthorizationResult,
    PermissionContext,
    PermissionDecision,
    PermissionId,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.base import Tool
from backend.app.tools.demo import EchoInput, EchoTool
from backend.app.tools.errors import (
    DuplicateToolError,
    InvalidToolArgumentsError,
    UnknownToolError,
)
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.models import ToolExecutionRequest
from backend.app.tools.registry import ToolRegistry


class RecordingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str = Field(min_length=1)


class RecordingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


class RecordingTool(Tool):
    name = "test.recording"
    description = "Records boundary ordering."
    input_schema = RecordingInput
    output_schema = RecordingOutput
    permission_required = False
    permission_id = PermissionId.TEST_RECORD.value

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def execute(self, arguments: BaseModel) -> BaseModel:
        self.events.append("execute")
        return RecordingOutput(value=arguments.value)


class FailingTool(RecordingTool):
    name = "test.failing"

    def execute(self, _arguments: BaseModel) -> BaseModel:
        raise RuntimeError("internal secret must not be returned")


class InvalidResultTool(RecordingTool):
    name = "test.invalid-result"

    def execute(self, _arguments: BaseModel) -> BaseModel:
        return object()


def create_test_service(registry: ToolRegistry) -> ToolExecutionService:
    return ToolExecutionService(
        registry,
        PermissionEngine(
            PermissionPolicy(
                {
                    ("system.echo", PermissionId.SYSTEM_ECHO): PermissionRule(
                        allowed=True,
                        risk_level=RiskLevel.LOW,
                        permission_required=False,
                    ),
                    ("test.recording", PermissionId.TEST_RECORD): PermissionRule(
                        allowed=True,
                        risk_level=RiskLevel.LOW,
                        permission_required=False,
                    ),
                    ("test.failing", PermissionId.TEST_RECORD): PermissionRule(
                        allowed=True,
                        risk_level=RiskLevel.LOW,
                        permission_required=False,
                    ),
                    ("test.invalid-result", PermissionId.TEST_RECORD): PermissionRule(
                        allowed=True,
                        risk_level=RiskLevel.LOW,
                        permission_required=False,
                    ),
                }
            )
        ),
    )


class ToolFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.echo = EchoTool()
        self.registry.register(self.echo)

    def test_register_and_reject_duplicate_names(self) -> None:
        with self.assertRaises(DuplicateToolError):
            self.registry.register(EchoTool())

    def test_lookup_returns_registered_tool(self) -> None:
        self.assertIs(self.registry.get("system.echo"), self.echo)

    def test_unknown_tool_is_rejected_without_echoing_name(self) -> None:
        with self.assertRaises(UnknownToolError) as error:
            self.registry.get("secret.tool")

        self.assertEqual(str(error.exception), "")

    def test_listing_exposes_tool_metadata_and_schema(self) -> None:
        tools = self.registry.list_tools()

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "system.echo")
        self.assertIn("message", tools[0].input_schema["properties"])
        self.assertFalse(tools[0].permission_required)
        self.assertEqual(tools[0].risk_level, "low")

    def test_input_schema_validates_successfully(self) -> None:
        arguments = self.echo.validate_input({"message": "hello"})

        self.assertEqual(arguments, EchoInput(message="hello"))

    def test_invalid_missing_and_unexpected_arguments_are_rejected(self) -> None:
        invalid_arguments = ({}, {"message": "hello", "extra": "no"})

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(InvalidToolArgumentsError):
                    self.echo.validate_input(arguments)

    def test_demo_executes_and_validates_structured_result(self) -> None:
        service = create_test_service(self.registry)

        result = service.execute(
            ToolExecutionRequest(
                name="system.echo",
                arguments={"message": "hello"},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output, {"message": "hello"})
        self.assertIsNone(result.error)
        self.assertGreaterEqual(result.metadata.duration_ms, 0)

    def test_unknown_tool_request_returns_safe_failure(self) -> None:
        service = create_test_service(self.registry)

        result = service.execute(
            ToolExecutionRequest(name="private.internal", arguments={})
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "unknown_tool")
        self.assertNotIn("private.internal", result.error.message)

    def test_permission_boundary_runs_before_execution(self) -> None:
        events: list[str] = []

        class RecordingPolicy(PermissionPolicy):
            def evaluate(
                self,
                context: PermissionContext | None,
            ) -> AuthorizationResult:
                events.append("authorize")
                return super().evaluate(context)

        registry = ToolRegistry()
        registry.register(RecordingTool(events))
        service = ToolExecutionService(
            registry,
            PermissionEngine(
                RecordingPolicy(
                    {
                        ("test.recording", PermissionId.TEST_RECORD): PermissionRule(
                            allowed=True,
                            risk_level=RiskLevel.LOW,
                            permission_required=False,
                        )
                    }
                )
            ),
        )
        result = service.execute(
            ToolExecutionRequest(
                name="test.recording",
                arguments={"value": "safe"},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(events, ["authorize", "execute"])

    def test_default_boundary_denies_tools_requiring_permission(self) -> None:
        events: list[str] = []
        tool = RecordingTool(events)
        tool.permission_required = True
        registry = ToolRegistry()
        registry.register(tool)
        service = create_test_service(registry)

        result = service.execute(
            ToolExecutionRequest(
                name="test.recording",
                arguments={"value": "safe"},
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "permission_denied")
        self.assertEqual(events, [])

    def test_tool_execution_failure_is_normalized_without_secret(self) -> None:
        registry = ToolRegistry()
        registry.register(FailingTool([]))
        service = create_test_service(registry)

        result = service.execute(
            ToolExecutionRequest(
                name="test.failing",
                arguments={"value": "safe"},
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "execution_failed")
        self.assertNotIn("secret", result.model_dump_json())

    def test_invalid_tool_result_is_reported_safely(self) -> None:
        registry = ToolRegistry()
        registry.register(InvalidResultTool([]))
        service = create_test_service(registry)

        result = service.execute(
            ToolExecutionRequest(
                name="test.invalid-result",
                arguments={"value": "safe"},
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "invalid_result")

    def test_arbitrary_code_string_is_only_echoed_as_data(self) -> None:
        service = create_test_service(self.registry)
        code = "__import__('os').system('whoami')"

        result = service.execute(
            ToolExecutionRequest(
                name="system.echo",
                arguments={"message": code},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output, {"message": code})

    def test_agent_delegates_explicit_tool_requests_to_executor(self) -> None:
        provider = Mock()
        registry = ToolRegistry()
        registry.register(self.echo)
        service = create_test_service(registry)
        agent = ChatAgent(provider, tool_executor=service)

        result = agent.execute_tool_request(
            ToolExecutionRequest(
                name="system.echo",
                arguments={"message": "hello"},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output, {"message": "hello"})
        provider.generate.assert_not_called()
        provider.call_tools.assert_not_called()

    def test_agent_without_tool_service_cannot_execute(self) -> None:
        agent = ChatAgent(Mock())

        with self.assertRaises(ChatAgentError):
            agent.execute_tool_request(
                ToolExecutionRequest(name="system.echo", arguments={})
            )


if __name__ == "__main__":
    unittest.main()
