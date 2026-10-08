from __future__ import annotations

import logging
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel

from backend.app.tools.base import Tool
from backend.app.tools.errors import (
    ToolExecutionError,
    ToolFrameworkError,
    ToolPermissionDeniedError,
)
from backend.app.tools.models import (
    ToolErrorInfo,
    ToolExecutionMetadata,
    ToolExecutionRequest,
    ToolResult,
)
from backend.app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class PermissionBoundary(Protocol):
    def authorize(self, tool_name: str, permission_required: bool) -> None:
        """Raise ToolPermissionDeniedError when execution is not authorized."""


class DefaultPermissionBoundary:
    """Placeholder policy: only tools explicitly requiring no permission may run."""

    def authorize(self, tool_name: str, permission_required: bool) -> None:
        if permission_required:
            raise ToolPermissionDeniedError


class ToolExecutionService:
    def __init__(
        self,
        registry: ToolRegistry,
        permission_boundary: PermissionBoundary,
    ) -> None:
        self.registry = registry
        self.permission_boundary = permission_boundary

    def execute(self, request: ToolExecutionRequest) -> ToolResult:
        started = perf_counter()
        tool_name = request.name
        tool = None
        try:
            tool = self.registry.get(request.name)
            validated_arguments = tool.validate_input(request.arguments)
            self.permission_boundary.authorize(
                tool.name,
                tool.permission_required,
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
            )
        except ToolFrameworkError as exc:
            error = self._safe_error(tool, exc)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=error,
                metadata=self._metadata(started),
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
