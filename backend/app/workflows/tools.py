from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.tools.base import Tool


class VerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    item: str = Field(min_length=1, max_length=200)
    expected_value: str = Field(min_length=1, max_length=1000)
    actual_value: str = Field(min_length=1, max_length=1000)


class VerifyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    item: str
    message: str


class VerifyTool(Tool):
    name = "system.verify"
    description = "Verifies that an execution output matches an expected condition."
    input_schema = VerifyInput
    output_schema = VerifyOutput
    permission_required = False
    permission_id = "test.record"
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, VerifyInput):
            raise TypeError("VerifyTool requires validated VerifyInput.")
        is_match = arguments.actual_value.strip() == arguments.expected_value.strip()
        return VerifyOutput(
            verified=is_match,
            item=arguments.item,
            message="Verification succeeded." if is_match else "Verification mismatch detected.",
        )


class DataExtractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=4000)
    field_name: str = Field(min_length=1, max_length=100)


class DataExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extracted_value: str
    field_name: str


class DataExtractionTool(Tool):
    name = "planner.extract"
    description = "Extracts structured parameters from input text."
    input_schema = DataExtractionInput
    output_schema = DataExtractionOutput
    permission_required = False
    permission_id = "test.record"
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, DataExtractionInput):
            raise TypeError("DataExtractionTool requires validated DataExtractionInput.")
        return DataExtractionOutput(
            extracted_value=arguments.text.strip(),
            field_name=arguments.field_name,
        )


class HighRiskActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action_name: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)


class HighRiskActionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_name: str
    status: str
    message: str


class HighRiskActionTool(Tool):
    name = "test.action.high_risk"
    description = "Simulates a sensitive high-risk action requiring mandatory user confirmation."
    input_schema = HighRiskActionInput
    output_schema = HighRiskActionOutput
    permission_required = True
    permission_id = "test.record"
    risk_level = "high"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, HighRiskActionInput):
            raise TypeError("HighRiskActionTool requires validated HighRiskActionInput.")
        return HighRiskActionOutput(
            action_name=arguments.action_name,
            status="executed",
            message=f"High risk action '{arguments.action_name}' executed after authorization.",
        )
