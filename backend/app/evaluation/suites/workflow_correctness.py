from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from backend.app.evaluation.models import (
    CaseEvaluationResult,
    EvaluationCategory,
)
from backend.app.security.models import (
    PermissionId,
    RiskLevel,
)
from backend.app.security.permissions import PermissionEngine
from backend.app.security.policy import PermissionPolicy, PermissionRule
from backend.app.tools.demo import EchoTool
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.registry import ToolRegistry
from backend.app.workflows.engine import WorkflowConflictError, WorkflowEngine
from backend.app.workflows.errors import WorkflowValidationError
from backend.app.workflows.models import (
    StepStatus,
    StepVerificationStatus,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStepDefinition,
)
from backend.app.workflows.repository import InMemoryWorkflowRepository
from backend.app.workflows.tools import HighRiskActionTool, VerifyTool
from backend.app.workflows.validator import WorkflowValidator


def _setup_workflow_engine() -> tuple[WorkflowEngine, WorkflowValidator, InMemoryWorkflowRepository]:
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(VerifyTool())
    registry.register(HighRiskActionTool())

    policy = PermissionPolicy({
        ("system.echo", PermissionId.SYSTEM_ECHO.value): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.LOW,
            permission_required=False,
        ),
        ("system.verify", PermissionId.TEST_RECORD.value): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.LOW,
            permission_required=False,
        ),
        ("test.action.high_risk", PermissionId.TEST_RECORD.value): PermissionRule(
            allowed=True,
            risk_level=RiskLevel.HIGH,
            permission_required=True,
            confirmation_required=True,
        ),
    })

    permission_engine = PermissionEngine(policy)
    executor = ToolExecutionService(registry, permission_engine)
    repo = InMemoryWorkflowRepository()
    validator = WorkflowValidator(registry)
    engine = WorkflowEngine(repo, executor, permission_engine)
    return engine, validator, repo


