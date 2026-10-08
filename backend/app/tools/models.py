from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.security.models import AuthorizationResult


ToolRiskLevel = Literal["low", "medium", "high", "critical"]


class ToolErrorInfo(BaseModel):
    code: str
    message: str


class ToolExecutionMetadata(BaseModel):
    duration_ms: float = Field(ge=0)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    tool_name: str
    output: dict[str, Any] | None = None
    error: ToolErrorInfo | None = None
    metadata: ToolExecutionMetadata
    authorization: AuthorizationResult | None = None


class ToolMetadata(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    permission_required: bool
    permission_id: str | None = None
    risk_level: ToolRiskLevel


class ToolExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    arguments: dict[str, Any] = Field(default_factory=dict)
