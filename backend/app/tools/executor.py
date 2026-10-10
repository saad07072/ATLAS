from __future__ import annotations

import logging
from time import perf_counter

from pydantic import BaseModel

from backend.app.security.models import (
    AuthorizationResult,
    PermissionContext,
    PermissionDecision,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.tools.base import Tool
from backend.app.tools.errors import (
    ToolExecutionError,
    ToolFrameworkError,
    UnknownToolError,
)
from backend.app.tools.models import (
    ToolErrorInfo,
    ToolExecutionMetadata,
    ToolExecutionRequest,
    ToolResult,
)
from backend.app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutionService:
    def __init__(
        self,
        registry: ToolRegistry,
        permission_boundary: PermissionEngine,
    ) -> None:
        self.registry = registry
        self.permission_boundary = permission_boundary

    def execute(self, request: ToolExecutionRequest) -> ToolResult:
        started = perf_counter()
        tool_name = request.name
        tool = None
        authorization: AuthorizationResult | None = None
        try:
            tool = self.registry.get(request.name)
            validated_arguments = tool.validate_input(request.arguments)
            permission = str(tool.permission_id) if tool.permission_id else None
            context = (
                PermissionContext(
                    requested_action=permission,
                    tool_name=tool.name,
                    permission=permission,
                    risk_level=str(tool.risk_level),
                    permission_required=tool.permission_required,
                )
                if permission
                else None
            )
            evaluated_authorization = self.permission_boundary.evaluate(context)
            if not self._authorization_matches_context(evaluated_authorization, context):
                authorization = self._invalid_authorization(request.name)
            else:
                authorization = evaluated_authorization
            if authorization.decision != PermissionDecision.ALLOW:
                return self._authorization_failure(
                    request.name,
                    authorization,
                    started,
                )
            raw_result = tool.execute(validated_arguments)
            result = tool.validate_result(raw_result)
            if not isinstance(result, BaseModel):
                raise ToolExecutionError
            return ToolResult(
                success=True,
                tool_name=tool.name,
                output=result.model_dump(mode="json"),
                metadata=self._metadata(started),
                authorization=authorization,
            )
        except ToolFrameworkError as exc:
            if isinstance(exc, UnknownToolError):
                authorization = AuthorizationResult(
                    decision=PermissionDecision.DENY,
                    tool_name=request.name,
                    reason_code="unknown_tool",
                    message="The requested tool is not available.",
                )
                return self._authorization_failure(
                    request.name,
                    authorization,
                    started,
                    error_code="unknown_tool",
                )
            error = self._safe_error(tool, exc)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=error,
                metadata=self._metadata(started),
                authorization=authorization or self._invalid_authorization(tool_name),
            )
        except Exception:
            logger.error("Tool execution failed for registered tool %s", tool_name)
            error = self._safe_error(
                tool,
                ToolExecutionError(),
            )
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=error,
                metadata=self._metadata(started),
                authorization=authorization or self._invalid_authorization(tool_name),
            )

    @staticmethod
    def _metadata(started: float) -> ToolExecutionMetadata:
        return ToolExecutionMetadata(
            duration_ms=max(0.0, (perf_counter() - started) * 1000),
        )

    @staticmethod
    def _safe_error(
        tool: Tool | None,
        error: ToolFrameworkError,
    ) -> ToolErrorInfo:
        if tool is None:
            return ToolErrorInfo(code=error.code, message=error.safe_message)
        try:
            normalized = tool.error_handler(error)
            if not isinstance(normalized, ToolErrorInfo):
                raise TypeError("Tool error handlers must return ToolErrorInfo.")
            return normalized
        except Exception:
            logger.error("Tool error handler failed for registered tool %s", tool.name)
            return ToolErrorInfo(
                code="tool_error",
                message="The tool request could not be completed.",
            )

    def _authorization_failure(
        self,
        tool_name: str,
        authorization: AuthorizationResult,
        started: float,
        *,
        error_code: str | None = None,
    ) -> ToolResult:
        if error_code is not None:
            code = error_code
            message = "The requested tool is not available."
        elif authorization.decision == PermissionDecision.CONFIRMATION_REQUIRED:
            code = "confirmation_required"
            message = authorization.message
        else:
            code = "permission_denied"
            message = "The requested action is not authorized."
        return ToolResult(
            success=False,
            tool_name=tool_name,
            error=ToolErrorInfo(code=code, message=message),
            metadata=self._metadata(started),
            authorization=authorization,
        )

    @staticmethod
    def _invalid_authorization(tool_name: str) -> AuthorizationResult:
        return AuthorizationResult(
            decision=PermissionDecision.DENY,
            tool_name=tool_name,
            reason_code="invalid_authorization",
            message="Authorization could not be verified.",
        )

    @staticmethod
    def _authorization_matches_context(
        authorization: object,
        context: PermissionContext | None,
    ) -> bool:
        if not isinstance(authorization, AuthorizationResult):
            return False
        if context is None:
            return authorization.decision == PermissionDecision.DENY
        try:
            risk_level = RiskLevel(context.risk_level)
        except (TypeError, ValueError):
            return authorization.decision == PermissionDecision.DENY
        return (
            authorization.tool_name == context.tool_name
            and authorization.permission == context.permission
            and authorization.risk_level == risk_level
        )
