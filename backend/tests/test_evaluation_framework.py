from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.app.evaluation.models import (
    CaseEvaluationResult,
    EvaluationCategory,
    EvaluationRunReport,
)
from backend.app.evaluation.runner import EvaluationRunner
from backend.app.evaluation.suites.answer_quality import run_answer_quality_suite
from backend.app.evaluation.suites.memory_conversation import run_memory_conversation_suite
from backend.app.evaluation.suites.reliability_error import run_reliability_error_suite
from backend.app.evaluation.suites.tool_authorization import run_tool_authorization_suite
from backend.app.evaluation.suites.workflow_correctness import run_workflow_correctness_suite


class EvaluationFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_answer_quality_suite_deterministic(self) -> None:
        results = run_answer_quality_suite()
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertTrue(r.passed, f"Case {r.case_id} failed: {r.failure_reason}")
            self.assertEqual(r.category, EvaluationCategory.ANSWER_QUALITY)

    def test_tool_authorization_suite_deterministic(self) -> None:
        results = run_tool_authorization_suite()
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertTrue(r.passed, f"Case {r.case_id} failed: {r.failure_reason}")
            self.assertEqual(r.category, EvaluationCategory.TOOL_AUTHORIZATION)

    def test_workflow_correctness_suite_deterministic(self) -> None:
        results = run_workflow_correctness_suite()
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertTrue(r.passed, f"Case {r.case_id} failed: {r.failure_reason}")
            self.assertEqual(r.category, EvaluationCategory.WORKFLOW_CORRECTNESS)

    def test_memory_conversation_suite_deterministic(self) -> None:
        results = run_memory_conversation_suite()
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertTrue(r.passed, f"Case {r.case_id} failed: {r.failure_reason}")
            self.assertEqual(r.category, EvaluationCategory.MEMORY_CONVERSATION)

    def test_reliability_error_suite_deterministic(self) -> None:
        results = run_reliability_error_suite()
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertTrue(r.passed, f"Case {r.case_id} failed: {r.failure_reason}")
            self.assertEqual(r.category, EvaluationCategory.RELIABILITY_ERROR)

    def test_full_evaluation_runner_execution(self) -> None:
        runner = EvaluationRunner(output_dir=self.temp_dir)
        report = runner.run()

        self.assertEqual(report.overall_status, "PASSED")
        self.assertTrue(report.metrics.critical_invariants_satisfied)
        self.assertEqual(report.metrics.unauthorized_tool_executions, 0)
        self.assertEqual(report.metrics.critical_actions_silently_authorized, 0)
        self.assertEqual(report.metrics.failed_actions_reported_as_success, 0)
        self.assertEqual(report.metrics.secret_leakage_count, 0)
        self.assertEqual(report.metrics.failed_cases, 0)
        self.assertEqual(report.metrics.pass_rate, 100.0)

        # Verify report file generation
        report_file, latest_file = runner.save_report(report)
        self.assertTrue(report_file.exists())
        self.assertTrue(latest_file.exists())

        loaded_json = json.loads(report_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded_json["overall_status"], "PASSED")
        self.assertEqual(len(loaded_json["results"]), len(report.results))

    def test_runner_suite_filtering(self) -> None:
        runner = EvaluationRunner(
            output_dir=self.temp_dir,
            selected_suite="answer_quality",
        )
        report = runner.run()
        self.assertEqual(report.overall_status, "PASSED")
        self.assertTrue(all(r.category == EvaluationCategory.ANSWER_QUALITY for r in report.results))
        self.assertEqual(report.selected_suite, "answer_quality")

    def test_critical_safety_violation_forces_failing_status(self) -> None:
        runner = EvaluationRunner(output_dir=self.temp_dir)
        # Simulate a mock evaluation result with a critical invariant violation
        simulated_results = [
            CaseEvaluationResult(
                case_id="TA-02",
                suite="tool_selection_and_authorization",
                category=EvaluationCategory.TOOL_AUTHORIZATION,
                name="Unknown tool execution rejection",
                description="Simulated violation",
                passed=False,
                failure_reason="Unknown tool executed without authorization",
                safety_critical=True,
                critical_invariant_violated=True,
            )
        ]

        metrics, violations = runner._calculate_metrics(simulated_results, 0.1)
        self.assertFalse(metrics.critical_invariants_satisfied)
        self.assertEqual(metrics.unauthorized_tool_executions, 1)
        self.assertEqual(len(violations), 1)

        simulated_report = EvaluationRunReport(
            overall_status="PASSED" if (metrics.failed_cases == 0 and metrics.critical_invariants_satisfied) else "FAILED",
            metrics=metrics,
            invariant_violations=violations,
            results=simulated_results,
        )
        self.assertEqual(simulated_report.overall_status, "FAILED")

    def test_secret_leakage_and_fallback_critical_violations(self) -> None:
        runner = EvaluationRunner(output_dir=self.temp_dir)
        simulated_results = [
            CaseEvaluationResult(
                case_id="MC-05",
                suite="memory_and_conversation_safeguards",
                category=EvaluationCategory.MEMORY_CONVERSATION,
                name="Multi-tenant memory isolation enforcement",
                description="Simulated tenant breach",
                passed=False,
                failure_reason="Cross-tenant memory leakage detected.",
                safety_critical=True,
                critical_invariant_violated=True,
            ),
            CaseEvaluationResult(
                case_id="CUSTOM-99",
                suite="custom_suite",
                category=EvaluationCategory.RELIABILITY_ERROR,
                name="Unmapped critical safety violation",
                description="Simulated unmapped critical failure",
                passed=False,
                failure_reason="Unexpected safety bypass.",
                safety_critical=True,
                critical_invariant_violated=True,
            ),
        ]

        metrics, violations = runner._calculate_metrics(simulated_results, 0.1)
        self.assertFalse(metrics.critical_invariants_satisfied)
        self.assertEqual(metrics.secret_leakage_count, 1)
        self.assertEqual(metrics.unauthorized_tool_executions, 1)
        self.assertEqual(len(violations), 2)


if __name__ == "__main__":
    unittest.main()

