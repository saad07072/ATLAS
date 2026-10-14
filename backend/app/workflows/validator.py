from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import Any

from backend.app.memory.models import contains_secret
from backend.app.security.models import (
    ConfirmationState,
    PermissionId,
    RiskLevel,
)
from backend.app.tools.errors import InvalidToolArgumentsError, UnknownToolError
from backend.app.tools.registry import ToolRegistry
from backend.app.workflows.errors import (
    CycleDetectedError,
    WorkflowValidationError,
)
from backend.app.workflows.models import (
    StepStatus,
    WorkflowDefinition,
    WorkflowRecord,
    WorkflowStepDefinition,
    WorkflowStepRecord,
)

MAX_STEPS_PER_WORKFLOW = 20
MAX_ARGUMENT_JSON_BYTES = 16384


def compute_confirmation_hash(
    user_id: str,
    workflow_id: str,
    step_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Computes a deterministic cryptographic hash binding a confirmation to its exact context."""
    serialized_args = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    payload = f"{user_id}:{workflow_id}:{step_id}:{tool_name}:{serialized_args}".encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


class WorkflowValidator:
    def __init__(self, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def validate_plan(
        self,
        definition: WorkflowDefinition,
        *,
        user_id: str,
    ) -> tuple[WorkflowRecord, list[str]]:
        """
        Validates the entire workflow plan:
        1. Checks for credentials or secrets in input.
        2. Validates step uniqueness and limits.
        3. Checks DAG dependencies and detects cycles.
        4. Validates each step's tool and arguments against the trusted tool registry.
        5. Derives trusted risk levels and permission requirements.
        Returns the initial WorkflowRecord and the topologically sorted step_ids.
        """
        if contains_secret(definition.title) or contains_secret(definition.user_request):
            raise WorkflowValidationError("Workflow metadata must not contain credentials or secret tokens.")

        if len(definition.steps) > MAX_STEPS_PER_WORKFLOW:
            raise WorkflowValidationError(
                f"Workflow exceeds maximum limit of {MAX_STEPS_PER_WORKFLOW} steps."
            )

        step_ids = [s.step_id for s in definition.steps]
        if len(step_ids) != len(set(step_ids)):
            raise WorkflowValidationError("Workflow step IDs must be unique within the workflow.")

        known_step_ids = set(step_ids)

        # Build dependency graph
        in_degrees: dict[str, int] = {sid: 0 for sid in step_ids}
        adj_list: dict[str, list[str]] = defaultdict(list)

        for step in definition.steps:
            for dep in step.dependencies:
                if dep == step.step_id:
                    raise WorkflowValidationError(f"Step '{step.step_id}' cannot depend on itself.")
                if dep not in known_step_ids:
                    raise WorkflowValidationError(
                        f"Step '{step.step_id}' references unknown dependency '{dep}'."
                    )
                adj_list[dep].append(step.step_id)
                in_degrees[step.step_id] += 1

        # Cycle detection via topological sort (Kahn's algorithm)
        queue: deque[str] = deque([sid for sid, deg in in_degrees.items() if deg == 0])
        topological_order: list[str] = []

        while queue:
            curr = queue.popleft()
            topological_order.append(curr)
            for neighbor in adj_list[curr]:
                in_degrees[neighbor] -= 1
                if in_degrees[neighbor] == 0:
                    queue.append(neighbor)

        if len(topological_order) != len(step_ids):
            # Find cycle nodes
            cycle_nodes = [sid for sid, deg in in_degrees.items() if deg > 0]
            raise CycleDetectedError(cycle_nodes)

        # Validate each step against trusted tool registry
        workflow_id = None  # Will be generated on record creation
        step_records: list[WorkflowStepRecord] = []

        for order, step_id in enumerate(topological_order):
            step_def = next(s for s in definition.steps if s.step_id == step_id)
            step_record = self._validate_and_build_step_record(
                step_def,
                step_order=order,
            )
            step_records.append(step_record)

        workflow_record = WorkflowRecord(
            user_id=user_id,
            conversation_id=definition.conversation_id,
            title=definition.title.strip(),
            user_request=definition.user_request.strip(),
            step_count=len(step_records),
            steps=step_records,
        )

        # Update step records with the generated workflow_id
        for step in workflow_record.steps:
            step.workflow_id = workflow_record.id

        return workflow_record, topological_order

    def _validate_and_build_step_record(
        self,
        step_def: WorkflowStepDefinition,
        step_order: int,
    ) -> WorkflowStepRecord:
        # Check argument size and secrets
        raw_args_str = json.dumps(step_def.arguments, ensure_ascii=False)
        if len(raw_args_str.encode("utf-8")) > MAX_ARGUMENT_JSON_BYTES:
            raise WorkflowValidationError(
                f"Arguments for step '{step_def.step_id}' exceed size limit of {MAX_ARGUMENT_JSON_BYTES} bytes."
            )
        if contains_secret(raw_args_str):
            raise WorkflowValidationError(
                f"Arguments for step '{step_def.step_id}' must not contain secret tokens or credentials."
            )

        # Tool registry resolution
        try:
            tool = self.tool_registry.get(step_def.tool_name)
        except UnknownToolError:
            raise WorkflowValidationError(
                f"Step '{step_def.step_id}' references unknown tool '{step_def.tool_name}'."
            )

        # Validate arguments using tool's input schema
        try:
            tool.validate_input(step_def.arguments)
        except InvalidToolArgumentsError as exc:
            raise WorkflowValidationError(
                f"Step '{step_def.step_id}' has invalid arguments for tool '{step_def.tool_name}'."
            ) from exc

        # Derive trusted risk and permission metadata directly from the tool
        risk_level = RiskLevel(tool.risk_level)
        permission_required = tool.permission_required

        requires_confirmation = (
            risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )

        return WorkflowStepRecord(
            workflow_id="",  # Bound in caller
            step_id=step_def.step_id,
            step_order=step_order,
            title=step_def.title.strip(),
            tool_name=tool.name,
            arguments=dict(step_def.arguments),
            dependencies=list(step_def.dependencies),
            status=StepStatus.PENDING,
            max_retries=step_def.max_retries,
            risk_level=risk_level,
            permission_required=permission_required,
            confirmation_state=(
                ConfirmationState.PENDING
                if requires_confirmation
                else ConfirmationState.NOT_REQUESTED
            ),
        )

