from __future__ import annotations

import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.errors import GitHubIntegrationError
from backend.app.integrations.github.models import (
    GitHubIssue,
    GitHubIssueCreated,
    GitHubIssueList,
    GitHubPullRequest,
    GitHubRepository,
    GitHubRepositoryList,
)
from backend.app.integrations.github.service import GitHubApiClient
from backend.app.integrations.github.tools import (
    CreateIssueInput,
    CreateIssueTool,
    GetRepositoryTool,
    IssueListInput,
    RepositoryInput,
    create_github_tools,
)
from backend.app.security.models import (
    PermissionDecision,
    PermissionId,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.factory import create_tool_execution_service
from backend.app.tools.models import ToolExecutionRequest
from backend.app.tools.registry import ToolRegistry
from backend.app.integrations.github.transport import HttpResponse


class FakeTransport:
    def __init__(self, *responses: HttpResponse | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.calls.append((method, url, dict(headers), body, timeout))
        if not self.responses:
            raise AssertionError("Unexpected HTTP request.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(
    status: int,
    payload: object,
    *,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return HttpResponse(status, body, headers or {})


def valid_repository_payload() -> dict[str, object]:
    return {
        "id": 10,
        "name": "atlas",
        "full_name": "owner/atlas",
        "owner": {"login": "owner"},
        "private": True,
        "html_url": "https://github.com/owner/atlas",
        "description": None,
        "default_branch": "main",
        "permissions": {"push": True},
    }


def valid_issue_payload() -> dict[str, object]:
    return {
        "number": 7,
        "title": "Bug",
        "body": "Details",
        "state": "open",
        "html_url": "https://github.com/owner/atlas/issues/7",
        "user": {"login": "contributor"},
        "labels": [],
    }


class GitHubIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.private_key_pem = self.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        self.settings = Settings(
            _env_file=None,
            github_app_id="12345",
            github_installation_id="67890",
            github_private_key=self.private_key_pem,
            github_api_timeout_seconds=2.5,
        )

    def make_auth(
        self,
        transport: FakeTransport,
    ) -> GitHubAppAuthentication:
        return GitHubAppAuthentication(self.settings, transport=transport)

    @staticmethod
    def token_response(
        token: str = "installation-token",
        *,
        expires_at: datetime | None = None,
    ) -> HttpResponse:
        return response(
            201,
            {
                "token": token,
                "expires_at": (
                    expires_at or datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat(),
                "permissions": {"issues": "write"},
            },
        )

    def make_client(
        self,
        api_transport: FakeTransport,
    ) -> GitHubApiClient:
        auth = self.make_auth(FakeTransport(self.token_response()))
        return GitHubApiClient(
            auth,
            self.settings,
            transport=api_transport,
        )

    def test_valid_configuration_creates_verifiable_app_jwt(self) -> None:
        auth = self.make_auth(FakeTransport())
        fixed_time = 1_800_000_000

        token = auth.create_app_jwt(now=fixed_time)
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        header = json.loads(self._decode_segment(encoded_header))
        claims = json.loads(self._decode_segment(encoded_payload))
        self.private_key.public_key().verify(
            self._decode_segment(encoded_signature),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

        self.assertEqual(header, {"alg": "RS256", "typ": "JWT"})
        self.assertEqual(claims["iss"], "12345")
        self.assertEqual(claims["iat"], fixed_time - 60)
        self.assertEqual(claims["exp"], fixed_time + 540)
        self.assertNotIn(self.private_key_pem, token)
        self.assertNotIn(self.private_key_pem, repr(self.settings))

    def test_missing_installation_id_fails_safely_without_http(self) -> None:
        settings = self.settings.model_copy(update={"github_installation_id": None})
        transport = FakeTransport()
        auth = GitHubAppAuthentication(settings, transport=transport)

        with self.assertRaises(GitHubIntegrationError) as error:
            auth.installation_token()

        self.assertEqual(error.exception.code, "configuration_error")
        self.assertIn("installation ID", error.exception.safe_message)
        self.assertEqual(transport.calls, [])
        self.assertNotIn(self.private_key_pem, str(error.exception))

    def test_invalid_private_key_fails_without_leaking_key(self) -> None:
        settings = self.settings.model_copy(
            update={"github_private_key": "not-a-private-key"}
        )
        auth = GitHubAppAuthentication(settings, transport=FakeTransport())

        with self.assertRaises(GitHubIntegrationError) as error:
            auth.create_app_jwt()

        self.assertEqual(error.exception.code, "configuration_error")
        self.assertNotIn("not-a-private-key", str(error.exception))

    def test_installation_token_is_cached_until_expiration_leeway(self) -> None:
        transport = FakeTransport(
            self.token_response("token-one"),
            self.token_response("token-two"),
        )
        auth = self.make_auth(transport)

        self.assertEqual(auth.installation_token(), "token-one")
        self.assertEqual(auth.installation_token(), "token-one")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(
            transport.calls[0][1],
            "https://api.github.com/app/installations/67890/access_tokens",
        )
        self.assertEqual(transport.calls[0][0], "POST")
        self.assertTrue(
            transport.calls[0][2]["Authorization"].startswith("Bearer ")
        )

        auth._cached_token.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=30
        )
        self.assertEqual(auth.installation_token(), "token-two")
        self.assertEqual(len(transport.calls), 2)

    def test_expired_token_response_is_not_cached_or_returned(self) -> None:
        transport = FakeTransport(
            self.token_response(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
            )
        )
        auth = self.make_auth(transport)

        with self.assertRaises(GitHubIntegrationError) as error:
            auth.installation_token()

        self.assertEqual(error.exception.code, "invalid_authentication_response")
        self.assertNotIn("installation-token", str(error.exception))

    def test_token_endpoint_error_does_not_expose_auth_material(self) -> None:
        transport = FakeTransport(
            response(401, {"message": "installation-token invalid"}),
        )
        auth = self.make_auth(transport)

        with self.assertRaises(GitHubIntegrationError) as error:
            auth.installation_token()

        self.assertEqual(error.exception.code, "authentication_failed")
        self.assertNotIn("installation-token", str(error.exception))
        self.assertNotIn(self.private_key_pem, str(error.exception))

    def test_list_repositories_normalizes_payload_and_pagination(self) -> None:
        transport = FakeTransport(
            response(
                200,
                {"repositories": [valid_repository_payload()]},
                headers={
                    "Link": (
                        '<https://api.github.com/installation/repositories'
                        '?page=3&per_page=1>; rel="next"'
                    )
                },
            )
        )

        result = self.make_client(transport).list_repositories(page=2, per_page=1)

        self.assertEqual(
            result,
            GitHubRepositoryList(
                repositories=[
                    GitHubRepository(
                        id=10,
                        name="atlas",
                        full_name="owner/atlas",
                        owner="owner",
                        private=True,
                        html_url="https://github.com/owner/atlas",
                        description=None,
                        default_branch="main",
                    )
                ],
                next_page=3,
            ),
        )
        self.assertIn("/installation/repositories?page=2&per_page=1", transport.calls[0][1])

    def test_get_repository_uses_only_encoded_internal_repository_route(self) -> None:
        transport = FakeTransport(response(200, valid_repository_payload()))

        result = self.make_client(transport).get_repository(owner="owner", repo="atlas")

        self.assertEqual(result.full_name, "owner/atlas")
        self.assertIn("/repos/owner/atlas", transport.calls[0][1])
        self.assertEqual(transport.calls[0][0], "GET")
        self.assertTrue(transport.calls[0][2]["Authorization"].startswith("Bearer "))

    def test_list_issues_excludes_pull_requests_and_uses_pagination(self) -> None:
        issue = valid_issue_payload()
        pull_request = {**issue, "number": 8, "pull_request": {"url": "ignored"}}
        transport = FakeTransport(
            response(
                200,
                [issue, pull_request],
                headers={
                    "Link": (
                        '<https://api.github.com/repos/owner/atlas/issues'
                        '?page=2&per_page=30>; rel="next"'
                    )
                },
            )
        )

        result = self.make_client(transport).list_issues(
            owner="owner",
            repo="atlas",
            page=1,
            per_page=30,
        )

        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].user, "contributor")
        self.assertEqual(result.next_page, 2)

    def test_get_pull_request_normalizes_nested_branch_data(self) -> None:
        payload = {
            **valid_issue_payload(),
            "draft": True,
            "merged": False,
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
        }
        transport = FakeTransport(response(200, payload))

        result = self.make_client(transport).get_pull_request(
            owner="owner",
            repo="atlas",
            number=7,
        )

        self.assertIsInstance(result, GitHubPullRequest)
        self.assertEqual(result.head, "feature")
        self.assertEqual(result.base, "main")

    def test_create_issue_posts_only_validated_issue_fields(self) -> None:
        created = {
            "number": 9,
            "title": "New issue",
            "html_url": "https://github.com/owner/atlas/issues/9",
            "state": "open",
        }
        transport = FakeTransport(response(201, created))

        result = self.make_client(transport).create_issue(
            owner="owner",
            repo="atlas",
            title="New issue",
            body="Details",
        )

        self.assertEqual(
            result,
            GitHubIssueCreated(
                number=9,
                title="New issue",
                html_url="https://github.com/owner/atlas/issues/9",
                state="open",
            ),
        )
        self.assertEqual(transport.calls[0][0], "POST")
        self.assertEqual(
            json.loads(transport.calls[0][3]),
            {"title": "New issue", "body": "Details"},
        )

    def test_response_errors_are_normalized_without_server_body(self) -> None:
        expected_codes = {
            401: "authentication_failed",
            403: "permission_denied",
            404: "not_found",
            409: "conflict",
            422: "validation_failed",
            429: "rate_limited",
        }
        for status, code in expected_codes.items():
            with self.subTest(status=status):
                client = self.make_client(
                    FakeTransport(response(status, {"message": "private response"}))
                )
                with self.assertRaises(GitHubIntegrationError) as error:
                    client.get_repository(owner="owner", repo="atlas")
                self.assertEqual(error.exception.code, code)
                self.assertNotIn("private response", str(error.exception))

    def test_forbidden_rate_limit_and_generic_api_errors_are_classified(self) -> None:
        cases = (
            (403, {"X-RateLimit-Remaining": "0"}, "rate_limited"),
            (500, {}, "github_api_error"),
        )
        for status, headers, code in cases:
            with self.subTest(status=status):
                api_responses = (
                    [response(status, {}, headers=headers) for _ in range(3)]
                    if status >= 500
                    else [response(status, {}, headers=headers)]
                )
                client = self.make_client(
                    FakeTransport(*api_responses)
                )
                with patch("backend.app.integrations.github.service.time.sleep"):
                    with self.assertRaises(GitHubIntegrationError) as error:
                        client.get_repository(owner="owner", repo="atlas")
                self.assertEqual(error.exception.code, code)

    def test_safe_get_retries_transient_response_but_not_write(self) -> None:
        transport = FakeTransport(
            response(503, {}),
            response(502, {}),
            response(200, valid_repository_payload()),
        )
        client = self.make_client(transport)
        with patch("backend.app.integrations.github.service.time.sleep"):
            self.assertEqual(
                client.get_repository(owner="owner", repo="atlas").name,
                "atlas",
            )
        self.assertEqual(len(transport.calls), 3)

        write_transport = FakeTransport(response(503, {}))
        with self.assertRaises(GitHubIntegrationError):
            self.make_client(write_transport).create_issue(
                owner="owner",
                repo="atlas",
                title="Issue",
                body=None,
            )
        self.assertEqual(len(write_transport.calls), 1)

    def test_network_timeout_is_normalized_and_retries_are_bounded(self) -> None:
        failure = GitHubIntegrationError("network_error", "safe network failure")
        transport = FakeTransport(failure, failure, failure)
        client = self.make_client(transport)

        with patch("backend.app.integrations.github.service.time.sleep"):
            with self.assertRaises(GitHubIntegrationError) as error:
                client.get_repository(owner="owner", repo="atlas")

        self.assertEqual(error.exception.code, "network_error")
        self.assertEqual(len(transport.calls), 3)
        self.assertNotIn("installation-token", str(error.exception))

    def test_invalid_github_response_is_safely_rejected(self) -> None:
        client = self.make_client(FakeTransport(response(200, {"not": "a repository"})))

        with self.assertRaises(GitHubIntegrationError) as error:
            client.get_repository(owner="owner", repo="atlas")

        self.assertEqual(error.exception.code, "invalid_response")
        self.assertNotIn("repository", error.exception.safe_message)

    def test_client_rejects_arbitrary_http_methods_and_paths(self) -> None:
        client = self.make_client(FakeTransport())

        for method, path in (
            ("DELETE", "/repos/owner/atlas/issues"),
            ("GET", "/app/installations/123/access_tokens"),
            ("POST", "/repos/owner/atlas/pulls"),
        ):
            with self.subTest(method=method, path=path):
                with self.assertRaises(GitHubIntegrationError) as error:
                    client._request(method, path)
                self.assertEqual(error.exception.code, "invalid_request")
    def test_input_schemas_reject_ambiguous_or_unbounded_values(self) -> None:
        invalid_repositories = (
            {"owner": "owner/repo", "repo": "atlas"},
            {"owner": "https://github.com", "repo": "atlas"},
            {"owner": "owner", "repo": "../atlas"},
            {"owner": "owner", "repo": "atlas", "url": "https://attacker.test"},
        )
        for arguments in invalid_repositories:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValidationError):
                    RepositoryInput.model_validate(arguments)

        with self.assertRaises(ValidationError):
            IssueListInput.model_validate(
                {"owner": "owner", "repo": "atlas", "per_page": 101}
            )
        with self.assertRaises(ValidationError):
            CreateIssueInput.model_validate(
                {"owner": "owner", "repo": "atlas", "title": "  "}
            )
        with self.assertRaises(ValidationError):
            CreateIssueInput.model_validate(
                {
                    "owner": "owner",
                    "repo": "atlas",
                    "title": "Issue",
                    "body": "x" * 65537,
                }
            )

    def test_github_tools_are_registered_with_fixed_permission_metadata(self) -> None:
        tools = create_github_tools(Mock())
        service = create_tool_execution_service(tools)
        metadata = {tool.name: tool for tool in service.registry.list_tools()}

        self.assertEqual(
            set(metadata),
            {
                "github.list_repositories",
                "github.get_repository",
                "github.list_issues",
                "github.get_pull_request",
                "github.create_issue",
            },
        )
        for name in set(metadata) - {"github.create_issue"}:
            self.assertEqual(metadata[name].permission_id, PermissionId.GITHUB_READ.value)
            self.assertEqual(metadata[name].risk_level, RiskLevel.LOW.value)
        self.assertEqual(
            metadata["github.create_issue"].permission_id,
            PermissionId.GITHUB_ISSUE_WRITE.value,
        )
        self.assertEqual(metadata["github.create_issue"].risk_level, "high")
        self.assertTrue(metadata["github.create_issue"].permission_required)

    def test_read_tools_execute_through_the_shared_permission_boundary(self) -> None:
        github = Mock()
        repository = GitHubRepository(
            id=10,
            name="atlas",
            full_name="owner/atlas",
            owner="owner",
            private=True,
            html_url="https://github.com/owner/atlas",
        )
        issue = GitHubIssue(
            number=7,
            title="Bug",
            body=None,
            state="open",
            html_url="https://github.com/owner/atlas/issues/7",
            user="contributor",
        )
        pull_request = GitHubPullRequest(
            number=8,
            title="Feature",
            body=None,
            state="open",
            html_url="https://github.com/owner/atlas/pull/8",
            draft=False,
            merged=False,
            head="feature",
            base="main",
        )
        github.list_repositories.return_value = GitHubRepositoryList(
            repositories=[repository]
        )
        github.get_repository.return_value = repository
        github.list_issues.return_value = GitHubIssueList(issues=[issue])
        github.get_pull_request.return_value = pull_request
        service = create_tool_execution_service(create_github_tools(github))
        requests = (
            ("github.list_repositories", {}, "repositories"),
            (
                "github.get_repository",
                {"owner": "owner", "repo": "atlas"},
                "full_name",
            ),
            (
                "github.list_issues",
                {"owner": "owner", "repo": "atlas"},
                "issues",
            ),
            (
                "github.get_pull_request",
                {"owner": "owner", "repo": "atlas", "number": 8},
                "head",
            ),
        )

        for name, arguments, output_key in requests:
            with self.subTest(tool=name):
                result = service.execute(
                    ToolExecutionRequest(name=name, arguments=arguments)
                )
                self.assertTrue(result.success)
                self.assertIn(output_key, result.output)

        github.list_repositories.assert_called_once()
        github.get_repository.assert_called_once()
        github.list_issues.assert_called_once()
        github.get_pull_request.assert_called_once()

    def test_denied_permission_never_calls_github(self) -> None:
        github = Mock()
        tool = GetRepositoryTool()
        tool.github = github
        registry = ToolRegistry()
        registry.register(tool)
        service = ToolExecutionService(
            registry,
            PermissionEngine(
                PermissionPolicy(
                    {
                        ("github.get_repository", PermissionId.GITHUB_READ): PermissionRule(
                            allowed=False,
                            risk_level=RiskLevel.LOW,
                        )
                    }
                )
            ),
        )

        result = service.execute(
            ToolExecutionRequest(
                name="github.get_repository",
                arguments={"owner": "owner", "repo": "atlas"},
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.authorization.decision, PermissionDecision.DENY)
        github.get_repository.assert_not_called()

    def test_issue_confirmation_required_never_calls_github(self) -> None:
        github = Mock()
        service = create_tool_execution_service(create_github_tools(github))

        result = service.execute(
            ToolExecutionRequest(
                name="github.create_issue",
                arguments={
                    "owner": "owner",
                    "repo": "atlas",
                    "title": "Issue",
                    "body": "Details",
                },
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "confirmation_required")
        self.assertEqual(
            result.authorization.decision,
            PermissionDecision.CONFIRMATION_REQUIRED,
        )
        github.create_issue.assert_not_called()

    def test_issue_tool_executes_only_when_permission_policy_allows(self) -> None:
        github = Mock()
        created = GitHubIssueCreated(
            number=9,
            title="Issue",
            html_url="https://github.com/owner/atlas/issues/9",
            state="open",
        )
        github.create_issue.return_value = created
        tool = CreateIssueTool()
        tool.github = github
        registry = ToolRegistry()
        registry.register(tool)
        service = ToolExecutionService(
            registry,
            PermissionEngine(
                PermissionPolicy(
                    {
                        (
                            "github.create_issue",
                            PermissionId.GITHUB_ISSUE_WRITE,
                        ): PermissionRule(
                            allowed=True,
                            risk_level=RiskLevel.HIGH,
                            confirmation_required=False,
                        )
                    }
                )
            ),
        )

        result = service.execute(
            ToolExecutionRequest(
                name="github.create_issue",
                arguments={
                    "owner": "owner",
                    "repo": "atlas",
                    "title": "Issue",
                    "body": "Details",
                },
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output["number"], 9)
        github.create_issue.assert_called_once_with(
            owner="owner",
            repo="atlas",
            title="Issue",
            body="Details",
        )

    def test_llm_arguments_cannot_supply_confirmation_or_api_route(self) -> None:
        github = Mock()
        service = create_tool_execution_service(create_github_tools(github))

        result = service.execute(
            ToolExecutionRequest(
                name="github.create_issue",
                arguments={
                    "owner": "owner",
                    "repo": "atlas",
                    "title": "Issue",
                    "confirmation_state": "confirmed",
                    "path": "/app/installations",
                },
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "invalid_arguments")
        github.create_issue.assert_not_called()

    def test_inaccessible_repository_response_does_not_create_issue(self) -> None:
        transport = FakeTransport(response(404, {"message": "not installed"}))
        client = self.make_client(transport)

        with self.assertRaises(GitHubIntegrationError) as error:
            client.create_issue(
                owner="not-installed",
                repo="private",
                title="Issue",
                body=None,
            )

        self.assertEqual(error.exception.code, "not_found")
        self.assertEqual(transport.calls[0][0], "POST")
        self.assertNotIn("not installed", error.exception.safe_message)

    @staticmethod
    def _decode_segment(segment: str) -> bytes:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


if __name__ == "__main__":
    unittest.main()
