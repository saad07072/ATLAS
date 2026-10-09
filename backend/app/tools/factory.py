from backend.app.security.models import PermissionId, RiskLevel
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.base import Tool
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.registry import ToolRegistry


def create_tool_execution_service(tools: list[Tool]) -> ToolExecutionService:
    registry = ToolRegistry()
    rules: dict[tuple[str, PermissionId], PermissionRule] = {}
    permission_by_string = {permission.value: permission for permission in PermissionId}
    for tool in tools:
        registry.register(tool)
        if not tool.permission_id:
            continue
        permission = permission_by_string.get(tool.permission_id)
        if permission is None:
            continue
        rules[(tool.name, permission)] = PermissionRule(
            allowed=True,
            risk_level=RiskLevel(tool.risk_level),
            permission_required=tool.permission_required,
        )
    return ToolExecutionService(
        registry,
        PermissionEngine(PermissionPolicy(rules)),
    )
