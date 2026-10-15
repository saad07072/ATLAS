from __future__ import annotations

import logging
from typing import Any

from backend.app.conversations.repository import ConversationRepository
from backend.app.workflows.engine import WorkflowEngine
from backend.app.workflows.errors import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from backend.app.workflows.models import (
    StepStatus,
    WorkflowDefinition,
    WorkflowEventRecord,
    WorkflowRecord,
    WorkflowStatus,
)
from backend.app.workflows.repository import WorkflowRepository
from backend.app.workflows.validator import WorkflowValidator

logger = logging.getLogger(__name__)


class WorkflowService:
    def __init__(
        self,
        repository: WorkflowRepository,
        validator: WorkflowValidator,
        engine: WorkflowEngine,
        conversation_repository: ConversationRepository | None = None,
    ) -> None:
        self.repository = repository
        self.validator = validator
        self.engine = engine
        self.conversation_repository = conversation_repository

    def create_workflow(
        self,
        user_id: str,
        definition: WorkflowDefinition,
    ) -> WorkflowRecord:
        """Validates and persists a new workflow definition."""
        if definition.conversation_id and self.conversation_repository:
            conv = self.conversation_repository.get(user_id, definition.conversation_id)
            if not conv:
                raise WorkflowValidationError(
                    "The specified conversation does not exist or is not owned by this account."
                )

        workflow_record, _ = self.validator.validate_plan(
            definition,
            user_id=user_id,
        )

        created = self.repository.create(workflow_record)
        self.repository.record_event(
            user_id,
            WorkflowEventRecord(
                workflow_id=created.id,
                event_type="workflow_created",
                details={
                    "title": created.title,
                    "step_count": created.step_count,
                    "conversation_id": created.conversation_id,
                },
            ),
        )
        return created

    def list_workflows(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: WorkflowStatus | None = None,
    ) -> tuple[list[WorkflowRecord], bool, int]:
        """Lists user-owned workflows with pagination."""
        return self.repository.list(
            user_id,
            limit=limit,
            offset=offset,
            status=status,
        )

    def get_workflow(
        self,
        user_id: str,
        workflow_id: str,
    ) -> WorkflowRecord:
        """Retrieves an owned workflow by ID."""
        record = self.repository.get(user_id, workflow_id)
        if not record:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found.")
        return record

    def start_workflow(
        self,
        user_id: str,
        workflow_id: str,
    ) -> WorkflowRecord:
        """Starts executing an eligible draft or ready workflow."""
        workflow = self.get_workflow(user_id, workflow_id)
        if workflow.status not in {WorkflowStatus.DRAFT, WorkflowStatus.READY}:
            raise WorkflowConflictError(
                f"Workflow '{workflow_id}' cannot be started from status '{workflow.status.value}'."
            )
        return self.engine.execute_workflow(user_id, workflow_id)

    def resume_workflow(
        self,
        user_id: str,
        workflow_id: str,
    ) -> WorkflowRecord:
        """Resumes execution of a paused or waiting workflow."""
        workflow = self.get_workflow(user_id, workflow_id)
        if workflow.status != WorkflowStatus.WAITING_FOR_CONFIRMATION:
            if workflow.status in {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.PARTIALLY_COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            }:
                raise WorkflowConflictError(
                    f"Workflow in status '{workflow.status.value}' cannot be resumed."
                )

        # Check if any step is still blocking on confirmation
        for step in workflow.steps:
            if step.status == StepStatus.WAITING_FOR_CONFIRMATION:
                raise WorkflowConflictError(
                    f"Step '{step.step_id}' is still waiting for confirmation. Confirm or reject the step before resuming."
                )

        self.repository.update_workflow(
            user_id,
            workflow_id,
            status=WorkflowStatus.RUNNING,
        )
        return self.engine.execute_workflow(user_id, workflow_id)

    def cancel_workflow(
        self,
        user_id: str,
        workflow_id: str,
    ) -> WorkflowRecord:
        """Cancels a workflow safely."""
        return self.engine.cancel_workflow(user_id, workflow_id)

    def confirm_step(
        self,
        user_id: str,
        workflow_id: str,
        step_id: str,
        decision: str,
        reason: str | None = None,
    ) -> WorkflowRecord:
        """Approves or rejects a step requiring confirmation."""
        return self.engine.confirm_step(
            user_id=user_id,
            workflow_id=workflow_id,
            step_id=step_id,
            decision=decision,
            reason=reason,
        )

    def list_events(
        self,
        user_id: str,
        workflow_id: str,
    ) -> list[WorkflowEventRecord]:
        """Lists audit events for an owned workflow."""
        self.get_workflow(user_id, workflow_id)  # Ownership check
        return self.repository.list_events(user_id, workflow_id)

    def list_user_events(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WorkflowEventRecord], bool, int]:
        """Lists chronological audit events across all workflows owned by the user."""
        return self.repository.list_user_events(user_id, limit=limit, offset=offset)

    def get_workflow_counts(self, user_id: str) -> dict[str, int]:
        """Returns deterministic counts of workflows partitioned by status."""
        return self.repository.count_by_status(user_id)

