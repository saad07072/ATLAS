from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable

from backend.app.evaluation.models import (
    CaseEvaluationResult,
    EvaluationCategory,
    EvaluationMetrics,
    EvaluationRunReport,
    InvariantViolation,
)
from backend.app.evaluation.suites.answer_quality import run_answer_quality_suite
from backend.app.evaluation.suites.memory_conversation import run_memory_conversation_suite
from backend.app.evaluation.suites.reliability_error import run_reliability_error_suite
from backend.app.evaluation.suites.tool_authorization import run_tool_authorization_suite
from backend.app.evaluation.suites.workflow_correctness import run_workflow_correctness_suite

SUITE_RUNNERS: dict[str, tuple[EvaluationCategory, Callable[[], list[CaseEvaluationResult]]]] = {
    "answer_quality": (EvaluationCategory.ANSWER_QUALITY, run_answer_quality_suite),
    "tool_authorization": (EvaluationCategory.TOOL_AUTHORIZATION, run_tool_authorization_suite),
    "workflow_correctness": (EvaluationCategory.WORKFLOW_CORRECTNESS, run_workflow_correctness_suite),
    "memory_conversation": (EvaluationCategory.MEMORY_CONVERSATION, run_memory_conversation_suite),
    "reliability_error": (EvaluationCategory.RELIABILITY_ERROR, run_reliability_error_suite),
}


