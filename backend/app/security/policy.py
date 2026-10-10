from dataclasses import dataclass
from typing import Mapping

from backend.app.security.models import (
    AuthorizationResult,
    ConfirmationState,
    PermissionContext,
    PermissionDecision,
    PermissionId,
    RiskLevel,
)


@dataclass(frozen=True)
class PermissionRule:
    allowed: bool
    risk_level: RiskLevel
    permission_required: bool = True
    confirmation_required: bool | None = None


class PermissionPolicy:
    def __init__(
        self,
        rules: Mapping[tuple[str, PermissionId], PermissionRule] | None = None,
    ) -> None:
        self._rules = dict(rules or {})

    def evaluate(
        self,
        context: PermissionContext | None,
    ) -> AuthorizationResult:
        if not isinstance(context, PermissionContext):
            return self._deny(
                tool_name="",
                permission=None,
                risk_level=None,
                reason_code="invalid_context",
                message="Permission context is invalid.",
            )

        try:
            permission = PermissionId(context.permission)
        except (TypeError, ValueError):
            return self._deny_context(
                context,
                reason_code="unknown_permission",
                message="The requested permission is not recognized.",
            )

        try:
            risk_level = RiskLevel(context.risk_level)
        except (TypeError, ValueError):
            return self._deny_context(
                context,
                permission=permission,
                reason_code="invalid_context",
                message="Permission context is invalid.",
            )

        if context.requested_action != permission.value:
            return self._deny_context(
                context,
                permission=permission,
                risk_level=risk_level,
                reason_code="invalid_context",
                message="Permission context is inconsistent.",
            )

        rule = self._rules.get((context.tool_name, permission))
        if rule is None:
            return self._deny_context(
                context,
                permission=permission,
                risk_level=risk_level,
                reason_code="unknown_tool",
                message="The requested tool is not authorized.",
            )

        if rule.risk_level != risk_level:
            return self._deny_context(
                context,
                permission=permission,
                risk_level=risk_level,
                reason_code="invalid_context",
                message="Permission context is inconsistent.",
            )

        if rule.permission_required != context.permission_required:
            return self._deny_context(
                context,
                permission=permission,
                risk_level=risk_level,
                reason_code="invalid_context",
                message="Permission context is inconsistent.",
            )

        if not rule.allowed:
            return self._deny_context(
                context,
                permission=permission,
                risk_level=risk_level,
                reason_code="permission_denied",
                message="The requested action is not authorized.",
            )

        requires_confirmation = (
            rule.confirmation_required
            if rule.confirmation_required is not None
            else risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )
        if risk_level == RiskLevel.CRITICAL or (
            requires_confirmation
            and context.confirmation_state != ConfirmationState.CONFIRMED
        ):
            return AuthorizationResult(
                decision=PermissionDecision.CONFIRMATION_REQUIRED,
                tool_name=context.tool_name,
                permission=permission.value,
                risk_level=risk_level,
                reason_code="confirmation_required",
                message="Confirmation is required before this action can proceed.",
            )

        return AuthorizationResult(
            decision=PermissionDecision.ALLOW,
            tool_name=context.tool_name,
            permission=permission.value,
            risk_level=risk_level,
            reason_code="policy_allowed",
            message="The action is authorized by policy.",
        )

    @staticmethod
    def _deny_context(
        context: PermissionContext,
        *,
        permission: PermissionId | None = None,
        risk_level: RiskLevel | None = None,
        reason_code: str,
        message: str,
    ) -> AuthorizationResult:
        return PermissionPolicy._deny(
            tool_name=context.tool_name,
            permission=permission.value if permission else context.permission,
            risk_level=risk_level,
            reason_code=reason_code,
            message=message,
        )

    @staticmethod
    def _deny(
        *,
        tool_name: str,
        permission: str | None,
        risk_level: RiskLevel | None,
        reason_code: str,
        message: str,
    ) -> AuthorizationResult:
        return AuthorizationResult(
            decision=PermissionDecision.DENY,
            tool_name=tool_name,
            permission=permission,
            risk_level=risk_level,
            reason_code=reason_code,
            message=message,
        )


def default_permission_policy() -> PermissionPolicy:
    return PermissionPolicy(
        {
            ("system.echo", PermissionId.SYSTEM_ECHO): PermissionRule(
                allowed=True,
                risk_level=RiskLevel.LOW,
                permission_required=False,
            )
        }
    )
