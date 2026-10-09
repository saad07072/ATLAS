from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from typing import Any, TypeVar
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ValidationError

from backend.app.config.settings import Settings
from backend.app.integrations.github.auth import (
    GITHUB_API_BASE,
    GitHubAppAuthentication,
)
from backend.app.integrations.github.errors import (
    GitHubIntegrationError,
    normalize_github_status,
)
from backend.app.integrations.github.models import (
    GitHubIssue,
    GitHubIssueList,
    GitHubIssueCreated,
    GitHubPullRequest,
    GitHubRepository,
    GitHubRepositoryList,
)
from backend.app.integrations.github.transport import HttpResponse, HttpTransport, UrllibTransport

_Model = TypeVar("_Model", bound=BaseModel)
_NEXT_PAGE = re.compile(r'<[^>]*[?&]page=(\d+)[^>]*>;\s*rel="next"', re.IGNORECASE)
_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
_MAX_GET_ATTEMPTS = 3
_REPOSITORY_PATH = re.compile(r"^/repos/[^/]+/[^/]+$")
_ISSUES_PATH = re.compile(r"^/repos/[^/]+/[^/]+/issues$")
_PULL_REQUEST_PATH = re.compile(r"^/repos/[^/]+/[^/]+/pulls/[1-9][0-9]*$")


