from functools import lru_cache

from backend.app.config.settings import settings
from backend.app.conversations.repository import PostgresConversationRepository
from backend.app.security.models import PermissionId, RiskLevel
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.demo import EchoTool
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.registry import ToolRegistry
from backend.app.workflows.engine import WorkflowEngine
from backend.app.workflows.repository import (
    InMemoryWorkflowRepository,
    PostgresWorkflowRepository,
    WorkflowRepository,
)
from backend.app.workflows.service import WorkflowService
from backend.app.workflows.tools import (
    DataExtractionTool,
    HighRiskActionTool,
    VerifyTool,
)
from backend.app.workflows.validator import WorkflowValidator


def create_default_tool_registry() -> tuple[ToolRegistry, PermissionEngine]:
    registry = ToolRegistry()
    tools = [
        EchoTool(),
        VerifyTool(),
        DataExtractionTool(),
        HighRiskActionTool(),
    ]
    for tool in tools:
        registry.register(tool)

    rules = {
        ("system.echo", PermissionId.SYSTEM_ECHO): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.LOW,
            permission_required=False,
        ),
        ("system.verify", PermissionId.TEST_RECORD): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.LOW,
            permission_required=False,
        ),
        ("planner.extract", PermissionId.TEST_RECORD): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.LOW,
            permission_required=False,
        ),
        ("test.action.high_risk", PermissionId.TEST_RECORD): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.HIGH,
            permission_required=True,
            confirmation_required=True,
        ),
    }

    # Fallback rule evaluator for tools registered with string IDs
    policy = PermissionPolicy(rules)
    engine = PermissionEngine(policy)
    return registry, engine


@lru_cache(maxsize=1)
def get_workflow_repository() -> WorkflowRepository:
    if settings.database_url:
        return PostgresWorkflowRepository(settings.database_url)
    return InMemoryWorkflowRepository()


def get_workflow_service() -> WorkflowService:
    repository = get_workflow_repository()
    registry, permission_engine = create_default_tool_registry()
    tool_executor = ToolExecutionService(registry, permission_engine)
    validator = WorkflowValidator(registry)
    engine = WorkflowEngine(repository, tool_executor, permission_engine)

    conversation_repo = (
        PostgresConversationRepository(settings.database_url)
        if settings.database_url
        else None
    )

    return WorkflowService(
        repository=repository,
        validator=validator,
        engine=engine,
        conversation_repository=conversation_repo,
    )

