from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict


Role = Literal["user", "assistant", "system", "tool"]


class LLMUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LLMHealthStatus(BaseModel):
    provider: str
    healthy: bool
    model: str | None = None
    message: str | None = None


class LLMMessage(BaseModel):
    role: Role = "user"
    content: str


class LLMToolDefinition(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class LLMToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMToolResult(BaseModel):
    name: str
    content: str
    success: bool = True


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[LLMMessage] = Field(default_factory=list)
    system_instruction: str | None = None
    model: str | None = None
    temperature: float = 0.2
    max_output_tokens: int | None = None
    timeout: float | None = None
    tools: list[LLMToolDefinition] = Field(default_factory=list)


class LLMResponse(BaseModel):
    content: str = ""
    model: str = ""
    finish_reason: str | None = None
    usage: LLMUsage | None = None


class LLMStructuredRequest(LLMRequest):
    response_schema: dict[str, Any] | type[BaseModel] | None = None


class LLMStructuredResponse(LLMResponse):
    parsed: dict[str, Any] | None = None
