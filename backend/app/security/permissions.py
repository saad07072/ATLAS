from backend.app.security.models import (
    AuthorizationResult,
    PermissionContext,
    PermissionDecision,
    PermissionId,
    RiskLevel,
)
from backend.app.security.policy import PermissionPolicy, PermissionRule


class PermissionEngine:
    def __init__(self, policy: PermissionPolicy | None = None) -> None:
        self.policy = policy or PermissionPolicy()

    def evaluate(
        self,
        context: PermissionContext | None,
    ) -> AuthorizationResult:
        return self.policy.evaluate(context)


__all__ = [
    "AuthorizationResult",
    "PermissionContext",
    "PermissionDecision",
    "PermissionEngine",
    "PermissionId",
    "PermissionPolicy",
    "PermissionRule",
    "RiskLevel",
]
