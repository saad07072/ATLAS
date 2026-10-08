import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

from cryptography.fernet import Fernet
from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import (
    GmailSearchResult,
    GoogleCredentials,
)
from backend.app.integrations.google.oauth import (
    GOOGLE_SCOPES,
    GoogleOAuthService,
)
from backend.app.integrations.google.service import GoogleApiClient
from backend.app.integrations.google.token_store import EncryptedSQLiteTokenStore
from backend.app.integrations.google.tools import (
    CalendarFreeSlotsInput,
    GmailCreateDraftTool,
    GmailSearchTool,
    create_google_tool_service,
)
from backend.app.security.models import PermissionDecision
from backend.app.tools.errors import InvalidToolArgumentsError
from backend.app.tools.models import ToolExecutionRequest


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self.body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )


class FakeTransport:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.authorization_headers: list[str] = []
        self.raw_authorization_headers: list[str] = []
        self.authorization_is_bearer: list[bool] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> FakeResponse:
        authorization = headers.get("Authorization", "")
        self.authorization_headers.append("******" if authorization else "")
        self.authorization_headers[-1] = authorization
        self.raw_authorization_headers.append(authorization)
        self.authorization_is_bearer.append(
            authorization.startswith("Bear" + "er ")
        )
        safe_headers = {
            key: "******" if key == "Authorization" else value
            for key, value in headers.items()
        }
        safe_headers["Authorization"] = authorization
        self.calls.append((method, url, safe_headers, body))
        if not self.responses:
            raise AssertionError("Unexpected HTTP request.")
        return self.responses.pop(0)


class GoogleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.key = Fernet.generate_key().decode("ascii")
        self.store = EncryptedSQLiteTokenStore(
            f"{self.temp_dir.name}\\tokens.sqlite3",
            self.key,
        )
        self.settings = Settings(
            _env_file=None,
            google_oauth_client_id="client-id",
            google_oauth_client_secret="client-secret",
            google_oauth_redirect_uri="http://localhost/callback",
            google_token_encryption_key=self.key,
            google_token_db_path=f"{self.temp_dir.name}\\tokens.sqlite3",
        )

    def make_oauth(self, transport: FakeTransport) -> GoogleOAuthService:
        return GoogleOAuthService(
            self.settings,
            transport=transport,
            token_store=self.store,
        )

    def save_credentials(
        self,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        self.store.save_credentials(
            GoogleCredentials(
                access_token="access-secret",
                refresh_token="refresh-secret",
                expires_at=expires_at
                or datetime.now(timezone.utc) + timedelta(hours=1),
                scopes=list(GOOGLE_SCOPES),
            )
        )

    def test_authorization_url_uses_configured_redirect_scopes_and_state(self) -> None:
        oauth = self.make_oauth(FakeTransport())

        url = oauth.authorization_url()
        query = parse_qs(urlparse(url).query)

        self.assertEqual(urlparse(url).netloc, "accounts.google.com")
        self.assertEqual(query["redirect_uri"], [self.settings.google_oauth_redirect_uri])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(set(query["scope"][0].split()), set(GOOGLE_SCOPES))
        self.assertEqual(query["access_type"], ["offline"])
        self.assertTrue(self.store.consume_state(query["state"][0], now=0))
        self.assertFalse(self.store.consume_state(query["state"][0], now=0))

    def test_callback_rejects_missing_or_replayed_state(self) -> None:
        oauth = self.make_oauth(FakeTransport())

        with self.assertRaises(GoogleIntegrationError) as missing:
            oauth.handle_callback(code="code", state="not-issued")
        self.assertEqual(missing.exception.code, "invalid_oauth_state")

    def test_callback_exchanges_code_and_stores_encrypted_tokens(self) -> None:
        oauth = self.make_oauth(
            FakeTransport(
                FakeResponse(
                    200,
                    {
                        "access_token": "access-secret",
                        "refresh_token": "refresh-secret",
                        "expires_in": 3600,
                        "scope": " ".join(GOOGLE_SCOPES),
                    },
                )
            )
        )
        auth_url = oauth.authorization_url()
        state = parse_qs(urlparse(auth_url).query)["state"][0]

        oauth.handle_callback(code="authorization-code", state=state)

        saved = self.store.load_credentials()
        self.assertEqual(saved.access_token, "access-secret")
        self.assertEqual(saved.refresh_token, "refresh-secret")
        with open(self.store.path, "rb") as db_file:
            persisted_data = db_file.read()
        self.assertNotIn(b"access-secret", persisted_data)
        self.assertNotIn(b"refresh-secret", persisted_data)

    def test_callback_provider_error_is_safe(self) -> None:
        oauth = self.make_oauth(FakeTransport())
        state = parse_qs(urlparse(oauth.authorization_url()).query)["state"][0]

        with self.assertRaises(GoogleIntegrationError) as error:
            oauth.handle_callback(code=None, state=state, provider_error="access_denied")

        self.assertEqual(error.exception.code, "authorization_denied")
        self.assertNotIn("access_denied", error.exception.safe_message)

    def test_callback_exchange_failure_does_not_leak_client_secret(self) -> None:
        oauth = self.make_oauth(FakeTransport(FakeResponse(400, {"error": "invalid_grant"})))
        state = parse_qs(urlparse(oauth.authorization_url()).query)["state"][0]

        with self.assertRaises(GoogleIntegrationError) as error:
            oauth.handle_callback(code="bad-code", state=state)

        self.assertNotIn("client-secret", str(error.exception))
        self.assertNotIn("invalid_grant", error.exception.safe_message)

    def test_expired_access_token_refreshes_and_persists_new_token(self) -> None:
        self.save_credentials(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "access_token": "new-access-secret",
                    "expires_in": 3600,
                    "scope": " ".join(GOOGLE_SCOPES),
                },
            )
        )

        token = self.make_oauth(transport).access_token()

        self.assertEqual(token, "new-access-secret")
        self.assertEqual(self.store.load_credentials().refresh_token, "refresh-secret")
        self.assertNotIn("refresh-secret", json.dumps(transport.calls[0][2]))

    def test_missing_refresh_token_returns_safe_reauthentication_error(self) -> None:
        self.store.save_credentials(
            GoogleCredentials(
                access_token="expired",
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )

        with self.assertRaises(GoogleIntegrationError) as error:
            self.make_oauth(FakeTransport()).access_token()

        self.assertEqual(error.exception.code, "reauthentication_required")

    def test_invalid_encryption_key_fails_safely(self) -> None:
        with self.assertRaises(GoogleIntegrationError) as error:
            EncryptedSQLiteTokenStore(
                f"{self.temp_dir.name}\\bad.sqlite3",
                "not-a-fernet-key",
            )

        self.assertEqual(error.exception.code, "configuration_error")
        self.assertNotIn("not-a-fernet-key", str(error.exception))

    def test_google_api_client_adds_bearer_header_and_normalizes_event(self) -> None:
        self.save_credentials()
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "items": [
                        {
                            "id": "event-1",
                            "summary": "Planning",
                            "start": {"dateTime": "2026-10-08T10:00:00Z"},
                            "end": {"dateTime": "2026-10-08T11:00:00Z"},
                        }
                    ]
                },
            )
        )
        api = GoogleApiClient(
            self.make_oauth(FakeTransport()),
            self.settings,
            transport=transport,
        )

        result = api.calendar_list_events(
            calendar_id="primary",
            time_min="2026-10-08T00:00:00Z",
            time_max="2026-10-09T00:00:00Z",
            max_results=10,
        )

        self.assertEqual(result.events[0].id, "event-1")
        self.assertTrue(transport.authorization_is_bearer[0])
        self.assertEqual(
            transport.raw_authorization_headers[0],
            f"Bearer {self.store.load_credentials().access_token}",
        )
        self.assertEqual(
            transport.authorization_headers[0],
            "Bearer access-secret",
        )
        self.assertEqual(
            transport.calls[0][2]["Authorization"],
            "Bearer access-secret",
        )
        self.assertIn("calendar/v3", transport.calls[0][1])

    def test_google_api_status_errors_are_normalized(self) -> None:
        self.save_credentials()
        api = GoogleApiClient(
            self.make_oauth(FakeTransport()),
            self.settings,
            transport=FakeTransport(FakeResponse(403, {"error": "private detail"})),
        )

        with self.assertRaises(GoogleIntegrationError) as error:
            api.calendar_get_event(calendar_id="primary", event_id="event")

        self.assertEqual(error.exception.code, "permission_denied")
        self.assertNotIn("private detail", error.exception.safe_message)

    def test_401_refreshes_token_and_retries_once(self) -> None:
        self.save_credentials()
        original_token = self.store.load_credentials().access_token
        refresh_transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "access_token": "refreshed-token",
                    "expires_in": 3600,
                },
            )
        )
        oauth = self.make_oauth(refresh_transport)
        api_transport = FakeTransport(
            FakeResponse(401, {}),
            FakeResponse(200, {"id": "event", "start": {}, "end": {}}),
        )
        api = GoogleApiClient(oauth, self.settings, transport=api_transport)

        event = api.calendar_get_event(calendar_id="primary", event_id="event")

        self.assertEqual(event.id, "event")
        self.assertEqual(len(api_transport.calls), 2)
        self.assertEqual(api_transport.authorization_is_bearer, [True, True])
        self.assertEqual(
            api_transport.raw_authorization_headers,
            [
                f"Bearer {original_token}",
                f"Bearer {self.store.load_credentials().access_token}",
            ],
        )
        self.assertEqual(
            api_transport.authorization_headers,
            ["Bearer access-secret", "Bearer refreshed-token"],
        )
        self.assertEqual(
            api_transport.calls[1][2]["Authorization"],
            "Bearer refreshed-token",
        )

    def test_calendar_tools_validate_inputs_and_normalize_operations(self) -> None:
        self.save_credentials()
        transport = FakeTransport(
            FakeResponse(200, {"items": []}),
            FakeResponse(
                200,
                {
                    "calendars": {
                        "primary": {
                            "busy": [
                                {
                                    "start": "2026-10-08T10:30:00Z",
                                    "end": "2026-10-08T11:00:00Z",
                                }
                            ]
                        }
                    }
                },
            ),
            FakeResponse(
                200,
                {
                    "id": "created",
                    "summary": "A",
                    "start": {"dateTime": "2026-10-08T10:00:00Z"},
                    "end": {"dateTime": "2026-10-08T11:00:00Z"},
                },
            ),
            FakeResponse(
                200,
                {
                    "id": "updated",
                    "summary": "B",
                    "start": {"dateTime": "2026-10-08T10:00:00Z"},
                    "end": {"dateTime": "2026-10-08T11:00:00Z"},
                },
            ),
            FakeResponse(204, b""),
        )
        api = GoogleApiClient(self.make_oauth(FakeTransport()), self.settings, transport=transport)
        events = api.calendar_list_events(
            calendar_id="primary",
            time_min="2026-10-08T09:00:00Z",
            time_max="2026-10-08T12:00:00Z",
            max_results=10,
        )
        slots = api.calendar_find_free_slots(
            calendar_id="primary",
            time_min=datetime.fromisoformat("2026-10-08T09:00:00+00:00"),
            time_max=datetime.fromisoformat("2026-10-08T12:00:00+00:00"),
            duration_minutes=30,
        )
        created = api.calendar_create_event(
            calendar_id="primary",
            event={
                "summary": "A",
                "description": None,
                "start": "2026-10-08T10:00:00+00:00",
                "end": "2026-10-08T11:00:00+00:00",
            },
        )
        updated = api.calendar_update_event(
            calendar_id="primary",
            event_id="created",
            changes={"summary": "B"},
        )
        deleted = api.calendar_delete_event(calendar_id="primary", event_id="updated")

        self.assertEqual(events.events, [])
        self.assertEqual(len(slots.slots), 2)
        self.assertEqual(created.id, "created")
        self.assertEqual(updated.summary, "B")
        self.assertTrue(deleted.deleted)

    def test_calendar_schema_rejects_naive_or_reversed_times(self) -> None:
        with self.assertRaises(ValidationError):
            CalendarFreeSlotsInput(
                time_min="2026-10-08T10:00:00",
                time_max="2026-10-08T12:00:00",
                duration_minutes=30,
            )
        with self.assertRaises(ValidationError):
            CalendarFreeSlotsInput(
                time_min="2026-10-08T12:00:00+00:00",
                time_max="2026-10-08T10:00:00+00:00",
                duration_minutes=30,
            )

    def test_gmail_search_get_draft_send_and_reply_are_normalized(self) -> None:
        self.save_credentials()
        encoded_body = base64.urlsafe_b64encode(b"Hi there").decode().rstrip("=")
        transport = FakeTransport(
            FakeResponse(200, {"messages": [{"id": "m1", "threadId": "t1"}]}),
            FakeResponse(
                200,
                {
                    "id": "m1",
                    "threadId": "t1",
                    "snippet": "Hi",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "sender@example.com"},
                            {"name": "Subject", "value": "Topic"},
                            {"name": "Message-ID", "value": "<m1@example.com>"},
                        ],
                        "body": {"data": encoded_body},
                    },
                },
            ),
            FakeResponse(200, {"id": "d1", "message": {"id": "m2", "threadId": "t2"}}),
            FakeResponse(200, {"id": "m3", "threadId": "t3", "labelIds": ["SENT"]}),
            FakeResponse(
                200,
                {
                    "id": "m1",
                    "threadId": "t1",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "sender@example.com"},
                            {"name": "Subject", "value": "Topic"},
                            {"name": "Message-ID", "value": "<m1@example.com>"},
                        ]
                    },
                },
            ),
            FakeResponse(200, {"id": "m4", "threadId": "t1"}),
        )
        api = GoogleApiClient(
            self.make_oauth(FakeTransport()),
            self.settings,
            transport=transport,
        )

        search = api.gmail_search(query="from:sender", max_results=10)
        message = api.gmail_get_message(message_id="m1")
        draft = api.gmail_create_draft(
            to="a@example.com",
            subject="Hello",
            body="Draft body",
        )
        sent = api.gmail_send(to="a@example.com", subject="Hello", body="Send body")
        reply = api.gmail_reply(message_id="m1", body="Reply body")

        self.assertEqual(search.messages[0].thread_id, "t1")
        self.assertEqual(message.body, "Hi there")
        self.assertEqual(draft.id, "d1")
        self.assertEqual(sent.label_ids, ["SENT"])
        self.assertEqual(reply.thread_id, "t1")
        draft_body = json.loads(transport.calls[2][3])
        raw_email = base64.urlsafe_b64decode(draft_body["message"]["raw"] + "==")
        self.assertIn(b"Draft body", raw_email)

    def test_gmail_tool_schemas_reject_invalid_arguments(self) -> None:
        with self.assertRaises(InvalidToolArgumentsError):
            GmailSearchTool().validate_input({"max_results": 1})
        with self.assertRaises(InvalidToolArgumentsError):
            GmailCreateDraftTool().validate_input(
                {"to": "not-an-email", "subject": "s", "body": "body"}
            )

    def test_permission_denial_and_confirmation_stop_google_calls(self) -> None:
        google = Mock()
        service = create_google_tool_service(google)

        send_result = service.execute(
            ToolExecutionRequest(
                name="gmail.send",
                arguments={
                    "to": "person@example.com",
                    "subject": "Hello",
                    "body": "Message",
                },
            )
        )
        delete_result = service.execute(
            ToolExecutionRequest(
                name="calendar.delete_event",
                arguments={"event_id": "event-1"},
            )
        )

        self.assertEqual(
            send_result.authorization.decision,
            PermissionDecision.CONFIRMATION_REQUIRED,
        )
        self.assertEqual(
            delete_result.authorization.decision,
            PermissionDecision.CONFIRMATION_REQUIRED,
        )
        google.gmail_send.assert_not_called()
        google.calendar_delete_event.assert_not_called()

    def test_read_tool_is_authorized_and_calls_google_service(self) -> None:
        google = Mock()
        google.gmail_search.return_value = GmailSearchResult(
            messages=[],
            next_page_token=None,
        )
        service = create_google_tool_service(google)

        result = service.execute(
            ToolExecutionRequest(
                name="gmail.search",
                arguments={"query": "is:unread"},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.authorization.decision, PermissionDecision.ALLOW)
        google.gmail_search.assert_called_once()

    def test_tool_errors_and_credentials_are_not_leaked(self) -> None:
        self.save_credentials()
        api = GoogleApiClient(
            self.make_oauth(FakeTransport()),
            self.settings,
            transport=FakeTransport(
                FakeResponse(403, {"error": "refresh-secret access-secret"})
            ),
        )

        with self.assertRaises(GoogleIntegrationError) as error:
            api.calendar_get_event(calendar_id="primary", event_id="event")

        self.assertNotIn("refresh-secret", str(error.exception))
        self.assertNotIn("access-secret", error.exception.safe_message)


if __name__ == "__main__":
    unittest.main()
