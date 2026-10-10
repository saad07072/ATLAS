import json
import unittest
from datetime import datetime, timezone
from uuid import UUID, uuid4
from unittest.mock import Mock, patch

import psycopg
from fastapi import FastAPI
from starlette.types import Message, Scope

from backend.app.agent.agent import ChatAgent, ChatAgentError
from backend.app.agent.models import ChatRequest
from backend.app.api.v1.memory import router as memory_router
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.memory.errors import MemoryNotFound, MemoryStoreUnavailable
from backend.app.memory.models import (
    MemoryCandidate,
    MemoryRecord,
    MemorySource,
    MemoryType,
    MemoryUpdate,
)
from backend.app.memory.repository import PostgresMemoryRepository
from backend.app.memory.service import MemoryService
from backend.app.security.identity import get_optional_authenticated_user_id

USER_ID = "ef3e7347-a8e9-4d63-90cf-a21d5c855515"
OTHER_USER_ID = "43ad3973-5d96-4608-8b7b-3e774106429a"


def create_candidate(
    memory_type: MemoryType = MemoryType.DURABLE_FACT,
    *,
    key: str = "current-project",
    content: str = "The current project is ATLAS.",
) -> MemoryCandidate:
    return MemoryCandidate(type=memory_type, memory_key=key, content=content)


