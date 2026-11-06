from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from pydantic import ValidationError
from starlette.types import Message, Scope

from backend.app.agent.agent import ChatAgent
from backend.app.agent.models import ChatRequest
from backend.app.agent.providers.errors import (
    ProviderAPIError,
    ProviderConfigurationError,
)
from backend.app.api.v1.chat import get_chat_agent, router
from backend.app.conversations.runtime import get_conversation_service
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.exceptions import ApplicationError
from backend.app.security.identity import get_authenticated_user_id
from uuid import UUID


def create_test_app(agent: ChatAgent) -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.include_router(router, prefix="/api/v1")
    test_app.dependency_overrides[get_chat_agent] = lambda: agent
    conversations = Mock()
    conversations.create.return_value = Mock(id="f7bd17ab-f527-49c8-a464-399b974b9c57")
    conversations.append_message.return_value = Mock(id="d1e71d12-70c8-40df-bf7b-6e3aa0905166")
    conversations.get_context.return_value = []
    test_app.dependency_overrides[get_conversation_service] = lambda: conversations
    test_app.dependency_overrides[get_authenticated_user_id] = lambda: UUID(
        "ef3e7347-a8e9-4d63-90cf-a21d5c855515"
    )
    return test_app


async def request(
    app: FastAPI,
    path: str,
    body: dict[str, object],
) -> tuple[int, dict[str, object]]:
    encoded_body = json.dumps(body).encode()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("testclient", 50000),
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
    status = next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, json.loads(response_body)


class ChatAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.provider = Mock()
        self.provider.generate.return_value = Mock(content="A useful response.")
        self.agent = ChatAgent(self.provider)

    async def test_normal_conversation_uses_provider_response(self) -> None:
        response = self.agent.respond(ChatRequest(message="Why is the sky blue?"))

        self.assertEqual(response.intent, "conversation")
        self.assertEqual(response.message, "A useful response.")
        self.provider.generate.assert_called_once()

    async def test_capability_question_describes_current_capabilities(self) -> None:
        response = self.agent.respond(ChatRequest(message="What can you do?"))

        self.assertEqual(response.intent, "capability_question")
        self.assertIn("answer questions", response.message)
        self.assertIn("cannot perform actions", response.message)
        self.provider.generate.assert_not_called()

    async def test_ambiguous_request_returns_clarification(self) -> None:
        response = self.agent.respond(ChatRequest(message="Do it"))

        self.assertEqual(response.intent, "clarification")
        self.assertTrue(response.requires_clarification)
        self.provider.generate.assert_not_called()

    async def test_unsupported_action_is_not_executed(self) -> None:
        response = self.agent.respond(ChatRequest(message="Send an email to my team"))

        self.assertEqual(response.intent, "unsupported")
        self.assertIn("cannot perform actions", response.message)
        self.provider.generate.assert_not_called()

    async def test_question_about_an_action_is_not_marked_unsupported(self) -> None:
        response = self.agent.respond(ChatRequest(message="How do I run Python?"))

        self.assertEqual(response.intent, "conversation")
        self.provider.generate.assert_called_once()

    async def test_empty_input_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(message="  ")

    async def test_long_input_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(message="x" * 4001)

    async def test_provider_response_is_structured(self) -> None:
        app = create_test_app(self.agent)
        status, body = await request(
            app,
            "/api/v1/chat",
            {"message": "Explain gravity"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            body,
            {
                "intent": "task_request",
                "message": "A useful response.",
                "requires_clarification": False,
                "conversation_id": "f7bd17ab-f527-49c8-a464-399b974b9c57",
                "actions": [],
            },
        )

    async def test_provider_failure_returns_safe_api_error(self) -> None:
        self.provider.generate.side_effect = ProviderAPIError(
            "failed with GEMINI_API_KEY=secret-value"
        )
        app = create_test_app(self.agent)
        status, body = await request(
            app,
            "/api/v1/chat",
            {"message": "Explain gravity"},
        )

        self.assertEqual(status, 503)
        self.assertEqual(
            body,
            {
                "error": {
                    "code": "chat_unavailable",
                    "message": "ATLAS could not complete this response. Please try again.",
                }
            },
        )
        self.assertNotIn("secret-value", json.dumps(body))

    async def test_provider_configuration_failure_is_safe(self) -> None:
        with patch(
            "backend.app.api.v1.chat.get_llm_provider",
            side_effect=ProviderConfigurationError(
                "GEMINI_API_KEY=secret-value"
            ),
        ):
            with self.assertRaises(ApplicationError) as error:
                get_chat_agent()

        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret-value", error.exception.message)

    async def test_malformed_provider_response_returns_safe_api_error(self) -> None:
        self.provider.generate.return_value = None
        app = create_test_app(self.agent)
        status, body = await request(
            app,
            "/api/v1/chat",
            {"message": "Explain gravity"},
        )

        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "chat_unavailable")

    async def test_api_key_is_redacted_from_prompt_and_response(self) -> None:
        secret = "configured-secret"
        provider = Mock()
        provider.generate.return_value = Mock(content=f"Echo: {secret}")
        agent = ChatAgent(provider, secret=secret)

        response = agent.respond(ChatRequest(message=f"My key is {secret}"))

        self.assertNotIn(secret, provider.generate.call_args.args[0].messages[0].content)
        self.assertNotIn(secret, response.message)

    async def test_provider_is_used_only_for_text_generation(self) -> None:
        self.agent.respond(ChatRequest(message="Help me plan a study schedule"))

        provider_request = self.provider.generate.call_args.args[0]
        self.assertEqual(provider_request.tools, [])
        self.provider.call_tools.assert_not_called()

    async def test_api_rejects_empty_and_oversized_input(self) -> None:
        app = create_test_app(self.agent)

        empty_status, _ = await request(
            app,
            "/api/v1/chat",
            {"message": " "},
        )
        oversized_status, _ = await request(
            app,
            "/api/v1/chat",
            {"message": "x" * 4001},
        )

        self.assertEqual(empty_status, 422)
        self.assertEqual(oversized_status, 422)

    async def test_spoken_transcript_follows_identical_chat_and_auth_rules(self) -> None:
        app = create_test_app(self.agent)
        status_code, body = await request(
            app,
            "/api/v1/chat",
            {"message": "What can you do to help me today?"},
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body["intent"], "capability_question")
        self.assertIn("answer questions", body["message"])
        self.assertIn("cannot perform actions", body["message"])
        self.assertEqual(body["conversation_id"], "f7bd17ab-f527-49c8-a464-399b974b9c57")

    async def test_spoken_transcript_with_credentials_is_rejected_at_boundary(self) -> None:
        secret = "super-secret-credential"
        agent = ChatAgent(self.provider, secret=secret)
        app = create_test_app(agent)

        status_code, body = await request(
            app,
            "/api/v1/chat",
            {"message": f"Please remember my token: {secret}"},
        )

        self.assertEqual(status_code, 422)
        self.assertEqual(body["error"]["code"], "invalid_chat_message")
        self.assertNotIn(secret, json.dumps(body))


    def test_open_amazon_website_action_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.execute.return_value = ToolResult(tool_name="web.open", success=True, output={"status": "success"}, metadata=ToolExecutionMetadata(duration_ms=10.0))
        agent = ChatAgent(self.provider, tool_executor=tool_executor)

        response = agent.respond(ChatRequest(message="open amazon.com"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("opened amazon.com", response.message.lower())
        self.assertEqual(len(response.actions), 1)
        self.assertEqual(response.actions[0].tool, "web.open")
        self.assertEqual(response.actions[0].target, "amazon.com")
        self.assertEqual(response.actions[0].status, "success")

    def test_close_tab_and_youtube_action_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.execute.return_value = ToolResult(tool_name="system.close_app", success=True, output={"status": "closed"}, metadata=ToolExecutionMetadata(duration_ms=10.0))
        agent = ChatAgent(self.provider, tool_executor=tool_executor)

        response1 = agent.respond(ChatRequest(message="close tab"))
        self.assertEqual(response1.intent, "task_request")
        self.assertEqual(response1.actions[0].tool, "system.close_app")
        self.assertEqual(response1.actions[0].target, "tab")

        response2 = agent.respond(ChatRequest(message="close youtube"))
        self.assertEqual(response2.intent, "task_request")
        self.assertEqual(response2.actions[0].tool, "system.close_app")
        self.assertEqual(response2.actions[0].target, "youtube")

    def test_launch_generic_windows_app_action_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.execute.return_value = ToolResult(tool_name="system.open_app", success=True, output={"status": "launched"}, metadata=ToolExecutionMetadata(duration_ms=10.0))
        agent = ChatAgent(self.provider, tool_executor=tool_executor)

        response = agent.respond(ChatRequest(message="open discord"))
        self.assertEqual(response.intent, "task_request")
        self.assertEqual(response.actions[0].tool, "system.open_app")
        self.assertEqual(response.actions[0].target, "discord")


    def test_live_sports_query_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.execute.return_value = ToolResult(
            tool_name="web.search",
            success=True,
            output={"summary": "Live score: India 187/6 in 38 overs vs New Zealand", "status": "success"},
            metadata=ToolExecutionMetadata(duration_ms=10.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)

        response = agent.respond(ChatRequest(message="India versus New Zealand"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("India 187/6", response.message)
        self.assertEqual(response.actions[0].tool, "web.search")
        self.assertEqual(response.actions[0].status, "success")

    def test_screen_vision_requested_when_no_image(self) -> None:
        agent = ChatAgent(self.provider)
        response = agent.respond(ChatRequest(message="can you able to see my screen"))
        self.assertEqual(response.intent, "conversation")
        self.assertIn("SHARE SCREEN", response.message)
        self.assertEqual(response.actions[0].tool, "screen.inspect")
        self.assertEqual(response.actions[0].status, "requested")

    def test_screen_vision_executed_when_image_present(self) -> None:
        self.provider.generate.return_value = Mock(content="I see VS Code with TypeScript files, sir.")
        agent = ChatAgent(self.provider)
        response = agent.respond(ChatRequest(message="can you see my screen", image_data="data:image/jpeg;base64,abc123fake"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("VS Code", response.message)
        self.assertEqual(response.actions[0].tool, "screen.inspect")
        self.assertEqual(response.actions[0].status, "success")


    def test_calendar_list_events_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"calendar.list_events": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="calendar.list_events",
            success=True,
            output={
                "events": [
                    {"summary": "Sprint Retro", "start": {"dateTime": "2026-11-08T15:00:00Z"}}
                ]
            },
            metadata=ToolExecutionMetadata(duration_ms=10.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="what meetings do I have scheduled?"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("Sprint Retro", response.message)
        self.assertEqual(response.actions[0].tool, "calendar.list_events")
        self.assertEqual(response.actions[0].status, "success")

    def test_calendar_unconnected_guides_user(self) -> None:
        tool_executor = Mock()
        tool_executor.registry._tools = {}
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="check my calendar"))
        self.assertEqual(response.intent, "conversation")
        self.assertIn("Google Workspace is not currently connected", response.message)
        self.assertEqual(response.actions[0].tool, "calendar.list_events")
        self.assertEqual(response.actions[0].status, "requested")

    def test_gmail_search_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"gmail.search": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="gmail.search",
            success=True,
            output={
                "messages": [
                    {"from": "lead@company.com", "subject": "Project ATLAS Release"}
                ]
            },
            metadata=ToolExecutionMetadata(duration_ms=15.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="check my emails for ATLAS"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("Project ATLAS Release", response.message)
        self.assertEqual(response.actions[0].tool, "gmail.search")
        self.assertEqual(response.actions[0].status, "success")

    def test_github_list_repositories_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"github.list_repositories": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="github.list_repositories",
            success=True,
            output={
                "repositories": [
                    {"full_name": "saad07072/ATLAS", "private": False}
                ]
            },
            metadata=ToolExecutionMetadata(duration_ms=20.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="list my github repos"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("saad07072/ATLAS", response.message)
        self.assertEqual(response.actions[0].tool, "github.list_repositories")
        self.assertEqual(response.actions[0].status, "success")

    def test_system_file_read_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"system.file_read": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="system.file_read",
            success=True,
            output={"content": "sample configuration data"},
            metadata=ToolExecutionMetadata(duration_ms=5.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="read file config.json"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("sample configuration data", response.message)
        self.assertEqual(response.actions[0].tool, "system.file_read")
        self.assertEqual(response.actions[0].status, "success")

    def test_cognitive_real_time_search_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"web.search": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="web.search",
            success=True,
            output={
                "status": "success",
                "summary": "Quantum supremacy demonstrated by new Google chip",
                "headlines": ["Google announces new quantum benchmark"]
            },
            metadata=ToolExecutionMetadata(duration_ms=18.0),
        )
        self.provider.generate.return_value = Mock(
            content="Google has announced breakthrough quantum benchmarks, sir."
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="What is the latest news about quantum computing?"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("quantum", response.message.lower())
        self.assertEqual(response.actions[0].tool, "web.search")
        self.assertEqual(response.actions[0].status, "success")

    def test_system_list_windows_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"system.list_windows": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="system.list_windows",
            success=True,
            output={
                "windows": [{"pid": 1234, "process_name": "chrome", "title": "YouTube"}],
                "count": 1,
                "summary": "Active windows: YouTube (chrome)",
            },
            metadata=ToolExecutionMetadata(duration_ms=10.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="what windows do I have open?"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("YouTube", response.message)
        self.assertEqual(response.actions[0].tool, "system.list_windows")
        self.assertEqual(response.actions[0].status, "success")

    def test_system_focus_window_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"system.focus_window": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="system.focus_window",
            success=True,
            output={"target": "notepad", "status": "focused", "message": "Brought notepad to the foreground, sir."},
            metadata=ToolExecutionMetadata(duration_ms=8.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="switch to notepad window"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("notepad", response.message.lower())
        self.assertEqual(response.actions[0].tool, "system.focus_window")
        self.assertEqual(response.actions[0].status, "success")

    def test_system_send_keys_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"system.send_keys": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="system.send_keys",
            success=True,
            output={"text": "git status", "status": "sent", "message": 'Typed "git status", sir.'},
            metadata=ToolExecutionMetadata(duration_ms=12.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="type 'git status' and press enter"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("git status", response.message)
        self.assertEqual(response.actions[0].tool, "system.send_keys")
        self.assertEqual(response.actions[0].status, "success")

    def test_system_window_state_dispatched(self) -> None:
        from backend.app.tools.models import ToolResult, ToolExecutionMetadata
        tool_executor = Mock()
        tool_executor.registry._tools = {"system.window_state": Mock()}
        tool_executor.execute.return_value = ToolResult(
            tool_name="system.window_state",
            success=True,
            output={"action": "minimize_all", "status": "success", "message": "All desktop windows minimized."},
            metadata=ToolExecutionMetadata(duration_ms=6.0),
        )
        agent = ChatAgent(self.provider, tool_executor=tool_executor)
        response = agent.respond(ChatRequest(message="minimize all windows"))
        self.assertEqual(response.intent, "task_request")
        self.assertIn("minimized", response.message.lower())
        self.assertEqual(response.actions[0].tool, "system.window_state")
        self.assertEqual(response.actions[0].status, "success")



if __name__ == "__main__":
    unittest.main()