def run_workflow_correctness_suite() -> list[CaseEvaluationResult]:
    results: list[CaseEvaluationResult] = []
    category = EvaluationCategory.WORKFLOW_CORRECTNESS
    suite_name = "workflow_correctness"

    # WC-01: Valid Multi-step DAG Execution Order
    t0 = perf_counter()
    engine, validator, repo = _setup_workflow_engine()
    user_id = str(uuid4())
    wf_def = WorkflowDefinition(
        title="Valid Linear Pipeline",
        user_request="Process data sequentially",
        steps=[
            WorkflowStepDefinition(
                step_id="step_1",
                title="First Step",
                tool_name="system.echo",
                arguments={"message": "step1_output"},
                dependencies=[],
            ),
            WorkflowStepDefinition(
                step_id="step_2",
                title="Second Step",
                tool_name="system.echo",
                arguments={"message": "step2_output"},
                dependencies=["step_1"],
            ),
        ],
    )
    record, _ = validator.validate_plan(wf_def, user_id=user_id)
    repo.create(record)
    executed = engine.execute_workflow(user_id, record.id)
    duration = (perf_counter() - t0) * 1000

    step_1 = next(s for s in executed.steps if s.step_id == "step_1")
    step_2 = next(s for s in executed.steps if s.step_id == "step_2")
    passed = (
        executed.status == WorkflowStatus.COMPLETED
        and step_1.status == StepStatus.COMPLETED
        and step_2.status == StepStatus.COMPLETED
        and step_1.completed_at is not None
        and step_2.completed_at is not None
        and step_1.completed_at <= step_2.completed_at
    )
    results.append(
        CaseEvaluationResult(
            case_id="WC-01",
            suite=suite_name,
            category=category,
            name="Valid multi-step DAG execution ordering",
            description="Evaluates that multi-step workflows execute strictly in dependency topological order.",
            passed=passed,
            actual_output={"workflow_status": executed.status.value, "steps": [s.status.value for s in executed.steps]},
            failure_reason=None if passed else "Workflow did not execute in correct sequential order.",
            duration_ms=round(duration, 2),
            safety_critical=False,
            critical_invariant_violated=False,
        )
    )

    # WC-02: Circular Dependency Detection
    t0 = perf_counter()
    _, validator, _ = _setup_workflow_engine()
    cycle_def = WorkflowDefinition(
        title="Cyclic Pipeline",
        user_request="Attempt cyclic dependencies",
        steps=[
            WorkflowStepDefinition(
                step_id="step_a",
                title="Step A",
                tool_name="system.echo",
                arguments={"message": "a"},
                dependencies=["step_b"],
            ),
            WorkflowStepDefinition(
                step_id="step_b",
                title="Step B",
                tool_name="system.echo",
                arguments={"message": "b"},
                dependencies=["step_a"],
            ),
        ],
    )
    cycle_rejected = False
    try:
        validator.validate_plan(cycle_def, user_id="test_user")
    except WorkflowValidationError:
        cycle_rejected = True
    duration = (perf_counter() - t0) * 1000

    results.append(
        CaseEvaluationResult(
            case_id="WC-02",
            suite=suite_name,
            category=category,
            name="Cyclic DAG validation rejection",
            description="Evaluates that circular dependencies are caught and rejected prior to execution.",
            passed=cycle_rejected,
            actual_output={"cycle_rejected": cycle_rejected},
            failure_reason=None if cycle_rejected else "Cyclic workflow was not rejected by validator.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=not cycle_rejected,
        )
    )

    # WC-03: Missing Dependency Validation Rejection
    t0 = perf_counter()
    _, validator, _ = _setup_workflow_engine()
    missing_dep_def = WorkflowDefinition(
        title="Missing Dep Pipeline",
        user_request="Invalid dependency reference",
        steps=[
            WorkflowStepDefinition(
                step_id="step_x",
                title="Step X",
                tool_name="system.echo",
                arguments={"message": "x"},
                dependencies=["non_existent_step_id"],
            ),
        ],
    )
    missing_rejected = False
    try:
        validator.validate_plan(missing_dep_def, user_id="test_user")
    except WorkflowValidationError:
        missing_rejected = True
    duration = (perf_counter() - t0) * 1000

    results.append(
        CaseEvaluationResult(
            case_id="WC-03",
            suite=suite_name,
            category=category,
            name="Missing dependency validation rejection",
            description="Evaluates that references to non-existent step IDs are rejected before execution.",
            passed=missing_rejected,
            actual_output={"missing_rejected": missing_rejected},
            failure_reason=None if missing_rejected else "Missing dependency was not rejected by validator.",
            duration_ms=round(duration, 2),
            safety_critical=False,
            critical_invariant_violated=False,
        )
    )

    # WC-04: Failure Propagation and Truthful Non-Completion Outcome
    t0 = perf_counter()
    engine, validator, repo = _setup_workflow_engine()
    user_id = str(uuid4())
    # Step 1: verify failure; Step 2 depends on Step 1
    fail_def = WorkflowDefinition(
        title="Failure Cascade Test",
        user_request="Test failure propagation",
        steps=[
            WorkflowStepDefinition(
                step_id="step_fail",
                title="Failing Step",
                tool_name="system.echo",
                arguments={"message": "fail"},
            ),
            WorkflowStepDefinition(
                step_id="step_dependent",
                title="Dependent Step",
                tool_name="system.echo",
                arguments={"message": "should_be_skipped"},
                dependencies=["step_fail"],
            ),
        ],
    )
    record, _ = validator.validate_plan(fail_def, user_id=user_id)
    repo.create(record)
    # Artificially set step_fail to FAILED to simulate failure propagation
    repo.update_step(user_id, record.id, "step_fail", status=StepStatus.FAILED)
    executed = engine.execute_workflow(user_id, record.id)
    duration = (perf_counter() - t0) * 1000

    step_dep = next(s for s in executed.steps if s.step_id == "step_dependent")
    passed = (
        executed.status in {WorkflowStatus.FAILED, WorkflowStatus.PARTIALLY_COMPLETED}
        and executed.status != WorkflowStatus.COMPLETED  # MUST NEVER BE COMPLETED!
        and step_dep.status == StepStatus.SKIPPED
    )
    critical_violated = executed.status == WorkflowStatus.COMPLETED
    results.append(
        CaseEvaluationResult(
            case_id="WC-04",
            suite=suite_name,
            category=category,
            name="Failure cascade and truthful outcome reporting",
            description="Evaluates that prerequisite failures prevent dependent execution and report truthful status.",
            passed=passed,
            actual_output={"workflow_status": executed.status.value, "dependent_status": step_dep.status.value},
            failure_reason=None if passed else "Failed workflow was falsely marked completed or dependent was executed.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=critical_violated,
        )
    )

    # WC-05: High-Risk Step Pauses for Confirmation
    t0 = perf_counter()
    engine, validator, repo = _setup_workflow_engine()
    user_id = str(uuid4())
    pause_def = WorkflowDefinition(
        title="Confirmation Gate Test",
        user_request="Requires confirmation",
        steps=[
            WorkflowStepDefinition(
                step_id="step_high_risk",
                title="High Risk Action",
                tool_name="test.action.high_risk",
                arguments={"action_name": "reboot", "parameters": {"target": "server"}},
            ),
        ],
    )
    record, _ = validator.validate_plan(pause_def, user_id=user_id)
    repo.create(record)
    executed = engine.execute_workflow(user_id, record.id)
    duration = (perf_counter() - t0) * 1000

    step = executed.steps[0]
    passed = (
        executed.status == WorkflowStatus.WAITING_FOR_CONFIRMATION
        and step.status == StepStatus.WAITING_FOR_CONFIRMATION
        and step.confirmation_hash is not None
    )
    critical_violated = step.status == StepStatus.COMPLETED
    results.append(
        CaseEvaluationResult(
            case_id="WC-05",
            suite=suite_name,
            category=category,
            name="High-risk workflow step confirmation gating",
            description="Evaluates that workflows pause execution and request user approval when encountering high-risk steps.",
            passed=passed,
            actual_output={"status": executed.status.value, "step_status": step.status.value},
            failure_reason=None if passed else "Workflow did not pause for confirmation on high-risk step.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=critical_violated,
        )
    )

    # WC-06: Confirmation Replay Prevention
    t0 = perf_counter()
    engine, validator, repo = _setup_workflow_engine()
    user_id = str(uuid4())
    replay_def = WorkflowDefinition(
        title="Replay Test",
        user_request="Test replay",
        steps=[
            WorkflowStepDefinition(
                step_id="step_hr",
                title="HR Step",
                tool_name="test.action.high_risk",
                arguments={"action_name": "clean", "parameters": {"target": "cache"}},
            ),
        ],
    )
    record, _ = validator.validate_plan(replay_def, user_id=user_id)
    repo.create(record)
    engine.execute_workflow(user_id, record.id)

    # Confirm once -> succeeds
    engine.confirm_step(user_id, record.id, "step_hr", decision="confirm")

    # Attempt re-confirmation of already confirmed step -> MUST FAIL
    replay_blocked = False
    try:
        engine.confirm_step(user_id, record.id, "step_hr", decision="confirm")
    except WorkflowConflictError:
        replay_blocked = True
    duration = (perf_counter() - t0) * 1000

    results.append(
        CaseEvaluationResult(
            case_id="WC-06",
            suite=suite_name,
            category=category,
            name="Workflow confirmation replay prevention",
            description="Evaluates that confirmed steps reject duplicate confirmation attempts (HTTP 409 conflict).",
            passed=replay_blocked,
            actual_output={"replay_blocked": replay_blocked},
            failure_reason=None if replay_blocked else "Step allowed duplicate confirmation replay.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=not replay_blocked,
        )
    )

    # WC-07: Truthful Verification Outcome Reporting
    t0 = perf_counter()
    engine, validator, repo = _setup_workflow_engine()
    user_id = str(uuid4())
    verify_def = WorkflowDefinition(
        title="Verification Outcome Test",
        user_request="Verify mismatch detection",
        steps=[
            WorkflowStepDefinition(
                step_id="step_verify",
                title="Verification Step",
                tool_name="system.verify",
                arguments={"item": "report_checksum", "expected_value": "checksum_A", "actual_value": "checksum_B"},
            ),
        ],
    )
    record, _ = validator.validate_plan(verify_def, user_id=user_id)
    repo.create(record)
    executed = engine.execute_workflow(user_id, record.id)
    duration = (perf_counter() - t0) * 1000

    step_v = executed.steps[0]
    passed = (
        step_v.verification_status == StepVerificationStatus.FAILED
        and "mismatch" in (step_v.verification_details or "").lower()
    )
    critical_violated = step_v.verification_status == StepVerificationStatus.VERIFIED
    results.append(
        CaseEvaluationResult(
            case_id="WC-07",
            suite=suite_name,
            category=category,
            name="Truthful verification outcome reporting",
            description="Evaluates that tool verification failures are reported accurately and never falsely verified.",
            passed=passed,
            actual_output={"verification_status": step_v.verification_status.value if step_v.verification_status else None},
            failure_reason=None if passed else "Verification mismatch was not recorded as failed.",
            duration_ms=round(duration, 2),
            safety_critical=True,
            critical_invariant_violated=critical_violated,
        )
    )

    return results
