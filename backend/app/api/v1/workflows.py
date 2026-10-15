from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from backend.app.security.identity import require_authenticated_user_id
from backend.app.workflows.models import (
    StepConfirmationRequest,
    WorkflowDefinition,
    WorkflowEventListResponse,
    WorkflowEventRecord,
    WorkflowListResponse,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowSummary,
)
from backend.app.workflows.runtime import get_workflow_service
from backend.app.workflows.service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowRecord, status_code=status.HTTP_201_CREATED)
def create_workflow(
    definition: WorkflowDefinition,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowRecord:
    """Validates and persists a new workflow."""
    return service.create_workflow(str(user_id), definition)


@router.get("", response_model=WorkflowListResponse)
def list_workflows(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    workflow_status: WorkflowStatus | None = Query(default=None, alias="status"),
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowListResponse:
    """Lists the authenticated user's workflows."""
    workflows, has_more, total = service.list_workflows(
        str(user_id),
        limit=limit,
        offset=offset,
        status=workflow_status,
    )
    items = [
        WorkflowSummary(
            id=w.id,
            conversation_id=w.conversation_id,
            title=w.title,
            user_request=w.user_request,
            status=w.status,
            step_count=w.step_count,
            completed_step_count=w.completed_step_count,
            created_at=w.created_at,
            updated_at=w.updated_at,
            completed_at=w.completed_at,
        )
        for w in workflows
    ]
    return WorkflowListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/events", response_model=WorkflowEventListResponse)
def list_all_user_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowEventListResponse:
    """Lists chronological audit events across all workflows owned by the user."""
    events, has_more, total = service.list_user_events(
        str(user_id),
        limit=limit,
        offset=offset,
    )
    return WorkflowEventListResponse(
        items=events,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/{workflow_id}", response_model=WorkflowRecord)
def get_workflow(
    workflow_id: str,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowRecord:
    """Retrieves full details of a user-owned workflow."""
    return service.get_workflow(str(user_id), workflow_id)


@router.post("/{workflow_id}/start", response_model=WorkflowRecord)
def start_workflow(
    workflow_id: str,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowRecord:
    """Starts executing an eligible workflow."""
    return service.start_workflow(str(user_id), workflow_id)


@router.post("/{workflow_id}/resume", response_model=WorkflowRecord)
def resume_workflow(
    workflow_id: str,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowRecord:
    """Resumes execution of a paused workflow."""
    return service.resume_workflow(str(user_id), workflow_id)


@router.post("/{workflow_id}/cancel", response_model=WorkflowRecord)
def cancel_workflow(
    workflow_id: str,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowRecord:
    """Cancels a workflow safely."""
    return service.cancel_workflow(str(user_id), workflow_id)


@router.post(
    "/{workflow_id}/steps/{step_id}/confirm",
    response_model=WorkflowRecord,
)
def confirm_step(
    workflow_id: str,
    step_id: str,
    confirmation: StepConfirmationRequest,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowRecord:
    """Confirms or rejects an operation requiring approval."""
    return service.confirm_step(
        user_id=str(user_id),
        workflow_id=workflow_id,
        step_id=step_id,
        decision=confirmation.decision,
        reason=confirmation.reason,
    )


@router.get("/{workflow_id}/events", response_model=list[WorkflowEventRecord])
def list_workflow_events(
    workflow_id: str,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: WorkflowService = Depends(get_workflow_service),
) -> list[WorkflowEventRecord]:
    """Retrieves audit events for the specified workflow."""
    return service.list_events(str(user_id), workflow_id)

