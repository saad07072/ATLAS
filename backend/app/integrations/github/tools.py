from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.integrations.github.errors import GitHubIntegrationError
from backend.app.integrations.github.models import (
    GitHubIssueCreated,
    GitHubIssueList,
    GitHubPullRequest,
    GitHubRepository,
    GitHubRepositoryList,
)
from backend.app.integrations.github.service import GitHubApiClient
from backend.app.security.models import PermissionId, RiskLevel
from backend.app.tools.base import Tool
from backend.app.tools.errors import ToolFrameworkError
from backend.app.tools.models import ToolErrorInfo

_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_PATTERN = re.compile(r"^(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}$")


class GitHubTool(Tool):
    github: GitHubApiClient
    permission_id: ClassVar[str]

    def error_handler(self, error: Exception) -> ToolErrorInfo:
        if isinstance(error, GitHubIntegrationError):
            return ToolErrorInfo(code=error.code, message=error.safe_message)
        if isinstance(error, ToolFrameworkError):
            return super().error_handler(error)
        return ToolErrorInfo(
            code="github_operation_failed",
            message="The GitHub operation could not be completed.",
        )


class RepositoryListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    page: int = Field(default=1, ge=1, le=10000)
    per_page: int = Field(default=30, ge=1, le=100)


class RepositoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    owner: str = Field(min_length=1, max_length=39)
    repo: str = Field(min_length=1, max_length=100)

    @field_validator("owner")
    @classmethod
    def validate_owner(cls, value: str) -> str:
        if not _OWNER_PATTERN.fullmatch(value):
            raise ValueError("Invalid GitHub owner.")
        return value

    @field_validator("repo")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not _REPOSITORY_PATTERN.fullmatch(value):
            raise ValueError("Invalid GitHub repository.")
        return value


class IssueListInput(RepositoryInput):
    page: int = Field(default=1, ge=1, le=10000)
    per_page: int = Field(default=30, ge=1, le=100)


class PullRequestInput(RepositoryInput):
    number: int = Field(gt=0, le=2_147_483_647)


class CreateIssueInput(RepositoryInput):
    title: str = Field(min_length=1, max_length=256)
    body: str | None = Field(default=None, max_length=65536)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Issue title must not be blank.")
        return value


class ListRepositoriesTool(GitHubTool):
    name = "github.list_repositories"
    description = "Lists repositories available to the configured GitHub App."
    input_schema = RepositoryListInput
    output_schema = GitHubRepositoryList
    permission_required = True
    permission_id = PermissionId.GITHUB_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, RepositoryListInput):
            raise TypeError
        return self.github.list_repositories(
            page=arguments.page,
            per_page=arguments.per_page,
        )


class GetRepositoryTool(GitHubTool):
    name = "github.get_repository"
    description = "Gets normalized details for an App-accessible repository."
    input_schema = RepositoryInput
    output_schema = GitHubRepository
    permission_required = True
    permission_id = PermissionId.GITHUB_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, RepositoryInput):
            raise TypeError
        return self.github.get_repository(owner=arguments.owner, repo=arguments.repo)


class ListIssuesTool(GitHubTool):
    name = "github.list_issues"
    description = "Lists issues in an App-accessible repository."
    input_schema = IssueListInput
    output_schema = GitHubIssueList
    permission_required = True
    permission_id = PermissionId.GITHUB_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, IssueListInput):
            raise TypeError
        return self.github.list_issues(
            owner=arguments.owner,
            repo=arguments.repo,
            page=arguments.page,
            per_page=arguments.per_page,
        )


class GetPullRequestTool(GitHubTool):
    name = "github.get_pull_request"
    description = "Gets a pull request in an App-accessible repository."
    input_schema = PullRequestInput
    output_schema = GitHubPullRequest
    permission_required = True
    permission_id = PermissionId.GITHUB_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, PullRequestInput):
            raise TypeError
        return self.github.get_pull_request(
            owner=arguments.owner,
            repo=arguments.repo,
            number=arguments.number,
        )


class CreateIssueTool(GitHubTool):
    name = "github.create_issue"
    description = "Creates an issue in an App-accessible repository."
    input_schema = CreateIssueInput
    output_schema = GitHubIssueCreated
    permission_required = True
    permission_id = PermissionId.GITHUB_ISSUE_WRITE.value
    risk_level = RiskLevel.HIGH.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, CreateIssueInput):
            raise TypeError
        return self.github.create_issue(
            owner=arguments.owner,
            repo=arguments.repo,
            title=arguments.title,
            body=arguments.body,
        )


def create_github_tools(github: GitHubApiClient) -> list[Tool]:
    tools: list[Tool] = [
        ListRepositoriesTool(),
        GetRepositoryTool(),
        ListIssuesTool(),
        GetPullRequestTool(),
        CreateIssueTool(),
    ]
    for tool in tools:
        tool.github = github
    return tools
