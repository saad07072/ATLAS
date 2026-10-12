import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.types import Message, Scope

from backend.app.agent.agent import ChatAgent
from backend.app.agent.providers.errors import ProviderAPIError
from backend.app.api.v1.chat import get_chat_agent, router as chat_router
from backend.app.api.v1.conversations import router as conversations_router
from backend.app.conversations.errors import ConversationStoreUnavailable
from backend.app.conversations.models import (
    DEFAULT_CONVERSATION_TITLE,
    ConversationCreate,
    ConversationMessage,
    ConversationRecord,
    ConversationRole,
    ConversationRename,
)
from backend.app.conversations.repository import (
    PostgresConversationRepository,
)
from backend.app.conversations.runtime import get_conversation_service
from backend.app.conversations.service import ConversationService
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.conversations.errors import ConversationNotFound
from backend.app.security.identity import get_optional_authenticated_user_id

USER_A = UUID("ef3e7347-a8e9-4d63-90cf-a21d5c855515")
USER_B = UUID("43ad3973-5d96-4608-8b7b-3e774106429a")


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self.conversations: dict[str, tuple[str, ConversationRecord]] = {}
        self.messages: dict[str, tuple[str, ConversationMessage]] = {}
        self.clock = datetime.now(timezone.utc)
        self.fail = False
        self.fail_assistant_append = False

    def _check_available(self) -> None:
        if self.fail:
            raise ConversationStoreUnavailable("database credentials must not leak")

    def _tick(self) -> datetime:
        self.clock += timedelta(microseconds=1)
        return self.clock

    def create(self, user_id: str, title: str) -> ConversationRecord:
        self._check_available()
        now = self._tick()
        record = ConversationRecord(
            id=str(uuid4()),
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.conversations[record.id] = (user_id, record)
        return record

    def list(
        self,
        user_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationRecord], bool]:
        self._check_available()
        records = sorted(
            (
                record
                for owner, record in self.conversations.values()
                if owner == user_id
            ),
            key=lambda record: (record.updated_at, record.id),
            reverse=True,
        )
        page = records[offset : offset + limit + 1]
        return page[:limit], len(page) > limit

    def get(
        self,
        user_id: str,
        conversation_id: str,
    ) -> ConversationRecord | None:
        self._check_available()
        stored = self.conversations.get(conversation_id)
        if stored is None or stored[0] != user_id:
            return None
        return stored[1]

    def rename(
        self,
        user_id: str,
        conversation_id: str,
        title: str,
    ) -> ConversationRecord | None:
        self._check_available()
        stored = self.conversations.get(conversation_id)
        if stored is None or stored[0] != user_id:
            return None
        record = stored[1].model_copy(
            update={"title": title, "updated_at": self._tick()}
        )
        self.conversations[conversation_id] = (user_id, record)
        return record

    def delete(self, user_id: str, conversation_id: str) -> bool:
        self._check_available()
        stored = self.conversations.get(conversation_id)
        if stored is None or stored[0] != user_id:
            return False
        del self.conversations[conversation_id]
        self.messages = {
            message_id: message
            for message_id, message in self.messages.items()
            if message[1].conversation_id != conversation_id
        }
        return True

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[ConversationMessage], bool]:
        self._check_available()
        if self.get(user_id, conversation_id) is None:
            return [], False
        records = sorted(
            (
                message
                for owner, message in self.messages.values()
                if owner == user_id and message.conversation_id == conversation_id
            ),
            key=lambda message: (message.created_at, message.id),
        )
        page = list(reversed(records))[offset : offset + limit + 1]
        return list(reversed(page[:limit])), len(page) > limit

    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        *,
        excluding_message_id: str,
        limit: int,
    ) -> list[ConversationMessage] | None:
        self._check_available()
        if self.get(user_id, conversation_id) is None:
            return None
        records = sorted(
            (
                message
                for owner, message in self.messages.values()
                if owner == user_id
                and message.conversation_id == conversation_id
                and message.id != excluding_message_id
            ),
            key=lambda message: (message.created_at, message.id),
        )
        return records[-limit:]

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        *,
        role: ConversationRole,
        content: str,
    ) -> ConversationMessage | None:
        self._check_available()
        if self.fail_assistant_append and role == "assistant":
            raise ConversationStoreUnavailable("database credentials must not leak")
        stored = self.conversations.get(conversation_id)
        if stored is None or stored[0] != user_id:
            return None
        message = ConversationMessage(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=self._tick(),
        )
        self.messages[message.id] = (user_id, message)
        record = stored[1]
        title = record.title
        if role == "user" and title == DEFAULT_CONVERSATION_TITLE:
            title = content[:80]
        self.conversations[conversation_id] = (
            user_id,
            record.model_copy(update={"title": title, "updated_at": self._tick()}),
        )
        return message


