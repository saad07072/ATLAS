from __future__ import annotations

import asyncio
from uuid import UUID
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from backend.app.api.v1.github import router as github_router
from backend.app.api.v1.google import router as google_router
from backend.app.config.settings import Settings
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.exceptions import ApplicationError
from backend.app.main import redact_google_oauth_callback_query
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.github.runtime import get_github_authentication
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.oauth import (
    GoogleOAuthAuthorization,
)
from backend.app.integrations.google.runtime import get_google_oauth_service
from backend.app.security.identity import get_access_token_verifier
from backend.app.security.identity import SupabaseAccessTokenVerifier
from backend.app.tools.models import ToolExecutionRequest

USER_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class IntegrationOwnershipApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.oauth = Mock(spec=GoogleOAuthService)
        self.oauth.configured = True
        self.oauth.settings = Settings(
            _env_file=None,
            google_oauth_redirect_uri="http://127.0.0.1:8001/api/v1/google/oauth/callback",
        )
        self.oauth.authorization_request.side_effect = lambda user_id: (
            GoogleOAuthAuthorization(
                "https://accounts.google.com/",
                "state-a" if user_id == str(USER_A) else "state-b",
                "binding-a" if user_id == str(USER_A) else "binding-b",
            )
        )
        self.oauth.handle_callback.return_value = str(USER_A)
        self.authentication = Mock(spec=GitHubAppAuthentication)
        self.authentication.configured = True
        self.verifier = Mock(spec=SupabaseAccessTokenVerifier)
        self.verifier.verify.side_effect = {
            "user-a-token": USER_A,
            "user-b-token": USER_B,
        }.__getitem__

        self.app = FastAPI()
        register_exception_handlers(self.app)
        self.app.include_router(google_router, prefix="/api/v1")
        self.app.include_router(github_router, prefix="/api/v1")
        self.app.dependency_overrides[get_access_token_verifier] = (
            lambda: self.verifier
        )
        self.app.dependency_overrides[get_google_oauth_service] = (
            lambda: self.oauth
        )
        self.app.dependency_overrides[get_github_authentication] = (
            lambda: self.authentication
        )

    def test_google_callback_query_is_removed_before_server_access_logging(self) -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/v1/google/oauth/callback",
            "raw_path": b"/api/v1/google/oauth/callback",
            "query_string": b"code=authorization-secret&state=opaque-state",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8001),
        }
        request = Request(scope)

        async def call_next(_request: Request) -> Response:
            return Response()

        asyncio.run(redact_google_oauth_callback_query(request, call_next))

        self.assertEqual(scope["query_string"], b"")

    def test_google_oauth_start_is_authenticated_and_callback_is_safe(self) -> None:
        with TestClient(self.app) as client:
            for user_token in ("user-a-token", "user-b-token"):
                response = client.get(
                    "/api/v1/google/oauth/start",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                self.assertEqual(response.status_code, 200)

            callback = client.get(
                "/api/v1/google/oauth/callback",
                params={"code": "authorization-code", "state": "state-a"},
            )

        self.assertEqual(callback.status_code, 200)
        self.assertEqual(
            self.oauth.authorization_request.call_args_list,
            [((str(USER_A),),), ((str(USER_B),),)],
        )
        self.oauth.handle_callback.assert_called_once_with(
            code="authorization-code",
            state="state-a",
            browser_binding="binding-a",
            provider_error=None,
        )

    def test_status_is_scoped_to_each_authenticated_user(self) -> None:
        self.oauth.connection_status.side_effect = lambda user_id: (
            True,
            user_id == str(USER_A),
        )
        with TestClient(self.app) as client:
            for user_token in ("user-a-token", "user-b-token"):
                headers = {"Authorization": f"Bearer {user_token}"}
                google = client.get("/api/v1/google/status", headers=headers)
                github = client.get("/api/v1/github/status", headers=headers)

                self.assertEqual(
                    google.json(),
                    {
                        "configured": True,
                        "connected": user_token == "user-a-token",
                        "actions_enabled": False,
                    },
                )
                self.assertEqual(
                    github.json(),
                    {
                        "configured": True,
                        "connected": False,
                        "actions_enabled": False,
                    },
                )

        self.assertEqual(
            self.oauth.connection_status.call_args_list,
            [((str(USER_A),),), ((str(USER_B),),)],
        )

    def test_google_oauth_start_still_requires_authentication(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/api/v1/google/oauth/start")

        self.assertEqual(response.status_code, 401)
        self.oauth.authorization_request.assert_not_called()

    def test_google_oauth_callback_rejects_wrong_browser_cookie(self) -> None:
        self.oauth.handle_callback.side_effect = GoogleIntegrationError(
            "invalid_oauth_state",
            "Google authorization could not be validated. Please try again.",
        )
        with TestClient(self.app) as client:
            start = client.get(
                "/api/v1/google/oauth/start",
                headers={"Authorization": "Bearer " + "user-a-token"},
            )
            client.cookies.clear()
            callback = client.get(
                "/api/v1/google/oauth/callback",
                params={"code": "authorization-code", "state": "state-a"},
                cookies={"unrelated-cookie": "binding-a"},
            )

        self.assertEqual(start.status_code, 200)
        self.assertEqual(callback.status_code, 400)
        self.assertEqual(
            callback.json()["error"]["code"],
            "invalid_oauth_state",
        )
        self.oauth.handle_callback.assert_called_once_with(
            code="authorization-code",
            state="state-a",
            browser_binding=None,
            provider_error=None,
        )

    def test_google_disconnect_is_authenticated_and_uses_verified_subject(self) -> None:
        with TestClient(self.app) as client:
            response = client.delete(
                "/api/v1/google/connection",
                headers={"Authorization": "Bearer " + "user-a-token"},
            )
            unauthenticated = client.delete("/api/v1/google/connection")

        self.assertEqual(response.status_code, 200)
        self.oauth.disconnect.assert_called_once_with(str(USER_A))
        self.assertEqual(unauthenticated.status_code, 401)

    def test_bad_test_token_fails_authentication_closed(self) -> None:
        self.verifier.verify.side_effect = ApplicationError(
            "The access token is missing, invalid, or expired.",
            code="invalid_authentication",
            status_code=401,
        )
        with TestClient(self.app) as client:
            response = client.get(
                "/api/v1/google/oauth/start",
                headers={"Authorization": "Bearer invalid-token"},
            )

        self.assertEqual(response.status_code, 401)
        self.oauth.authorization_request.assert_not_called()


class SharedIntegrationToolRuntimeTests(unittest.TestCase):
    def test_standard_executors_do_not_register_shared_integration_actions(self) -> None:
        from backend.app.integrations.github.runtime import get_tool_executor
        from backend.app.integrations.google.runtime import get_google_tool_executor

        for executor in (get_tool_executor(), get_google_tool_executor()):
            self.assertEqual(executor.registry.list_tools(), [])
            for name in ("github.create_issue", "gmail.send", "calendar.delete_event"):
                with self.subTest(tool=name):
                    result = executor.execute(
                        ToolExecutionRequest(name=name, arguments={})
                    )
                    self.assertFalse(result.success)
                    self.assertEqual(result.error.code, "unknown_tool")
                    self.assertEqual(
                        result.authorization.decision.value,
                        "deny",
                    )


if __name__ == "__main__":
    unittest.main()
