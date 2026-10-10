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
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.exceptions import ApplicationError
from backend.app.security.identity import get_authenticated_user_id
from uuid import UUID


def create_test_app(agent: ChatAgent) -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.include_router(router, prefix="/api/v1")
    test_app.dependency_overrides[get_chat_agent] = lambda: agent
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


if __name__ == "__main__":
    unittest.main()