def create_test_app(
    service: ConversationService,
    *,
    user_id: UUID | None = USER_A,
    agent: ChatAgent | None = None,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.dependency_overrides[get_optional_authenticated_user_id] = lambda: user_id
    app.dependency_overrides[get_conversation_service] = lambda: service
    if agent is not None:
        app.dependency_overrides[get_chat_agent] = lambda: agent
    return app


async def api_request(
    app: FastAPI,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
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
    return status_code, json.loads(response_body) if response_body else {}


class ConversationModelTests(unittest.TestCase):
    def test_titles_and_messages_are_bounded_and_reject_secrets(self) -> None:
        self.assertEqual(ConversationCreate().title, DEFAULT_CONVERSATION_TITLE)
        for title in (" ", "x" * 121, "api_key: private-value"):
            with self.subTest(title=title[:20]), self.assertRaises(ValidationError):
                ConversationRename(title=title)
        for content in (" ", "x" * 8001, "password: private-value"):
            with self.subTest(content=content[:20]), self.assertRaises(ValidationError):
                ConversationMessage(
                    id=str(uuid4()),
                    conversation_id=str(uuid4()),
                    role="user",
                    content=content,
                    created_at=datetime.now(timezone.utc),
                )


class ConversationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryConversationRepository()
        self.service = ConversationService(self.repository)

    def test_creation_listing_rename_and_delete_are_owner_scoped(self) -> None:
        first = self.service.create(str(USER_A))
        second = self.service.create(str(USER_A))
        other = self.service.create(str(USER_B))
        self.service.append_message(
            str(USER_A),
            first.id,
            role="user",
            content="Explain the release plan",
        )

        listing, has_more = self.service.list(str(USER_A), limit=1)
        self.assertTrue(has_more)
        self.assertEqual(listing[0].id, first.id)
        self.assertNotIn(other.id, [record.id for record in self.service.list(str(USER_A))[0]])
        with self.assertRaises(ConversationNotFound):
            self.service.get(str(USER_B), first.id)
        with self.assertRaises(ConversationNotFound):
            self.service.rename(str(USER_B), first.id, "Private")
        self.assertFalse(self.service.delete(str(USER_B), first.id))
        self.assertEqual(self.service.rename(str(USER_A), second.id, "Planning").title, "Planning")
        self.assertTrue(self.service.delete(str(USER_A), first.id))
        with self.assertRaises(ConversationNotFound):
            self.service.get(str(USER_A), first.id)

    def test_message_history_is_chronological_and_bounded(self) -> None:
        conversation = self.service.create(str(USER_A))
        for index in range(5):
            self.service.append_message(
                str(USER_A),
                conversation.id,
                role="user",
                content=f"Question {index}",
            )
        record, messages, has_more = self.service.get(
            str(USER_A),
            conversation.id,
            message_limit=3,
        )

        self.assertEqual(record.id, conversation.id)
        self.assertEqual(
            [message.content for message in messages],
            ["Question 2", "Question 3", "Question 4"],
        )
        self.assertTrue(has_more)
        with self.assertRaises(ValueError):
            self.service.get(str(USER_A), conversation.id, message_limit=201)

    def test_deleted_conversation_cascades_messages_and_secrets_are_not_saved(self) -> None:
        conversation = self.service.create(str(USER_A))
        message = self.service.append_message(
            str(USER_A),
            conversation.id,
            role="user",
            content="A normal message",
        )

        self.assertIn(message.id, self.repository.messages)
        with self.assertRaises(ValueError):
            self.service.append_message(
                str(USER_A),
                conversation.id,
                role="user",
                content="api_key: private-value",
            )
        self.service.delete(str(USER_A), conversation.id)
        self.assertNotIn(message.id, self.repository.messages)

    def test_agent_context_respects_the_remaining_character_budget(self) -> None:
        conversation = self.service.create(str(USER_A))
        self.service.append_message(
            str(USER_A),
            conversation.id,
            role="user",
            content="Earlier context",
        )
        latest = self.service.append_message(
            str(USER_A),
            conversation.id,
            role="assistant",
            content="x" * 8000,
        )

        context = self.service.get_context(
            str(USER_A),
            conversation.id,
            excluding_message_id="new-message",
            max_characters=8000,
        )

        self.assertEqual([message.id for message in context], [latest.id])
        self.assertLessEqual(sum(len(message.content) for message in context), 8000)


class ConversationApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = InMemoryConversationRepository()
        self.service = ConversationService(self.repository)
        self.provider = Mock()
        self.provider.generate.return_value = Mock(content="A persisted answer.")
        self.agent = ChatAgent(self.provider)
        self.app = create_test_app(self.service, agent=self.agent)

    async def test_authenticated_crud_message_order_and_delete(self) -> None:
        status_code, created = await api_request(
            self.app,
            "POST",
            "/api/v1/conversations",
            {"user_id": str(USER_B), "title": "Project planning"},
        )
        self.assertEqual(status_code, 422)
        status_code, created = await api_request(
            self.app,
            "POST",
            "/api/v1/conversations",
            {"title": "Project planning"},
        )
        self.assertEqual(status_code, 201)
        conversation_id = created["id"]

        chat_status, response = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {
                "conversation_id": conversation_id,
                "message": "Explain the project plan",
                "user_id": str(USER_B),
            },
        )
        self.assertEqual(chat_status, 422)
        chat_status, response = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {
                "conversation_id": conversation_id,
                "message": "Explain the project plan",
            },
        )
        self.assertEqual(chat_status, 200)
        self.assertEqual(response["conversation_id"], conversation_id)

        detail_status, detail = await api_request(
            self.app,
            "GET",
            f"/api/v1/conversations/{conversation_id}?limit=10",
        )
        self.assertEqual(detail_status, 200)
        self.assertEqual(
            [message["role"] for message in detail["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(detail["messages"][0]["content"], "Explain the project plan")
        self.assertEqual(detail["messages"][1]["content"], "A persisted answer.")

        list_status, listing = await api_request(
            self.app,
            "GET",
            "/api/v1/conversations?limit=10&offset=0",
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(listing["conversations"][0]["id"], conversation_id)

        rename_status, renamed = await api_request(
            self.app,
            "PATCH",
            f"/api/v1/conversations/{conversation_id}",
            {"title": "Release preparation"},
        )
        self.assertEqual(rename_status, 200)
        self.assertEqual(renamed["title"], "Release preparation")
        delete_status, deleted = await api_request(
            self.app,
            "DELETE",
            f"/api/v1/conversations/{conversation_id}",
        )
        self.assertEqual(delete_status, 200)
        self.assertTrue(deleted["deleted"])
        self.assertFalse(self.repository.messages)

    async def test_cross_user_operations_and_invalid_ids_do_not_leak(self) -> None:
        conversation = self.service.create(str(USER_B), "Other user's chat")
        for method, path, body in (
            ("GET", f"/api/v1/conversations/{conversation.id}", None),
            ("PATCH", f"/api/v1/conversations/{conversation.id}", {"title": "Stolen"}),
        ):
            status_code, response = await api_request(self.app, method, path, body)
            self.assertEqual(status_code, 404)
            self.assertEqual(response["error"]["code"], "conversation_not_found")

        chat_status, chat_response = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {
                "conversation_id": conversation.id,
                "message": "Try to append to another user's chat",
            },
        )
        self.assertEqual(chat_status, 404)
        self.assertEqual(chat_response["error"]["code"], "conversation_not_found")
        self.assertEqual(self.repository.messages, {})

        delete_status, delete_response = await api_request(
            self.app,
            "DELETE",
            f"/api/v1/conversations/{conversation.id}",
        )
        self.assertEqual(delete_status, 200)
        self.assertFalse(delete_response["deleted"])
        invalid_status, _ = await api_request(
            self.app,
            "GET",
            "/api/v1/conversations/not-a-uuid",
        )
        self.assertEqual(invalid_status, 422)
        list_status, listing = await api_request(
            self.app,
            "GET",
            "/api/v1/conversations",
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(listing["conversations"], [])

    async def test_unauthenticated_requests_fail_closed(self) -> None:
        app = create_test_app(self.service, user_id=None, agent=self.agent)
        for method, path, body in (
            ("GET", "/api/v1/conversations", None),
            ("POST", "/api/v1/conversations", {}),
            ("POST", "/api/v1/chat", {"message": "Hello"}),
        ):
            status_code, response = await api_request(app, method, path, body)
            self.assertEqual(status_code, 401)
            self.assertEqual(response["error"]["code"], "authentication_required")

    async def test_configured_provider_secret_is_never_persisted(self) -> None:
        secret = "active-provider-secret"
        app = create_test_app(
            self.service,
            agent=ChatAgent(self.provider, secret=secret),
        )
        conversation = self.service.create(str(USER_A))

        status_code, response = await api_request(
            app,
            "POST",
            "/api/v1/chat",
            {"conversation_id": conversation.id, "message": f"My key is {secret}"},
        )

        self.assertEqual(status_code, 422)
        self.assertNotIn(secret, json.dumps(response))
        self.assertEqual(self.repository.messages, {})

    async def test_list_pagination_and_bounded_history(self) -> None:
        first = self.service.create(str(USER_A), "First")
        second = self.service.create(str(USER_A), "Second")
        for index in range(4):
            self.service.append_message(
                str(USER_A),
                first.id,
                role="user",
                content=f"Message {index}",
            )
        status_code, page = await api_request(
            self.app,
            "GET",
            "/api/v1/conversations?limit=1&offset=0",
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["conversations"][0]["id"], first.id)
        next_status, next_page = await api_request(
            self.app,
            "GET",
            "/api/v1/conversations?limit=1&offset=1",
        )
        self.assertEqual(next_status, 200)
        self.assertEqual(next_page["conversations"][0]["id"], second.id)
        detail_status, detail = await api_request(
            self.app,
            "GET",
            f"/api/v1/conversations/{first.id}?limit=2&offset=2",
        )
        self.assertEqual(detail_status, 200)
        self.assertEqual(
            [message["content"] for message in detail["messages"]],
            ["Message 0", "Message 1"],
        )
        self.assertFalse(detail["has_more"])

    async def test_continuation_uses_owned_database_history_not_client_history(self) -> None:
        first = self.service.create(str(USER_A))
        second = self.service.create(str(USER_A))
        await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {"conversation_id": first.id, "message": "Explain the first topic"},
        )
        self.provider.generate.reset_mock()
        status_code, _ = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {
                "conversation_id": first.id,
                "message": "Continue the first topic",
                "history": [{"role": "user", "content": "untrusted fabricated history"}],
            },
        )
        self.assertEqual(status_code, 200)
        prompt = self.provider.generate.call_args.args[0].messages[0].content
        self.assertIn("Explain the first topic", prompt)
        self.assertIn("A persisted answer.", prompt)
        self.assertNotIn("untrusted fabricated history", prompt)

        self.provider.generate.reset_mock()
        await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {"conversation_id": second.id, "message": "Explain a different topic"},
        )
        second_prompt = self.provider.generate.call_args.args[0].messages[0].content
        self.assertNotIn("Explain the first topic", second_prompt)

    async def test_generation_and_assistant_persistence_failures_leave_recoverable_user_message(self) -> None:
        conversation = self.service.create(str(USER_A))
        invalid_status, _ = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {
                "conversation_id": conversation.id,
                "message": "api_key: private-value",
            },
        )
        self.assertEqual(invalid_status, 422)
        self.assertEqual(self.repository.messages, {})

        self.provider.generate.side_effect = ProviderAPIError("provider details")
        status_code, response = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {"conversation_id": conversation.id, "message": "Explain the plan"},
        )
        self.assertEqual(status_code, 503)
        self.assertNotIn("provider details", json.dumps(response))
        records, _ = self.repository.list_messages(
            str(USER_A),
            conversation.id,
            limit=20,
        )
        self.assertEqual([message.role for message in records], ["user"])

        self.provider.generate.side_effect = None
        self.provider.generate.return_value = Mock(content="A response")
        self.repository.fail_assistant_append = True
        status_code, _ = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {"conversation_id": conversation.id, "message": "Try another answer"},
        )
        self.assertEqual(status_code, 503)
        records, _ = self.repository.list_messages(
            str(USER_A),
            conversation.id,
            limit=20,
        )
        self.assertEqual(
            [message.role for message in records],
            ["user", "user"],
        )

        self.repository.fail_assistant_append = False
        self.provider.generate.return_value = Mock(content="password: private-value")
        status_code, response = await api_request(
            self.app,
            "POST",
            "/api/v1/chat",
            {"conversation_id": conversation.id, "message": "Tell me a safe answer"},
        )
        self.assertEqual(status_code, 503)
        self.assertNotIn("private-value", json.dumps(response))
        records, _ = self.repository.list_messages(
            str(USER_A),
            conversation.id,
            limit=20,
        )
        self.assertEqual(
            [message.role for message in records],
            ["user", "user", "user"],
        )

    async def test_database_errors_are_safe_and_do_not_echo_credentials(self) -> None:
        self.repository.fail = True
        status_code, response = await api_request(
            self.app,
            "GET",
            "/api/v1/conversations",
        )
        self.assertEqual(status_code, 503)
        self.assertEqual(response["error"]["code"], "conversation_unavailable")
        self.assertNotIn("credentials", json.dumps(response))


class PostgresConversationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = PostgresConversationRepository(
            "postgresql://not-a-real-secret"
        )
        self.connection = Mock()
        self.connection.__enter__ = Mock(return_value=self.connection)
        self.connection.__exit__ = Mock(return_value=None)
        self.connect_patcher = patch(
            "psycopg.connect",
            return_value=self.connection,
        )
        self.connect = self.connect_patcher.start()
        self.addCleanup(self.connect_patcher.stop)

    def test_owner_scoped_queries_set_authenticated_rls_claims(self) -> None:
        now = datetime.now(timezone.utc)
        self.connection.execute.return_value.fetchall.return_value = [
            {
                "id": str(uuid4()),
                "title": "Planning",
                "created_at": now,
                "updated_at": now,
            }
        ]
        self.repository.list(str(USER_A), limit=10, offset=0)

        self.assertEqual(
            self.connection.execute.call_args_list[0].args[0],
            "SET LOCAL ROLE authenticated",
        )
        claim_args = self.connection.execute.call_args_list[1].args
        claims = json.loads(claim_args[1][1])
        self.assertEqual(claims["sub"], str(USER_A))
        self.assertTrue(claims["atlas_backend"])
        sql, params = self.connection.execute.call_args_list[2].args
        self.assertIn("WHERE user_id = %s", sql)
        self.assertIn("ORDER BY updated_at DESC, id DESC", sql)
        self.assertEqual(params, (str(USER_A), 11, 0))

    def test_message_history_query_is_owner_filtered_ordered_and_bounded(self) -> None:
        now = datetime.now(timezone.utc)
        conversation_id = str(uuid4())
        self.connection.execute.return_value.fetchone.return_value = {"?column?": 1}
        self.connection.execute.return_value.fetchall.return_value = [
            {
                "id": str(uuid4()),
                "conversation_id": conversation_id,
                "role": "user",
                "content": "A message",
                "created_at": now,
            }
        ]

        messages, has_more = self.repository.list_messages(
            str(USER_A),
            conversation_id,
            limit=5,
        )

        history_query, params = self.connection.execute.call_args_list[-1].args
        self.assertIn("WHERE user_id = %s AND conversation_id = %s", history_query)
        self.assertIn("ORDER BY created_at DESC, id DESC", history_query)
        self.assertIn("ORDER BY created_at ASC, id ASC", history_query)
        self.assertEqual(params, (str(USER_A), conversation_id, 6, 0))
        self.assertEqual(len(messages), 1)
        self.assertFalse(has_more)

    def test_append_message_updates_activity_and_keeps_content_parameterized(self) -> None:
        now = datetime.now(timezone.utc)
        conversation_id = str(uuid4())
        content = "Explain the project plan"
        self.connection.execute.return_value.fetchone.return_value = {"?column?": 1}
        self.connection.execute.return_value.fetchone.side_effect = [
            {"?column?": 1},
            {
                "id": str(uuid4()),
                "conversation_id": conversation_id,
                "role": "user",
                "content": content,
                "created_at": now,
            },
        ]

        self.repository.append_message(
            str(USER_A),
            conversation_id,
            role="user",
            content=content,
        )

        insert_sql, insert_params = self.connection.execute.call_args_list[-2].args
        self.assertIn("INSERT INTO public.atlas_conversation_messages", insert_sql)
        self.assertNotIn(content, insert_sql)
        self.assertEqual(insert_params[-1], content)
        update_sql = self.connection.execute.call_args_list[-1].args[0]
        self.assertIn("updated_at = now()", update_sql)

    def test_database_errors_and_missing_configuration_fail_closed(self) -> None:
        repository = PostgresConversationRepository(None)
        with self.assertRaises(ConversationStoreUnavailable):
            repository.list(str(USER_A), limit=5, offset=0)

        self.connect.side_effect = psycopg.OperationalError(
            "database password must not leak"
        )
        with self.assertRaises(ConversationStoreUnavailable) as error:
            self.repository.list(str(USER_A), limit=5, offset=0)
        self.assertNotIn("password", str(error.exception))


if __name__ == "__main__":
    unittest.main()
