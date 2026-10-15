from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.app.config.settings import settings
from backend.app.conversations.errors import ConversationStoreUnavailable
from backend.app.conversations.models import ConversationRecord
from backend.app.conversations.runtime import get_conversation_service
from backend.app.conversations.service import ConversationService
from backend.app.integrations.github.auth import GitHubAppAuthentication
from backend.app.integrations.github.runtime import get_github_authentication
from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.runtime import get_google_oauth_service
from backend.app.security.identity import require_authenticated_user_id
from backend.app.workflows.models import (
    WorkflowEventRecord,
    WorkflowStatus,
    WorkflowSummary,
)
from backend.app.workflows.runtime import get_workflow_service
from backend.app.workflows.service import WorkflowService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardStatusCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    draft: int = 0
    ready: int = 0
    running: int = 0
    waiting_for_confirmation: int = 0
    completed: int = 0
    partially_completed: int = 0
    failed: int = 0
    cancelled: int = 0


class ConnectedServiceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    status: Literal["Connected", "Disconnected", "Unavailable"]
    configured: bool
    actions_enabled: bool = False
    description: str


class DashboardSystemStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str
    app_version: str
    environment: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_counts: DashboardStatusCounts
    running_workflows: list[WorkflowSummary]
    pending_approvals: list[WorkflowSummary]
    recent_activity: list[WorkflowEventRecord]
    recent_conversations: list[ConversationRecord]
    connected_services: list[ConnectedServiceSummary]
    system_status: DashboardSystemStatus


@router.get("", response_model=DashboardResponse)
def get_dashboard_overview(
    user_id: UUID = Depends(require_authenticated_user_id),
    workflow_service: WorkflowService = Depends(get_workflow_service),
    conversation_service: ConversationService = Depends(get_conversation_service),
    google_oauth: GoogleOAuthService = Depends(get_google_oauth_service),
    github_auth: GitHubAppAuthentication = Depends(get_github_authentication),
) -> DashboardResponse:
    """Returns an authenticated, unified operational overview for the ATLAS dashboard."""
    user_id_str = str(user_id)

    # 1. Workflow counts and lists
    raw_counts = workflow_service.get_workflow_counts(user_id_str)
    workflow_counts = DashboardStatusCounts(
        total=raw_counts.get("total", 0),
        draft=raw_counts.get("draft", 0),
        ready=raw_counts.get("ready", 0),
        running=raw_counts.get("running", 0),
        waiting_for_confirmation=raw_counts.get("waiting_for_confirmation", 0),
        completed=raw_counts.get("completed", 0),
        partially_completed=raw_counts.get("partially_completed", 0),
        failed=raw_counts.get("failed", 0),
        cancelled=raw_counts.get("cancelled", 0),
    )

    # Bounded lists for running and pending approvals
    running_wfs, _, _ = workflow_service.list_workflows(
        user_id_str, limit=10, offset=0, status=WorkflowStatus.RUNNING
    )
    pending_wfs, _, _ = workflow_service.list_workflows(
        user_id_str, limit=10, offset=0, status=WorkflowStatus.WAITING_FOR_CONFIRMATION
    )

    running_summaries = [
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
        for w in running_wfs
    ]

    pending_summaries = [
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
        for w in pending_wfs
    ]

    # 2. Recent chronological activity events
    recent_events, _, _ = workflow_service.list_user_events(user_id_str, limit=10, offset=0)

    # 3. Recent conversations (fail gracefully if storage not configured)
    recent_conversations: list[ConversationRecord] = []
    try:
        convs, _ = conversation_service.list(user_id_str, limit=5, offset=0)
        recent_conversations = convs
    except (ConversationStoreUnavailable, Exception):
        recent_conversations = []

    # 4. Connected Services Status (Guarded: Actions are strictly disabled)
    google_configured = False
    google_connected = False
    try:
        google_configured, google_connected = google_oauth.connection_status(user_id_str)
    except GoogleIntegrationError:
        google_configured = False
        google_connected = False

    github_configured = github_auth.configured

    connected_services = [
        ConnectedServiceSummary(
            id="google",
            name="Google Services",
            status="Connected" if google_connected else ("Disconnected" if google_configured else "Unavailable"),
            configured=google_configured,
            actions_enabled=False,
            description="Gmail and Google Calendar OAuth integration.",
        ),
        ConnectedServiceSummary(
            id="github",
            name="GitHub",
            status="Disconnected" if github_configured else "Unavailable",
            configured=github_configured,
            actions_enabled=False,
            description="GitHub App integration for repositories and issues.",
        ),
    ]

    system_status = DashboardSystemStatus(
        app_name=settings.app_name,
        app_version=settings.app_version,
        environment=settings.environment,
    )

    return DashboardResponse(
        workflow_counts=workflow_counts,
        running_workflows=running_summaries,
        pending_approvals=pending_summaries,
        recent_activity=recent_events,
        recent_conversations=recent_conversations,
        connected_services=connected_services,
        system_status=system_status,
    )
