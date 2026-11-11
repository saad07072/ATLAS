from __future__ import annotations

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

    def test_app_close_tool_execution(self) -> None:
        from backend.app.tools.system_tools import AppCloseTool, AppCloseInput
        tool = AppCloseTool()
        with unittest.mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)
            result = tool.execute(AppCloseInput(target="notepad"))
            self.assertEqual(result.target, "notepad")
            self.assertEqual(result.status, "closed")
            self.assertTrue(result.verified)

    def test_app_close_tool_tab_execution(self) -> None:
        from backend.app.tools.system_tools import AppCloseTool, AppCloseInput
        tool = AppCloseTool()
        with unittest.mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)
            result = tool.execute(AppCloseInput(target="youtube"))
            self.assertEqual(result.target, "youtube")
            self.assertEqual(result.status, "closed")
            self.assertTrue(result.verified)

    def test_web_open_tool_normalizes_amazon_domain(self) -> None:
        from backend.app.tools.system_tools import WebOpenTool, WebOpenInput
        tool = WebOpenTool()
        with unittest.mock.patch("subprocess.Popen") as mock_popen:
            res1 = tool.execute(WebOpenInput(url="amazon.com"))
            self.assertEqual(res1.url, "https://www.amazon.com")
            self.assertEqual(res1.status, "success")

            res2 = tool.execute(WebOpenInput(url="amazon"))
            self.assertEqual(res2.url, "https://www.amazon.com")
            self.assertEqual(res2.status, "success")

    def test_app_launch_tool_windows_app(self) -> None:
        from backend.app.tools.system_tools import AppLaunchTool, AppLaunchInput
        tool = AppLaunchTool()
        with unittest.mock.patch("subprocess.Popen") as mock_popen:
            res = tool.execute(AppLaunchInput(app_name="vlc"))
            self.assertEqual(res.status, "launched")
            self.assertIn("vlc", res.message)

    def test_live_search_tool_execution(self) -> None:
        from backend.app.tools.system_tools import LiveSearchTool, LiveSearchInput
        tool = LiveSearchTool()
        with unittest.mock.patch("urllib.request.urlopen") as mock_url:
            mock_resp = Mock()
            mock_resp.read.return_value = b"""<rss><channel>
                <item><title>IND vs NZ 1st ODI Live: India wins by 4 wickets - News</title></item>
            </channel></rss>"""
            mock_resp.__enter__ = Mock(return_value=mock_resp)
            mock_resp.__exit__ = Mock(return_value=None)
            mock_url.return_value = mock_resp

            res = tool.execute(LiveSearchInput(query="India versus New Zealand"))
            self.assertEqual(res.status, "success")
            self.assertTrue(res.verified)
            self.assertIn("IND vs NZ", res.summary)

    def test_all_system_tools_registered(self) -> None:
        from backend.app.tools.system_tools import get_all_system_tools
        tools = get_all_system_tools()
        names = {t.name for t in tools}
        self.assertIn("web.open", names)
        self.assertIn("system.close_app", names)
        self.assertIn("weather.get", names)
        self.assertIn("system.open_app", names)
        self.assertIn("system.datetime", names)
        self.assertIn("web.search", names)
        self.assertIn("system.list_windows", names)
        self.assertIn("system.focus_window", names)
        self.assertIn("system.send_keys", names)
        self.assertIn("system.window_state", names)

    def test_list_windows_tool_execution(self) -> None:
        from backend.app.tools.system_tools import ListWindowsTool, ListWindowsInput
        tool = ListWindowsTool()
        res = tool.execute(ListWindowsInput(filter=""))
        self.assertEqual(res.verified, True)
        self.assertGreaterEqual(res.count, 1)
        self.assertIn("desktop", res.summary.lower())

    def test_focus_window_tool_execution(self) -> None:
        from backend.app.tools.system_tools import FocusWindowTool, FocusWindowInput
        tool = FocusWindowTool()
        res = tool.execute(FocusWindowInput(target="notepad"))
        self.assertEqual(res.status, "focused")
        self.assertEqual(res.verified, True)
        self.assertIn("notepad", res.message)

    def test_send_keys_tool_execution(self) -> None:
        from backend.app.tools.system_tools import SendKeysTool, SendKeysInput
        tool = SendKeysTool()
        res = tool.execute(SendKeysInput(text="echo hello", target_window="terminal", press_enter=True))
        self.assertEqual(res.status, "sent")
        self.assertEqual(res.verified, True)
        self.assertIn("echo hello", res.message)

    def test_window_state_tool_execution(self) -> None:
        from backend.app.tools.system_tools import WindowStateTool, WindowStateInput
        tool = WindowStateTool()
        res = tool.execute(WindowStateInput(action="minimize_all"))
        self.assertEqual(res.status, "success")
        self.assertEqual(res.verified, True)
        self.assertIn("minimized", res.message.lower())

    def test_media_control_tool_execution(self) -> None:
        from backend.app.tools.system_tools import MediaControlTool, MediaControlInput
        tool = MediaControlTool()
        res = tool.execute(MediaControlInput(action="play_pause"))
        self.assertEqual(res.status, "success")
        self.assertTrue(res.verified)

    def test_volume_control_tool_execution(self) -> None:
        from backend.app.tools.system_tools import VolumeControlTool, VolumeControlInput
        tool = VolumeControlTool()
        res = tool.execute(VolumeControlInput(action="up"))
        self.assertEqual(res.status, "success")
        self.assertTrue(res.verified)

    def test_system_vitals_tool_execution(self) -> None:
        from backend.app.tools.system_tools import SystemVitalsTool, SystemVitalsInput
        tool = SystemVitalsTool()
        res = tool.execute(SystemVitalsInput(detail_level="summary"))
        self.assertEqual(res.status, "success")
        self.assertTrue(res.verified)
        self.assertGreater(res.memory_total_gb, 0)
        self.assertIn("diagnostics", res.summary.lower())

    def test_lock_workstation_tool_execution(self) -> None:
        import sys
        import ctypes
        from backend.app.tools.system_tools import LockWorkstationTool, LockWorkstationInput
        tool = LockWorkstationTool()
        if sys.platform == "win32" and hasattr(ctypes, "windll"):
            with unittest.mock.patch("ctypes.windll.user32.LockWorkStation"):
                res = tool.execute(LockWorkstationInput())
                self.assertEqual(res.status, "success")
                self.assertTrue(res.verified)
        else:
            res = tool.execute(LockWorkstationInput())
            self.assertEqual(res.status, "success")
            self.assertTrue(res.verified)

    def test_protocol_execution_tool_focus_mode(self) -> None:
        from backend.app.tools.system_tools import ProtocolExecutionTool, ProtocolExecutionInput
        tool = ProtocolExecutionTool()
        with unittest.mock.patch("subprocess.Popen"), unittest.mock.patch("subprocess.run"):
            res = tool.execute(ProtocolExecutionInput(protocol="focus_mode"))
            self.assertEqual(res.status, "success")
            self.assertTrue(res.verified)
            self.assertGreaterEqual(len(res.executed_steps), 1)
            self.assertIn("focus mode", res.message.lower())

    def test_protocol_execution_tool_dev_setup(self) -> None:
        from backend.app.tools.system_tools import ProtocolExecutionTool, ProtocolExecutionInput
        tool = ProtocolExecutionTool()
        with unittest.mock.patch("subprocess.Popen"), unittest.mock.patch("subprocess.run"):
            res = tool.execute(ProtocolExecutionInput(protocol="dev_setup"))
            self.assertEqual(res.status, "success")
            self.assertTrue(res.verified)
            self.assertIn("developer setup", res.message.lower())


if __name__ == "__main__":
    unittest.main()
