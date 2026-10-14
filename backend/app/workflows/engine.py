from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.security.models import (
    ConfirmationState,
    PermissionContext,
    PermissionDecision,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.models import ToolExecutionRequest, ToolResult
from backend.app.workflows.errors import (
    InvalidStateTransitionError,
    WorkflowConflictError,
    WorkflowNotFoundError,
)
from backend.app.workflows.models import (
    StepStatus,
    StepVerificationStatus,
    WorkflowEventRecord,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowStepRecord,
    assert_step_transition,
    assert_workflow_transition,
)
from backend.app.workflows.repository import WorkflowRepository
from backend.app.workflows.validator import compute_confirmation_hash

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Core deterministic orchestrator for ATLAS workflows.
    Enforces DAG dependencies, re-checks security policies, manages confirmation pauses,
    executes tools via ToolExecutionService, and accurately reports partial/full outcomes.
    """

    def __init__(
        self,
        repository: WorkflowRepository,
        tool_executor: ToolExecutionService,
        permission_engine: PermissionEngine,
    ) -> None:
        self.repository = repository
        self.tool_executor = tool_executor
        self.permission_engine = permission_engine

    def execute_workflow(
        self,
        user_id: str,
        workflow_id: str,
    ) -> WorkflowRecord:
        """Runs eligible steps until the workflow finishes, pauses for confirmation, or encounters terminal failure."""
        workflow = self.repository.get(user_id, workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found.")

        # Transition draft/ready -> running
        if workflow.status in {WorkflowStatus.DRAFT, WorkflowStatus.READY}:
            assert_workflow_transition(workflow.status, WorkflowStatus.RUNNING)
            workflow = self.repository.update_workflow(
                user_id,
                workflow_id,
                status=WorkflowStatus.RUNNING,
            )
            self._record_event(user_id, workflow_id, None, "workflow_started", {
                "initial_status": workflow.status.value,
            })
        elif workflow.status != WorkflowStatus.RUNNING:
            raise WorkflowConflictError(
                f"Cannot execute workflow in status '{workflow.status.value}'."
            )

        # Main execution loop
        while True:
            # Refresh latest workflow state
            workflow = self.repository.get(user_id, workflow_id)
            if not workflow or workflow.status != WorkflowStatus.RUNNING:
                break

            steps = sorted(workflow.steps, key=lambda s: s.step_order)
            step_status_map = {s.step_id: s.status for s in steps}

            # Find next step eligible for execution
            eligible_step: WorkflowStepRecord | None = None
            has_blocked_pending = False
            has_waiting_confirmation = False

            for step in steps:
                if step.status == StepStatus.WAITING_FOR_CONFIRMATION:
                    has_waiting_confirmation = True
                    break

                if step.status in {StepStatus.PENDING, StepStatus.READY}:
                    # Check prerequisites
                    deps = step.dependencies
                    dep_statuses = [step_status_map[d] for d in deps]

                    # If any dependency failed, was skipped, or cancelled, this step must be skipped
                    if any(ds in {StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.CANCELLED} for ds in dep_statuses):
                        self._skip_step(
                            user_id,
                            workflow_id,
                            step,
                            reason="Prerequisite step failed or was skipped.",
                        )
                        continue

                    # If all dependencies are completed, step is ready to execute
                    if all(ds == StepStatus.COMPLETED for ds in dep_statuses):
                        eligible_step = step
                        break
                    else:
                        has_blocked_pending = True

            if has_waiting_confirmation:
                # Pause workflow in waiting_for_confirmation
                self.repository.update_workflow(
                    user_id,
                    workflow_id,
                    status=WorkflowStatus.WAITING_FOR_CONFIRMATION,
                )
                self._record_event(
                    user_id,
                    workflow_id,
                    None,
                    "workflow_paused",
                    {"reason": "waiting_for_confirmation"},
                )
                break

            if eligible_step is None:
                if has_blocked_pending:
                    # Unresolvable dependencies - skip remaining
                    for step in steps:
                        if step.status in {StepStatus.PENDING, StepStatus.READY}:
                            self._skip_step(
                                user_id,
                                workflow_id,
                                step,
                                reason="Prerequisites could not be satisfied.",
                            )
                # Check for termination
                self._finalize_workflow_outcome(user_id, workflow_id)
                break

            # Execute the eligible step
            paused = self._execute_step(user_id, workflow, eligible_step)
            if paused:
                # Paused for confirmation
                break

        return self.repository.get(user_id, workflow_id) or workflow

    def _execute_step(
        self,
        user_id: str,
        workflow: WorkflowRecord,
        step: WorkflowStepRecord,
    ) -> bool:
        """
        Executes a single step. Returns True if execution paused (e.g. for confirmation), False if step finished.
        """
        workflow_id = workflow.id
        step_id = step.step_id

        # Update to running
        assert_step_transition(step.status, StepStatus.RUNNING)
        step = self.repository.update_step(
            user_id,
            workflow_id,
            step_id,
            status=StepStatus.RUNNING,
            attempt_count=step.attempt_count + 1,
            started_at=datetime.now(timezone.utc),
        )
        self.repository.update_workflow(
            user_id,
            workflow_id,
            current_step_id=step_id,
        )
        self._record_event(user_id, workflow_id, step_id, "step_started", {
            "tool_name": step.tool_name,
            "attempt": step.attempt_count,
        })

        # Evaluate permissions
        tool = self.tool_executor.registry.get(step.tool_name)
        permission_str = str(tool.permission_id) if tool.permission_id else None
        context = (
            PermissionContext(
                user_id=user_id,
                requested_action=permission_str,
                tool_name=step.tool_name,
                permission=permission_str,
                risk_level=step.risk_level.value,
                permission_required=step.permission_required,
                confirmation_state=step.confirmation_state,
                source="workflow_engine",
            )
            if permission_str
            else None
        )
        authorization = self.permission_engine.evaluate(context)

        # Handle Confirmation Required
        if authorization.decision == PermissionDecision.CONFIRMATION_REQUIRED:
            conf_hash = compute_confirmation_hash(
                user_id,
                workflow_id,
                step_id,
                step.tool_name,
                step.arguments,
            )
            assert_step_transition(step.status, StepStatus.WAITING_FOR_CONFIRMATION)
            self.repository.update_step(
                user_id,
                workflow_id,
                step_id,
                status=StepStatus.WAITING_FOR_CONFIRMATION,
                confirmation_state=ConfirmationState.PENDING,
                confirmation_hash=conf_hash,
                permission_decision=PermissionDecision.CONFIRMATION_REQUIRED,
            )
            self.repository.update_workflow(
                user_id,
                workflow_id,
                status=WorkflowStatus.WAITING_FOR_CONFIRMATION,
            )
            self._record_event(user_id, workflow_id, step_id, "confirmation_required", {
                "tool_name": step.tool_name,
                "risk_level": step.risk_level.value,
                "reason": authorization.message,
            })
            return True  # Paused!

        # Handle Denied
        if authorization.decision == PermissionDecision.DENY:
            assert_step_transition(step.status, StepStatus.FAILED)
            self.repository.update_step(
                user_id,
                workflow_id,
                step_id,
                status=StepStatus.FAILED,
                completed_at=datetime.now(timezone.utc),
                permission_decision=PermissionDecision.DENY,
                error_info={
                    "code": authorization.reason_code,
                    "message": authorization.message,
                },
            )
            self._record_event(user_id, workflow_id, step_id, "step_denied", {
                "reason_code": authorization.reason_code,
                "message": authorization.message,
            })
            return False

        # Execute Tool via ToolExecutionService
        request = ToolExecutionRequest(name=step.tool_name, arguments=step.arguments)
        result: ToolResult = self.tool_executor.execute(request, context=context)

        if not result.success:
            # Check retry logic
            if step.attempt_count <= step.max_retries and step.risk_level == RiskLevel.LOW:
                logger.warning("Step %s failed (attempt %d). Retrying...", step_id, step.attempt_count)
                # Leave step in READY so loop retries
                self.repository.update_step(
                    user_id,
                    workflow_id,
                    step_id,
                    status=StepStatus.READY,
                    error_info=result.error.model_dump() if result.error else None,
                )
                return False

            # Mark step failed
            assert_step_transition(step.status, StepStatus.FAILED)
            self.repository.update_step(
                user_id,
                workflow_id,
                step_id,
                status=StepStatus.FAILED,
                completed_at=datetime.now(timezone.utc),
                error_info=result.error.model_dump() if result.error else {"code": "execution_failed", "message": "Tool execution failed."},
            )
            self._record_event(user_id, workflow_id, step_id, "step_failed", {
                "error": result.error.model_dump() if result.error else None,
            })
            return False

        # Verify output if applicable
        verification_status = StepVerificationStatus.VERIFIED
        verification_details = "Output validated."

        if step.tool_name == "system.verify" and result.output:
            if not result.output.get("verified", True):
                verification_status = StepVerificationStatus.FAILED
                verification_details = result.output.get("message", "Verification failed.")

        # Step succeeded
        assert_step_transition(step.status, StepStatus.COMPLETED)
        self.repository.update_step(
            user_id,
            workflow_id,
            step_id,
            status=StepStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
            result_data=result.output,
            permission_decision=PermissionDecision.ALLOW,
            verification_status=verification_status,
            verification_details=verification_details,
        )

        # Increment completed count on workflow
        latest_wf = self.repository.get(user_id, workflow_id)
        new_completed = (latest_wf.completed_step_count + 1) if latest_wf else 1
        self.repository.update_workflow(
            user_id,
            workflow_id,
            completed_step_count=new_completed,
        )

        self._record_event(user_id, workflow_id, step_id, "step_completed", {
            "verification_status": verification_status.value,
        })
        return False

    def _skip_step(
        self,
        user_id: str,
        workflow_id: str,
        step: WorkflowStepRecord,
        reason: str,
    ) -> None:
        assert_step_transition(step.status, StepStatus.SKIPPED)
        self.repository.update_step(
            user_id,
            workflow_id,
            step.step_id,
            status=StepStatus.SKIPPED,
            completed_at=datetime.now(timezone.utc),
            error_info={"code": "step_skipped", "message": reason},
        )
        self._record_event(user_id, workflow_id, step.step_id, "step_skipped", {
            "reason": reason,
        })

    def _finalize_workflow_outcome(
        self,
        user_id: str,
        workflow_id: str,
    ) -> None:
        workflow = self.repository.get(user_id, workflow_id)
        if not workflow or workflow.status != WorkflowStatus.RUNNING:
            return

        steps = workflow.steps
        total = len(steps)
        completed = sum(1 for s in steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in steps if s.status == StepStatus.FAILED)
        skipped = sum(1 for s in steps if s.status == StepStatus.SKIPPED)

        now = datetime.now(timezone.utc)

        if completed == total and total > 0:
            assert_workflow_transition(workflow.status, WorkflowStatus.COMPLETED)
            self.repository.update_workflow(
                user_id,
                workflow_id,
                status=WorkflowStatus.COMPLETED,
                completed_at=now,
                current_step_id=None,
                result_summary="All steps completed successfully.",
            )
            self._record_event(user_id, workflow_id, None, "workflow_completed", {
                "completed_steps": completed,
                "total_steps": total,
            })
        elif completed > 0 and (failed > 0 or skipped > 0):
            # Truthful reporting of partial outcome!
            assert_workflow_transition(workflow.status, WorkflowStatus.PARTIALLY_COMPLETED)
            summary = f"Workflow partially completed: {completed} succeeded, {failed} failed, {skipped} skipped."
            self.repository.update_workflow(
                user_id,
                workflow_id,
                status=WorkflowStatus.PARTIALLY_COMPLETED,
                completed_at=now,
                current_step_id=None,
                result_summary=summary,
            )
            self._record_event(user_id, workflow_id, None, "workflow_partially_completed", {
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
            })
        else:
            assert_workflow_transition(workflow.status, WorkflowStatus.FAILED)
            self.repository.update_workflow(
                user_id,
                workflow_id,
                status=WorkflowStatus.FAILED,
                completed_at=now,
                current_step_id=None,
                error_summary="Workflow execution failed.",
            )
            self._record_event(user_id, workflow_id, None, "workflow_failed", {
                "failed": failed,
                "skipped": skipped,
            })

    def confirm_step(
        self,
        user_id: str,
        workflow_id: str,
        step_id: str,
        decision: str,  # "confirm" | "reject"
        reason: str | None = None,
    ) -> WorkflowRecord:
        """Processes user confirmation or rejection of a pending step."""
        workflow = self.repository.get(user_id, workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found.")

        step = next((s for s in workflow.steps if s.step_id == step_id), None)
        if not step:
            raise WorkflowNotFoundError(f"Step '{step_id}' not found in workflow '{workflow_id}'.")

        if step.status != StepStatus.WAITING_FOR_CONFIRMATION:
            raise WorkflowConflictError(
                f"Step '{step_id}' is in status '{step.status.value}', not waiting for confirmation."
            )

        if decision == "reject":
            # Mark step failed/cancelled
            assert_step_transition(step.status, StepStatus.FAILED)
            self.repository.update_step(
                user_id,
                workflow_id,
                step_id,
                status=StepStatus.FAILED,
                completed_at=datetime.now(timezone.utc),
                confirmation_state=ConfirmationState.NOT_REQUESTED,
                error_info={
                    "code": "confirmation_rejected",
                    "message": reason or "The user rejected authorization for this operation.",
                },
            )
            self._record_event(user_id, workflow_id, step_id, "confirmation_rejected", {
                "reason": reason,
            })
            # Resume workflow so downstream steps get skipped and workflow finalizes
            self.repository.update_workflow(
                user_id,
                workflow_id,
                status=WorkflowStatus.RUNNING,
            )
            return self.execute_workflow(user_id, workflow_id)

        # Decision is "confirm"
        expected_hash = compute_confirmation_hash(
            user_id,
            workflow_id,
            step_id,
            step.tool_name,
            step.arguments,
        )
        if step.confirmation_hash and step.confirmation_hash != expected_hash:
            raise WorkflowConflictError("Confirmation token mismatch or arguments were altered.")

        assert_step_transition(step.status, StepStatus.READY)
        self.repository.update_step(
            user_id,
            workflow_id,
            step_id,
            status=StepStatus.READY,
            confirmation_state=ConfirmationState.CONFIRMED,
        )
        self.repository.update_workflow(
            user_id,
            workflow_id,
            status=WorkflowStatus.RUNNING,
        )
        self._record_event(user_id, workflow_id, step_id, "confirmation_approved", {
            "reason": reason,
        })

        # Continue execution
        return self.execute_workflow(user_id, workflow_id)

    def cancel_workflow(
        self,
        user_id: str,
        workflow_id: str,
    ) -> WorkflowRecord:
        """Cancels an in-progress, ready, or paused workflow safely."""
        workflow = self.repository.get(user_id, workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found.")

        if workflow.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.PARTIALLY_COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }:
            raise WorkflowConflictError(
                f"Cannot cancel workflow in terminal status '{workflow.status.value}'."
            )

        now = datetime.now(timezone.utc)
        # Cancel non-completed steps
        for step in workflow.steps:
            if step.status in {
                StepStatus.PENDING,
                StepStatus.READY,
                StepStatus.WAITING_FOR_CONFIRMATION,
            }:
                self.repository.update_step(
                    user_id,
                    workflow_id,
                    step.step_id,
                    status=StepStatus.CANCELLED,
                    completed_at=now,
                    error_info={"code": "cancelled", "message": "Cancelled by user request."},
                )

        assert_workflow_transition(workflow.status, WorkflowStatus.CANCELLED)
        updated = self.repository.update_workflow(
            user_id,
            workflow_id,
            status=WorkflowStatus.CANCELLED,
            completed_at=now,
            current_step_id=None,
            result_summary="Workflow was cancelled.",
        )
        self._record_event(user_id, workflow_id, None, "workflow_cancelled", {})
        return updated or workflow

    def _record_event(
        self,
        user_id: str,
        workflow_id: str,
        step_id: str | None,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        event = WorkflowEventRecord(
            workflow_id=workflow_id,
            step_id=step_id,
            event_type=event_type,
            details=details,
        )
        self.repository.record_event(user_id, event)
