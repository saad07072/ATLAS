from uuid import UUID
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.v1.github import router as github_router
from backend.app.api.v1.google import router as google_router
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.runtime import get_github_authentication
from backend.app.integrations.google.oauth import GoogleOAuthService
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
        self.oauth.connection_status.return_value = (True, True)
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

    def test_google_oauth_start_and_callback_are_disabled_for_every_user(self) -> None:
        with TestClient(self.app) as client:
            for user_token in ("user-a-token", "user-b-token"):
                response = client.get(
                    "/api/v1/google/oauth/start",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "integration_ownership_unavailable",
                )

            callback = client.get(
                "/api/v1/google/oauth/callback",
                params={"code": "authorization-code", "state": "shared-state"},
            )

        self.assertEqual(callback.status_code, 503)
        self.oauth.authorization_url.assert_not_called()
        self.oauth.handle_callback.assert_not_called()

    def test_status_does_not_report_shared_credentials_as_user_connections(self) -> None:
        with TestClient(self.app) as client:
            for user_token in ("user-a-token", "user-b-token"):
                headers = {"Authorization": f"Bearer {user_token}"}
                google = client.get("/api/v1/google/status", headers=headers)
                github = client.get("/api/v1/github/status", headers=headers)

                self.assertEqual(
                    google.json(),
                    {
                        "configured": True,
                        "connected": False,
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

        self.oauth.connection_status.assert_not_called()

    def test_google_oauth_start_still_requires_authentication(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/api/v1/google/oauth/start")

        self.assertEqual(response.status_code, 401)
        self.oauth.authorization_url.assert_not_called()

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
        self.oauth.authorization_url.assert_not_called()


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