class GitHubApiClient:
    def __init__(
        self,
        authentication: GitHubAppAuthentication,
        settings: Settings,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self.authentication = authentication
        self.settings = settings
        self.transport = transport or UrllibTransport()

    def list_repositories(
        self,
        *,
        page: int,
        per_page: int,
    ) -> GitHubRepositoryList:
        response = self._request(
            "GET",
            "/installation/repositories",
            query={"page": page, "per_page": per_page},
        )
        payload = self._object_payload(response)
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            raise self._invalid_response()
        if not all(isinstance(item, dict) for item in repositories):
            raise self._invalid_response()
        return GitHubRepositoryList(
            repositories=[self._repository(item) for item in repositories],
            next_page=self._next_page(response),
        )

    def get_repository(self, *, owner: str, repo: str) -> GitHubRepository:
        response = self._request("GET", self._repository_path(owner, repo))
        return self._repository(self._object_payload(response))

    def list_issues(
        self,
        *,
        owner: str,
        repo: str,
        page: int,
        per_page: int,
    ) -> GitHubIssueList:
        response = self._request(
            "GET",
            f"{self._repository_path(owner, repo)}/issues",
            query={"page": page, "per_page": per_page},
        )
        payload = self._array_payload(response)
        if not all(isinstance(item, dict) for item in payload):
            raise self._invalid_response()
        issues = [self._issue(item) for item in payload if "pull_request" not in item]
        return GitHubIssueList(issues=issues, next_page=self._next_page(response))

    def get_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> GitHubPullRequest:
        response = self._request(
            "GET",
            f"{self._repository_path(owner, repo)}/pulls/{number}",
        )
        return self._pull_request(self._object_payload(response))

    def create_issue(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        body: str | None,
    ) -> GitHubIssueCreated:
        response = self._request(
            "POST",
            f"{self._repository_path(owner, repo)}/issues",
            body={"title": title, "body": body},
        )
        return self._created_issue(self._object_payload(response))

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, int] | None = None,
        body: dict[str, Any] | None = None,
    ) -> HttpResponse:
        allowed_route = (
            method == "GET"
            and (
                path == "/installation/repositories"
                or _REPOSITORY_PATH.fullmatch(path) is not None
                or _ISSUES_PATH.fullmatch(path) is not None
                or _PULL_REQUEST_PATH.fullmatch(path) is not None
            )
        ) or (
            method == "POST" and _ISSUES_PATH.fullmatch(path) is not None
        )
        if not allowed_route:
            raise GitHubIntegrationError(
                "invalid_request",
                "The GitHub request is invalid.",
            )
        url = f"{GITHUB_API_BASE}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request_body = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )
        token = self.authentication.installation_token()
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if request_body is not None:
            headers["Content-Type"] = "application/json"

        attempts = _MAX_GET_ATTEMPTS if method == "GET" else 1
        for attempt in range(attempts):
            try:
                response = self.transport.request(
                    method,
                    url,
                    headers=headers,
                    body=request_body,
                    timeout=self.settings.github_api_timeout_seconds,
                )
            except GitHubIntegrationError as exc:
                if method != "GET" or exc.code != "network_error" or attempt + 1 == attempts:
                    raise
                time.sleep(0.1 * (attempt + 1))
                continue
            except Exception:
                raise GitHubIntegrationError(
                    "network_error",
                    "The GitHub service could not be reached. Please try again.",
                ) from None

            if 200 <= response.status_code < 300:
                return response
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt + 1 < attempts:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise normalize_github_status(
                response.status_code,
                rate_limit_remaining=self._header(
                    response.headers, "X-RateLimit-Remaining"
                ),
            )
        raise GitHubIntegrationError(
            "network_error",
            "The GitHub service could not be reached. Please try again.",
        )

    @staticmethod
    def _repository_path(owner: str, repo: str) -> str:
        return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"

    @classmethod
    def _repository(cls, payload: dict[str, Any]) -> GitHubRepository:
        owner = payload.get("owner")
        if not isinstance(owner, dict):
            raise cls._invalid_response()
        return cls._model(
            GitHubRepository,
            {
                "id": payload.get("id"),
                "name": payload.get("name"),
                "full_name": payload.get("full_name"),
                "owner": owner.get("login"),
                "private": payload.get("private"),
                "html_url": payload.get("html_url"),
                "description": payload.get("description"),
                "default_branch": payload.get("default_branch"),
            },
        )

    @classmethod
    def _issue(cls, payload: dict[str, Any]) -> GitHubIssue:
        user = payload.get("user")
        if not isinstance(user, dict):
            raise cls._invalid_response()
        return cls._model(
            GitHubIssue,
            {
                "number": payload.get("number"),
                "title": payload.get("title"),
                "body": payload.get("body"),
                "state": payload.get("state"),
                "html_url": payload.get("html_url"),
                "user": user.get("login"),
            },
        )

    @classmethod
    def _pull_request(cls, payload: dict[str, Any]) -> GitHubPullRequest:
        head = payload.get("head")
        base = payload.get("base")
        if not isinstance(head, dict) or not isinstance(base, dict):
            raise cls._invalid_response()
        return cls._model(
            GitHubPullRequest,
            {
                "number": payload.get("number"),
                "title": payload.get("title"),
                "body": payload.get("body"),
                "state": payload.get("state"),
                "html_url": payload.get("html_url"),
                "draft": payload.get("draft"),
                "merged": payload.get("merged"),
                "head": head.get("ref"),
                "base": base.get("ref"),
            },
        )

    @classmethod
    def _created_issue(cls, payload: dict[str, Any]) -> GitHubIssueCreated:
        return cls._model(
            GitHubIssueCreated,
            {
                "number": payload.get("number"),
                "title": payload.get("title"),
                "html_url": payload.get("html_url"),
                "state": payload.get("state"),
            },
        )

    @staticmethod
    def _object_payload(response: HttpResponse) -> dict[str, Any]:
        payload = GitHubApiClient._json_payload(response)
        if not isinstance(payload, dict):
            raise GitHubApiClient._invalid_response()
        return payload

    @staticmethod
    def _array_payload(response: HttpResponse) -> list[Any]:
        payload = GitHubApiClient._json_payload(response)
        if not isinstance(payload, list):
            raise GitHubApiClient._invalid_response()
        return payload

    @staticmethod
    def _json_payload(response: HttpResponse) -> Any:
        try:
            return json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            raise GitHubApiClient._invalid_response() from None

    @staticmethod
    def _model(model: type[_Model], payload: object) -> _Model:
        try:
            return model.model_validate(payload)
        except (ValidationError, TypeError, ValueError):
            raise GitHubApiClient._invalid_response() from None

    @staticmethod
    def _next_page(response: HttpResponse) -> int | None:
        link = GitHubApiClient._header(response.headers, "Link")
        match = _NEXT_PAGE.search(link or "")
        return int(match.group(1)) if match else None

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        return next(
            (value for key, value in headers.items() if key.lower() == name.lower()),
            None,
        )

    @staticmethod
    def _invalid_response() -> GitHubIntegrationError:
        return GitHubIntegrationError(
            "invalid_response",
            "GitHub returned an invalid response.",
        )
