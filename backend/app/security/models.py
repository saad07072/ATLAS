from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PermissionId(StrEnum):
    SYSTEM_ECHO = "system.echo"
    TEST_RECORD = "test.record"
    CALENDAR_READ = "calendar.read"
    CALENDAR_CREATE = "calendar.create"
    CALENDAR_UPDATE = "calendar.update"
    CALENDAR_DELETE = "calendar.delete"
    GMAIL_READ = "gmail.read"
    GMAIL_DRAFT = "gmail.draft"
    GMAIL_SEND = "gmail.send"
    GMAIL_REPLY = "gmail.reply"
    GITHUB_READ = "github.read"
    GITHUB_ISSUE_WRITE = "github.issue.write"
    GITHUB_PULL_REQUEST_WRITE = "github.pull_request.write"
    GITHUB_CODE_WRITE = "github.code.write"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRMATION_REQUIRED = "confirmation_required"


class ConfirmationState(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    CONFIRMED = "confirmed"


class PermissionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    requested_action: PermissionId | str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=100)
    permission: PermissionId | str | None = Field(default=None, max_length=100)
    risk_level: RiskLevel | str | None = Field(default=None, max_length=20)
    permission_required: bool
    confirmation_state: ConfirmationState = ConfirmationState.NOT_REQUESTED
    source: str | None = Field(default=None, min_length=1, max_length=100)


class AuthorizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: PermissionDecision
    tool_name: str
    permission: PermissionId | str | None = None
    risk_level: RiskLevel | None = None
    reason_code: str
    message: str
