from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.app.security.models import (
    ConfirmationState,
    PermissionDecision,
    RiskLevel,
)
from backend.app.workflows.errors import InvalidStateTransitionError


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class StepVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"


# Legal workflow state transitions
VALID_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.DRAFT: {
        WorkflowStatus.READY,
        WorkflowStatus.RUNNING,
        WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.READY: {
        WorkflowStatus.RUNNING,
        WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.RUNNING: {
        WorkflowStatus.WAITING_FOR_CONFIRMATION,
        WorkflowStatus.COMPLETED,
        WorkflowStatus.PARTIALLY_COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.WAITING_FOR_CONFIRMATION: {
        WorkflowStatus.RUNNING,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
        WorkflowStatus.PARTIALLY_COMPLETED,
    },
    WorkflowStatus.COMPLETED: set(),
    WorkflowStatus.PARTIALLY_COMPLETED: set(),
    WorkflowStatus.FAILED: set(),
    WorkflowStatus.CANCELLED: set(),
}

# Legal step state transitions
VALID_STEP_TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.PENDING: {
        StepStatus.READY,
        StepStatus.RUNNING,
        StepStatus.SKIPPED,
        StepStatus.CANCELLED,
    },
    StepStatus.READY: {
        StepStatus.RUNNING,
        StepStatus.WAITING_FOR_CONFIRMATION,
        StepStatus.SKIPPED,
        StepStatus.CANCELLED,
    },
    StepStatus.RUNNING: {
        StepStatus.WAITING_FOR_CONFIRMATION,
        StepStatus.COMPLETED,
        StepStatus.FAILED,
        StepStatus.CANCELLED,
    },
    StepStatus.WAITING_FOR_CONFIRMATION: {
        StepStatus.READY,
        StepStatus.RUNNING,
        StepStatus.FAILED,
        StepStatus.CANCELLED,
        StepStatus.SKIPPED,
    },
    StepStatus.COMPLETED: set(),
    StepStatus.FAILED: {StepStatus.RUNNING},  # Allow retry of failed step if eligible
    StepStatus.SKIPPED: set(),
    StepStatus.CANCELLED: set(),
}


def assert_workflow_transition(
    from_status: WorkflowStatus,
    to_status: WorkflowStatus,
) -> None:
    if from_status == to_status:
        return
    allowed = VALID_WORKFLOW_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise InvalidStateTransitionError(
            from_state=from_status.value,
            to_state=to_status.value,
            entity="workflow",
        )


def assert_step_transition(
    from_status: StepStatus,
    to_status: StepStatus,
) -> None:
    if from_status == to_status:
        return
    allowed = VALID_STEP_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise InvalidStateTransitionError(
            from_state=from_status.value,
            to_state=to_status.value,
            entity="step",
        )


class WorkflowStepDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Unique identifier for the step in the workflow DAG.",
    )
    title: str = Field(min_length=1, max_length=120)
    tool_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_.\-]+$",
    )
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="IDs of steps that must complete before this step can execute.",
    )
    max_retries: int = Field(default=0, ge=0, le=3)
    requires_verification: bool = Field(default=False)
    verification_rule: str | None = Field(default=None, max_length=200)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=120)
    user_request: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None)
    steps: list[WorkflowStepDefinition] = Field(min_length=1)


class WorkflowStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    step_id: str
    step_order: int
    title: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    attempt_count: int = 0
    max_retries: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    permission_required: bool = False
    permission_decision: PermissionDecision | None = None
    confirmation_state: ConfirmationState = ConfirmationState.NOT_REQUESTED
    confirmation_hash: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result_data: dict[str, Any] | None = None
    error_info: dict[str, Any] | None = None
    verification_status: StepVerificationStatus = StepVerificationStatus.UNVERIFIED
    verification_details: str | None = None


class WorkflowRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    conversation_id: str | None = None
    title: str
    user_request: str
    status: WorkflowStatus = WorkflowStatus.DRAFT
    current_step_id: str | None = None
    step_count: int = 0
    completed_step_count: int = 0
    result_summary: str | None = None
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    version: int = 1
    steps: list[WorkflowStepRecord] = Field(default_factory=list)


class WorkflowEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    workflow_title: str | None = None
    step_id: str | None = None
    event_type: str = Field(max_length=64)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowEventListResponse(BaseModel):
    items: list[WorkflowEventRecord]
    total: int
    limit: int
    offset: int
    has_more: bool


class StepConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["confirm", "reject"]
    reason: str | None = Field(default=None, max_length=500)


class WorkflowSummary(BaseModel):
    id: str
    conversation_id: str | None = None
    title: str
    user_request: str
    status: WorkflowStatus
    step_count: int
    completed_step_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class WorkflowListResponse(BaseModel):
    items: list[WorkflowSummary]
    total: int
    limit: int
    offset: int
    has_more: bool


class WorkflowPlanProposal(BaseModel):
    title: str
    user_request: str
    steps: list[WorkflowStepDefinition]
    requires_confirmation: bool = False
