from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class EvaluationCategory(str, Enum):
    ANSWER_QUALITY = "answer_quality"
    TOOL_AUTHORIZATION = "tool_authorization"
    WORKFLOW_CORRECTNESS = "workflow_correctness"
    MEMORY_CONVERSATION = "memory_conversation"
    RELIABILITY_ERROR = "reliability_error"


class CaseEvaluationResult(BaseModel):
    case_id: str
    suite: str
    category: EvaluationCategory
    name: str
    description: str
    passed: bool
    actual_output: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
    duration_ms: float = 0.0
    safety_critical: bool = False
    critical_invariant_violated: bool = False


class InvariantViolation(BaseModel):
    invariant_name: str
    case_id: str
    details: str


class EvaluationMetrics(BaseModel):
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    skipped_cases: int = 0
    pass_rate: float = 0.0

    # Category Pass Rates
    answer_quality_pass_rate: float = 0.0
    tool_authorization_pass_rate: float = 0.0
    workflow_correctness_pass_rate: float = 0.0
    memory_conversation_pass_rate: float = 0.0
    reliability_error_pass_rate: float = 0.0

    # Critical Safety Invariants (ALL MUST BE ZERO)
    unauthorized_tool_executions: int = 0
    critical_actions_silently_authorized: int = 0
    failed_actions_reported_as_success: int = 0
    secret_leakage_count: int = 0

    critical_invariants_satisfied: bool = True
    duration_seconds: float = 0.0


class EvaluationRunReport(BaseModel):
    framework_version: str = "1.0.0"
    dataset_version: str = "2026.10-v1"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    overall_status: str  # "PASSED" | "FAILED"
    selected_suite: str | None = None
    selected_category: str | None = None
    metrics: EvaluationMetrics
    invariant_violations: list[InvariantViolation] = Field(default_factory=list)
    results: list[CaseEvaluationResult] = Field(default_factory=list)

