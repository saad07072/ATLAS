from pydantic import BaseModel, ConfigDict, Field

from backend.app.tools.base import Tool
from backend.app.tools.executor import DefaultPermissionBoundary, ToolExecutionService
from backend.app.tools.registry import ToolRegistry


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1, max_length=1000)


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1000)


class EchoTool(Tool):
    name = "system.echo"
    description = "Returns the supplied message unchanged."
    input_schema = EchoInput
    output_schema = EchoOutput
    permission_required = False
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, EchoInput):
            raise TypeError("EchoTool requires validated EchoInput.")
        return EchoOutput(message=arguments.message)


def create_demo_tool_service() -> ToolExecutionService:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return ToolExecutionService(registry, DefaultPermissionBoundary())
