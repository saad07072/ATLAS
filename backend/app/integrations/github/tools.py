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
    GitHubWorkflow,
    GitHubWorkflowList,
    GitHubWorkflowRun,
    GitHubWorkflowRunList,
    GitHubWorkflowDispatchResult,
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


class WorkflowListInput(RepositoryInput):
    pass


class WorkflowRunsInput(RepositoryInput):
    page: int = Field(default=1, ge=1, le=10000)
    per_page: int = Field(default=30, ge=1, le=100)


class WorkflowRunInput(RepositoryInput):
    run_id: int = Field(gt=0)


class WorkflowDispatchInput(RepositoryInput):
    workflow_id: str = Field(min_length=1, max_length=256)
    ref: str = Field(default="main", min_length=1, max_length=255)
    inputs: dict[str, str] = Field(default_factory=dict)


class ListWorkflowsTool(GitHubTool):
    name = "github.list_workflows"
    description = "Lists GitHub Actions workflows for a repository."
    input_schema = WorkflowListInput
    output_schema = GitHubWorkflowList
    permission_required = True
    permission_id = PermissionId.GITHUB_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, WorkflowListInput):
            raise TypeError
        return self.github.list_workflows(owner=arguments.owner, repo=arguments.repo)


class ListWorkflowRunsTool(GitHubTool):
    name = "github.list_workflow_runs"
    description = "Lists recent GitHub Actions workflow runs for a repository."
    input_schema = WorkflowRunsInput
    output_schema = GitHubWorkflowRunList
    permission_required = True
    permission_id = PermissionId.GITHUB_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, WorkflowRunsInput):
            raise TypeError
        return self.github.list_workflow_runs(
            owner=arguments.owner,
            repo=arguments.repo,
            page=arguments.page,
            per_page=arguments.per_page,
        )


class GetWorkflowRunTool(GitHubTool):
    name = "github.get_workflow_run"
    description = "Gets details and status for a specific GitHub Actions workflow run."
    input_schema = WorkflowRunInput
    output_schema = GitHubWorkflowRun
    permission_required = True
    permission_id = PermissionId.GITHUB_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, WorkflowRunInput):
            raise TypeError
        return self.github.get_workflow_run(
            owner=arguments.owner,
            repo=arguments.repo,
            run_id=arguments.run_id,
        )


class TriggerWorkflowDispatchTool(GitHubTool):
    name = "github.trigger_workflow_dispatch"
    description = "Triggers a GitHub Actions workflow dispatch event."
    input_schema = WorkflowDispatchInput
    output_schema = GitHubWorkflowDispatchResult
    permission_required = True
    permission_id = PermissionId.GITHUB_ISSUE_WRITE.value
    risk_level = RiskLevel.HIGH.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, WorkflowDispatchInput):
            raise TypeError
        return self.github.trigger_workflow_dispatch(
            owner=arguments.owner,
            repo=arguments.repo,
            workflow_id=arguments.workflow_id,
            ref=arguments.ref,
            inputs=arguments.inputs,
        )


def create_all_github_tools(github: GitHubApiClient) -> list[Tool]:
    tools: list[Tool] = [
        ListRepositoriesTool(),
        GetRepositoryTool(),
        ListIssuesTool(),
        GetPullRequestTool(),
        CreateIssueTool(),
        ListWorkflowsTool(),
        ListWorkflowRunsTool(),
        GetWorkflowRunTool(),
        TriggerWorkflowDispatchTool(),
    ]
    for tool in tools:
        tool.github = github
    return tools