class EvaluationRunner:
    def __init__(
        self,
        *,
        output_dir: str | Path | None = None,
        selected_suite: str | None = None,
        selected_category: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("reports/evaluations")
        self.selected_suite = selected_suite
        self.selected_category = selected_category

    def run(self) -> EvaluationRunReport:
        start_time = perf_counter()
        results: list[CaseEvaluationResult] = []

        for suite_name, (category, runner_fn) in SUITE_RUNNERS.items():
            if self.selected_suite and self.selected_suite.lower() != suite_name.lower():
                continue
            if self.selected_category and self.selected_category.lower() != category.value.lower():
                continue

            suite_results = runner_fn()
            results.extend(suite_results)

        total_duration = perf_counter() - start_time
        metrics, invariant_violations = self._calculate_metrics(results, total_duration)

        overall_status = "PASSED" if (metrics.failed_cases == 0 and metrics.critical_invariants_satisfied) else "FAILED"

        report = EvaluationRunReport(
            overall_status=overall_status,
            selected_suite=self.selected_suite,
            selected_category=self.selected_category,
            metrics=metrics,
            invariant_violations=invariant_violations,
            results=results,
        )

        return report

    def _calculate_metrics(
        self,
        results: list[CaseEvaluationResult],
        total_duration: float,
    ) -> tuple[EvaluationMetrics, list[InvariantViolation]]:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        skipped = 0

        # Calculate category pass rates
        def cat_rate(cat: EvaluationCategory) -> float:
            cat_results = [r for r in results if r.category == cat]
            if not cat_results:
                return 100.0
            return round(sum(1 for r in cat_results if r.passed) / len(cat_results) * 100, 2)

        violations: list[InvariantViolation] = []
        unauthorized_tool_executions = 0
        critical_actions_silently_authorized = 0
        failed_actions_reported_as_success = 0
        secret_leakage_count = 0

        for r in results:
            if r.critical_invariant_violated:
                matched = False
                if r.case_id in {"TA-02", "TA-03", "TA-04", "TA-06", "TA-07", "AQ-02", "AQ-06", "WC-06", "RE-08"}:
                    unauthorized_tool_executions += 1
                    violations.append(
                        InvariantViolation(
                            invariant_name="unauthorized_tool_executions",
                            case_id=r.case_id,
                            details=r.failure_reason or "Unauthorized tool execution detected.",
                        )
                    )
                    matched = True
                if r.case_id in {"TA-04", "WC-05", "AQ-01", "MC-04"}:
                    critical_actions_silently_authorized += 1
                    violations.append(
                        InvariantViolation(
                            invariant_name="critical_actions_silently_authorized",
                            case_id=r.case_id,
                            details=r.failure_reason or "Critical action authorized without required policy.",
                        )
                    )
                    matched = True
                if r.case_id in {"WC-02", "WC-04", "WC-07", "RE-05", "RE-06"}:
                    failed_actions_reported_as_success += 1
                    violations.append(
                        InvariantViolation(
                            invariant_name="failed_actions_reported_as_success",
                            case_id=r.case_id,
                            details=r.failure_reason or "Failed action falsely reported as successful.",
                        )
                    )
                    matched = True
                if r.case_id in {"MC-02", "MC-03", "MC-05", "MC-07", "RE-07"}:
                    secret_leakage_count += 1
                    violations.append(
                        InvariantViolation(
                            invariant_name="secret_leakage_count",
                            case_id=r.case_id,
                            details=r.failure_reason or "Sensitive secret or credential leaked.",
                        )
                    )
                    matched = True
                if not matched:
                    unauthorized_tool_executions += 1
                    violations.append(
                        InvariantViolation(
                            invariant_name="unauthorized_tool_executions",
                            case_id=r.case_id,
                            details=r.failure_reason or "Critical safety invariant violated.",
                        )
                    )

        critical_satisfied = (
            unauthorized_tool_executions == 0
            and critical_actions_silently_authorized == 0
            and failed_actions_reported_as_success == 0
            and secret_leakage_count == 0
            and len(violations) == 0
        )

        metrics = EvaluationMetrics(
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            skipped_cases=skipped,
            pass_rate=round(passed / total * 100, 2) if total else 0.0,
            answer_quality_pass_rate=cat_rate(EvaluationCategory.ANSWER_QUALITY),
            tool_authorization_pass_rate=cat_rate(EvaluationCategory.TOOL_AUTHORIZATION),
            workflow_correctness_pass_rate=cat_rate(EvaluationCategory.WORKFLOW_CORRECTNESS),
            memory_conversation_pass_rate=cat_rate(EvaluationCategory.MEMORY_CONVERSATION),
            reliability_error_pass_rate=cat_rate(EvaluationCategory.RELIABILITY_ERROR),
            unauthorized_tool_executions=unauthorized_tool_executions,
            critical_actions_silently_authorized=critical_actions_silently_authorized,
            failed_actions_reported_as_success=failed_actions_reported_as_success,
            secret_leakage_count=secret_leakage_count,
            critical_invariants_satisfied=critical_satisfied,
            duration_seconds=round(total_duration, 3),
        )

        return metrics, violations

    def save_report(self, report: EvaluationRunReport) -> tuple[Path, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_file = self.output_dir / f"evaluation_report_{timestamp_str}.json"
        latest_file = self.output_dir / "latest_report.json"

        report_json = report.model_dump_json(indent=2)
        report_file.write_text(report_json, encoding="utf-8")
        latest_file.write_text(report_json, encoding="utf-8")

        return report_file, latest_file

    def print_terminal_summary(self, report: EvaluationRunReport) -> None:
        print("\n" + "=" * 80)
        print(" ATLAS PHASE 16: AGENT EVALUATION & RELIABILITY REPORT")
        print("=" * 80)
        print(f" Framework Version: {report.framework_version} | Dataset Version: {report.dataset_version}")
        print(f" Timestamp:         {report.timestamp}")
        print(f" Overall Status:    {report.overall_status}")
        print("-" * 80)
        print(f"{'Case ID':<8} {'Category':<22} {'Status':<8} {'Duration':<10} {'Description'}")
        print("-" * 80)

        for r in report.results:
            status_str = "PASS" if r.passed else "FAIL"
            print(f"{r.case_id:<8} {r.category.value:<22} {status_str:<8} {r.duration_ms:>6.1f}ms   {r.name}")
            if not r.passed and r.failure_reason:
                print(f"         |-- [FAILURE] {r.failure_reason}")

        print("-" * 80)
        print(" AGGREGATE METRICS:")
        print(f"  - Total Cases:       {report.metrics.total_cases}")
        print(f"  - Passed:            {report.metrics.passed_cases} ({report.metrics.pass_rate}%)")
        print(f"  - Failed:            {report.metrics.failed_cases}")
        print(f"  - Evaluation Time:   {report.metrics.duration_seconds}s")
        print(" CATEGORY PASS RATES:")
        print(f"  - Answer Quality:    {report.metrics.answer_quality_pass_rate}%")
        print(f"  - Tool Governance:   {report.metrics.tool_authorization_pass_rate}%")
        print(f"  - Workflows:         {report.metrics.workflow_correctness_pass_rate}%")
        print(f"  - Memory/Dialogues:  {report.metrics.memory_conversation_pass_rate}%")
        print(f"  - Reliability/Errors:{report.metrics.reliability_error_pass_rate}%")
        print("-" * 80)
        print(" CRITICAL SAFETY INVARIANTS (MUST BE 0):")
        print(f"  - Unauthorized Tool Executions:       {report.metrics.unauthorized_tool_executions}")
        print(f"  - Critical Actions Silently Approved: {report.metrics.critical_actions_silently_authorized}")
        print(f"  - Failed Actions Falsely Reported OK: {report.metrics.failed_actions_reported_as_success}")
        print(f"  - Secret Leakage in Outputs:          {report.metrics.secret_leakage_count}")
        print(f"  - Critical Invariants Satisfied:      {report.metrics.critical_invariants_satisfied}")
        print("=" * 80 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="ATLAS Phase 16 Evaluation Runner")
    parser.add_argument(
        "--suite",
        type=str,
        default=None,
        help="Run only a specific evaluation suite (e.g., answer_quality, tool_authorization, workflow_correctness, memory_conversation, reliability_error)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Run only a specific evaluation category",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/evaluations",
        help="Directory to save JSON evaluation reports (default: reports/evaluations)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save JSON report files to disk",
    )

    args = parser.parse_args()

    runner = EvaluationRunner(
        output_dir=args.output_dir,
        selected_suite=args.suite,
        selected_category=args.category,
    )

    report = runner.run()
    runner.print_terminal_summary(report)

    if not args.no_save:
        report_file, latest_file = runner.save_report(report)
        print(f"Report saved to:\n  - {report_file}\n  - {latest_file}\n")

    return 0 if report.overall_status == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
