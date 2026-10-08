from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ValidationError

from backend.app.tools.errors import (
    InvalidToolArgumentsError,
    InvalidToolResultError,
    ToolFrameworkError,
)
from backend.app.tools.models import ToolErrorInfo, ToolMetadata, ToolRiskLevel


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]
    permission_required: ClassVar[bool] = True
    risk_level: ClassVar[ToolRiskLevel] = "low"

    @abstractmethod
    def execute(self, arguments: BaseModel) -> BaseModel:
        """Execute validated arguments and return an output model."""

    def validate_input(self, arguments: dict[str, object]) -> BaseModel:
        try:
            return self.input_schema.model_validate(arguments)
        except ValidationError as exc:
            raise InvalidToolArgumentsError from exc

    def validate_result(self, result: object) -> BaseModel:
        try:
            return self.output_schema.model_validate(result)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidToolResultError from exc

    def error_handler(self, error: Exception) -> ToolErrorInfo:
        if isinstance(error, ToolFrameworkError):
            code, message = error.code, error.safe_message
        else:
            code, message = "execution_failed", "The tool could not complete the request."
        return ToolErrorInfo(code=code, message=message)

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema.model_json_schema(),
            permission_required=self.permission_required,
            risk_level=self.risk_level,
        )