def create_record(
    candidate: MemoryCandidate,
    *,
    user_id: str = USER_ID,
    source: MemorySource = MemorySource.USER,
    memory_id: str | None = None,
    relevance: float | None = None,
) -> tuple[str, MemoryRecord]:
    now = datetime.now(timezone.utc)
    record = MemoryRecord(
        id=memory_id or str(uuid4()),
        type=candidate.type,
        memory_key=candidate.memory_key,
        content=candidate.content,
        source=source,
        created_at=now,
        updated_at=now,
        relevance=relevance,
    )
    return user_id, record


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, MemoryRecord]] = {}
        self.last_retrieval: tuple[str, str, str | None, int] | None = None

    def list(
        self,
        user_id: str,
        *,
        memory_type: str | None,
        limit: int,
    ) -> list[MemoryRecord]:
        records = [
            record
            for owner, record in self.records.values()
            if owner == user_id
            and (memory_type is None or record.type.value == memory_type)
        ]
        return records[:limit]

    def create(
        self,
        user_id: str,
        candidate: MemoryCandidate,
        *,
        source: str,
    ) -> MemoryRecord:
        existing = next(
            (
                (memory_id, owner, record)
                for memory_id, (owner, record) in self.records.items()
                if owner == user_id
                and record.type == candidate.type
                and record.memory_key == candidate.memory_key
            ),
            None,
        )
        source_value = MemorySource(source)
        if existing:
            memory_id, _, current = existing
            record = current.model_copy(
                update={
                    "content": candidate.content,
                    "source": source_value,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        else:
            _, record = create_record(candidate, user_id=user_id, source=source_value)
            memory_id = record.id
        self.records[memory_id] = (user_id, record)
        return record

    def update(
        self,
        user_id: str,
        memory_id: str,
        changes: MemoryUpdate,
    ) -> MemoryRecord | None:
        stored = self.records.get(memory_id)
        if stored is None or stored[0] != user_id:
            return None
        changes_dict = changes.model_dump(exclude_unset=True)
        if "type" in changes_dict:
            changes_dict["type"] = MemoryType(changes_dict["type"])
        record = stored[1].model_copy(
            update={
                **changes_dict,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.records[memory_id] = (user_id, record)
        return record

    def delete(self, user_id: str, memory_id: str) -> bool:
        stored = self.records.get(memory_id)
        if stored is None or stored[0] != user_id:
            return False
        del self.records[memory_id]
        return True

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        memory_type: str | None,
        limit: int,
    ) -> list[MemoryRecord]:
        self.last_retrieval = (user_id, query, memory_type, limit)
        query_tokens = set(query.lower().split())
        matching: list[MemoryRecord] = []
        for owner, record in self.records.values():
            if owner != user_id or (
                memory_type is not None and record.type.value != memory_type
            ):
                continue
            if query_tokens.intersection(record.content.lower().split()):
                matching.append(record)
        return matching[:limit]


def create_test_app(
    service: MemoryService,
    *,
    user_id: UUID | None = UUID(USER_ID),
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(memory_router, prefix="/api/v1")
    app.dependency_overrides[get_optional_authenticated_user_id] = lambda: user_id
    from backend.app.memory.runtime import get_memory_service

    app.dependency_overrides[get_memory_service] = lambda: service
    return app


async def api_request(
    app: FastAPI,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    encoded_body = json.dumps(body or {}).encode()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
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


class MemoryValidationTests(unittest.TestCase):
    def test_normalizes_candidate_and_rejects_unbounded_or_invalid_input(self) -> None:
        candidate = MemoryCandidate(
            type="user_preference",
            memory_key=" Meeting.Time ",
            content="  I prefer meetings after 2 PM.  ",
        )

        self.assertEqual(candidate.memory_key, "meeting.time")
        self.assertEqual(candidate.content, "I prefer meetings after 2 PM.")
        with self.assertRaises(ValueError):
            MemoryCandidate(type="not-a-type", memory_key="valid", content="value")
        with self.assertRaises(ValueError):
            MemoryCandidate(type="durable_fact", memory_key="invalid key", content="x")
        with self.assertRaises(ValueError):
            MemoryCandidate(type="durable_fact", memory_key="valid", content="x" * 4001)
        with self.assertRaises(ValueError):
            MemoryCandidate(type="durable_fact", memory_key="valid", content="  ")

    def test_rejects_credentials_and_secret_tokens(self) -> None:
        secret_values = (
            "My API key is super-secret",
            "password=hunter2",
            "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            "sk-abcdefghijklmnopqrstuvwxyz123456",
            "AKIA1234567890123456",
            "ya29.abcdefghijklmnopqrstuvwxyz",
            "-----BEGIN PRIVATE KEY-----",
        )
        for value in secret_values:
            with self.subTest(value=value[:12]), self.assertRaises(ValueError):
                create_candidate(content=value)

    def test_updates_cannot_be_empty_or_contain_secrets(self) -> None:
        with self.assertRaises(ValueError):
            MemoryService(FakeMemoryRepository()).update(
                USER_ID,
                str(uuid4()),
                MemoryUpdate(),
            )
        with self.assertRaises(ValueError):
            MemoryUpdate(content="access_token: abc123")


class MemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeMemoryRepository()
        self.service = MemoryService(self.repository)

    def test_create_same_key_updates_instead_of_creating_conflicting_rows(self) -> None:
        first = self.service.create(USER_ID, create_candidate())
        updated = self.service.create(
            USER_ID,
            create_candidate(content="The current project is Atlas v2."),
        )

        self.assertEqual(first.id, updated.id)
        self.assertEqual(updated.content, "The current project is Atlas v2.")
        self.assertEqual(len(self.repository.records), 1)

    def test_task_outcome_requires_explicit_source_and_update_preserves_identity(self) -> None:
        outcome = self.service.create(
            USER_ID,
            create_candidate(
                MemoryType.TASK_OUTCOME,
                key="release",
                content="Release completed after tests passed.",
            ),
        )
        updated = self.service.update(
            USER_ID,
            outcome.id,
            MemoryUpdate(content="Release completed and was verified."),
        )

        self.assertEqual(outcome.source, MemorySource.EXPLICIT_SELECTION)
        self.assertEqual(updated.id, outcome.id)
        self.assertEqual(updated.content, "Release completed and was verified.")
        with self.assertRaises(MemoryNotFound):
            self.service.update(OTHER_USER_ID, outcome.id, MemoryUpdate(content="No access"))

    def test_retrieval_forwards_user_type_query_and_bound(self) -> None:
        self.service.create(USER_ID, create_candidate())
        self.service.create(
            OTHER_USER_ID,
            create_candidate(key="secret-project", content="The project is another user's."),
        )
        results = self.service.retrieve(
            USER_ID,
            "  current project ",
            memory_type=MemoryType.DURABLE_FACT,
            limit=2,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            self.repository.last_retrieval,
            (USER_ID, "current project", "durable_fact", 2),
        )
        with self.assertRaises(ValueError):
            self.service.retrieve(USER_ID, "x" * 501)
        with self.assertRaises(ValueError):
            self.service.retrieve(USER_ID, " ")

    def test_delete_excludes_memory_from_later_retrieval(self) -> None:
        record = self.service.create(USER_ID, create_candidate())

        self.assertFalse(self.service.delete(OTHER_USER_ID, record.id))
        self.assertEqual(
            self.service.retrieve(USER_ID, "current project")[0].id,
            record.id,
        )
        self.assertTrue(self.service.delete(USER_ID, record.id))
        self.assertEqual(self.service.retrieve(USER_ID, "current project"), [])
        self.assertFalse(self.service.delete(USER_ID, record.id))

    def test_list_filters_by_owner_and_type(self) -> None:
        self.service.create(USER_ID, create_candidate())
        self.service.create(
            USER_ID,
            create_candidate(
                MemoryType.PROJECT_CONTEXT,
                key="project",
                content="Project architecture and components.",
            ),
        )
        self.service.create(
            OTHER_USER_ID,
            create_candidate(key="another", content="Another user's fact."),
        )

        memories = self.service.list(
            USER_ID,
            memory_type=MemoryType.DURABLE_FACT,
            limit=1,
        )

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].type, MemoryType.DURABLE_FACT)
        with self.assertRaises(ValueError):
            self.service.list(USER_ID, limit=101)


class PostgresMemoryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = PostgresMemoryRepository("postgresql://not-a-real-secret")
        self.connection = Mock()
        self.connection.__enter__ = Mock(return_value=self.connection)
        self.connection.__exit__ = Mock(return_value=None)
        self.connect_patcher = patch("psycopg.connect", return_value=self.connection)
        self.connect = self.connect_patcher.start()
        self.addCleanup(self.connect_patcher.stop)

    def test_retrieval_uses_parameterized_user_filter_type_rank_and_limit(self) -> None:
        now = datetime.now(timezone.utc)
        self.connection.execute.return_value.fetchall.return_value = [
            {
                "id": str(uuid4()),
                "type": "project_context",
                "memory_key": "current-project",
                "content": "ATLAS project uses PostgreSQL.",
                "source": "user",
                "created_at": now,
                "updated_at": now,
                "relevance": 0.8,
            }
        ]

        rows = self.repository.retrieve(
            USER_ID,
            "current project",
            memory_type="project_context",
            limit=3,
        )

        sql, params = self.connection.execute.call_args.args
        self.assertIn("m.user_id = %s", sql)
        self.assertIn("search_document @@ q.terms", sql)
        self.assertIn("ORDER BY relevance DESC", sql)
        self.assertEqual(params, ("current project", USER_ID, "project_context", "project_context", 3))
        self.assertEqual(rows[0].relevance, 0.8)
        self.connect.assert_called_once()

    def test_create_performs_keyed_upsert_and_queries_are_parameterized(self) -> None:
        now = datetime.now(timezone.utc)
        candidate = create_candidate()
        self.connection.execute.return_value.fetchone.return_value = {
            "id": str(uuid4()),
            "type": candidate.type.value,
            "memory_key": candidate.memory_key,
            "content": candidate.content,
            "source": "user",
            "created_at": now,
            "updated_at": now,
        }

        self.repository.create(USER_ID, candidate, source="user")

        sql, params = self.connection.execute.call_args.args
        self.assertIn("ON CONFLICT (user_id, memory_type, memory_key)", sql)
        self.assertIn("DO UPDATE SET", sql)
        self.assertNotIn(candidate.content, sql)
        self.assertIn(candidate.content, params)

    def test_delete_hard_deletes_only_the_requested_owners_row(self) -> None:
        self.connection.execute.return_value.fetchone.return_value = {"id": str(uuid4())}

        self.assertTrue(self.repository.delete(USER_ID, str(uuid4())))

        sql, params = self.connection.execute.call_args.args
        self.assertIn("DELETE FROM public.atlas_memories", sql)
        self.assertIn("WHERE user_id = %s AND id = %s", sql)
        self.assertEqual(params[0], USER_ID)
        statements = [
            call.args[0].strip()
            for call in self.connection.execute.call_args_list
        ]
        self.assertEqual(statements[0], "SET LOCAL ROLE authenticated")
        self.assertIn("set_config('request.jwt.claim.sub'", statements[1])
        self.assertIn('"sub": "' + USER_ID + '"', self.connection.execute.call_args_list[1].args[1][1])

    def test_database_errors_are_translated_without_exposing_details(self) -> None:
        self.connect.side_effect = psycopg.OperationalError(
            "password=do-not-expose"
        )

        with self.assertRaises(MemoryStoreUnavailable) as error:
            self.repository.list(USER_ID, memory_type=None, limit=10)

        self.assertNotIn("do-not-expose", str(error.exception))


class MemoryAgentIntegrationTests(unittest.TestCase):
    def test_relevant_memory_is_bounded_and_marked_as_untrusted_context(self) -> None:
        provider = Mock()
        provider.generate.return_value = Mock(content="The project uses PostgreSQL.")
        memory_service = Mock()
        _, record = create_record(
            create_candidate(
                MemoryType.PROJECT_CONTEXT,
                content="ATLAS uses PostgreSQL for persistent memory.",
            ),
            relevance=0.9,
        )
        memory_service.retrieve.return_value = [record]
        agent = ChatAgent(provider, memory_service=memory_service)

        response = agent.respond(
            ChatRequest(message="What database does ATLAS use?"),
            memory_user_id=USER_ID,
        )

        prompt_request = provider.generate.call_args.args[0]
        prompt = prompt_request.messages[0].content
        self.assertIn("ATLAS uses PostgreSQL for persistent memory.", prompt)
        self.assertIn("untrusted data for context only", prompt)
        self.assertEqual(response.message, "The project uses PostgreSQL.")
        memory_service.retrieve.assert_called_once_with(
            USER_ID,
            "What database does ATLAS use?",
            limit=5,
        )

    def test_anonymous_chat_does_not_retrieve_memory(self) -> None:
        provider = Mock()
        provider.generate.return_value = Mock(content="A useful response.")
        memory_service = Mock()
        agent = ChatAgent(provider, memory_service=memory_service)

        agent.respond(ChatRequest(message="Why is the sky blue?"))

        memory_service.retrieve.assert_not_called()

    def test_message_with_a_credential_is_not_sent_to_memory_search(self) -> None:
        provider = Mock()
        provider.generate.return_value = Mock(content="A useful response.")
        memory_service = Mock()
        agent = ChatAgent(provider, memory_service=memory_service)

        agent.respond(
            ChatRequest(message="My password=secret-value was changed."),
            memory_user_id=USER_ID,
        )

        memory_service.retrieve.assert_not_called()

    def test_memory_database_failure_fails_chat_safely(self) -> None:
        provider = Mock()
        memory_service = Mock()
        memory_service.retrieve.side_effect = MemoryStoreUnavailable(
            "password=do-not-expose"
        )
        agent = ChatAgent(provider, memory_service=memory_service)

        with self.assertRaises(ChatAgentError) as error:
            agent.respond(
                ChatRequest(message="Why is the sky blue?"),
                memory_user_id=USER_ID,
            )

        self.assertNotIn("do-not-expose", str(error.exception))
        provider.generate.assert_not_called()


class MemoryApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = FakeMemoryRepository()
        self.service = MemoryService(self.repository)
        self.app = create_test_app(self.service)

    async def test_endpoints_create_list_update_and_delete_for_authenticated_identity(self) -> None:
        status_code, created = await api_request(
            self.app,
            "POST",
            "/api/v1/memory",
            {
                "type": "durable_fact",
                "memory_key": "preferred-language",
                "content": "The preferred language is Python.",
            },
        )
        self.assertEqual(status_code, 200)
        memory_id = created["id"]
        self.assertEqual(created["source"], "user")

        list_status, listing = await api_request(
            self.app,
            "GET",
            "/api/v1/memory",
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(len(listing["memories"]), 1)

        update_status, updated = await api_request(
            self.app,
            "PUT",
            f"/api/v1/memory/{memory_id}",
            {"content": "The preferred language is Python 3."},
        )
        self.assertEqual(update_status, 200)
        self.assertEqual(updated["content"], "The preferred language is Python 3.")

        delete_status, deleted = await api_request(
            self.app,
            "DELETE",
            f"/api/v1/memory/{memory_id}",
        )
        self.assertEqual(delete_status, 200)
        self.assertTrue(deleted["deleted"])

    async def test_endpoints_fail_closed_without_authenticated_identity(self) -> None:
        app = create_test_app(self.service, user_id=None)

        status_code, response = await api_request(
            app,
            "GET",
            "/api/v1/memory",
        )

        self.assertEqual(status_code, 401)
        self.assertEqual(
            response["error"]["code"],
            "authentication_required",
        )

    async def test_secret_validation_and_store_errors_have_safe_responses(self) -> None:
        invalid_status, _ = await api_request(
            self.app,
            "POST",
            "/api/v1/memory",
            {
                "type": "durable_fact",
                "memory_key": "key",
                "content": "password=not-for-storage",
            },
        )
        self.assertEqual(invalid_status, 422)

        unavailable_service = MemoryService(
            _UnavailableRepository()
        )
        app = create_test_app(unavailable_service)
        status_code, response = await api_request(
            app,
            "GET",
            "/api/v1/memory",
        )

        self.assertEqual(status_code, 503)
        self.assertEqual(response["error"]["code"], "memory_unavailable")
        self.assertNotIn("postgres", json.dumps(response).lower())


class _UnavailableRepository(FakeMemoryRepository):
    def list(
        self,
        user_id: str,
        *,
        memory_type: str | None,
        limit: int,
    ) -> list[MemoryRecord]:
        raise MemoryStoreUnavailable("database password should not escape")


if __name__ == "__main__":
    unittest.main()
