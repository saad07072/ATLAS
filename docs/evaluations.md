# ATLAS Agent Evaluation & Reliability Framework

Phase 16 establishes a repeatable, deterministic evaluation framework for ATLAS (Autonomous Task & Life Assistant System). It replaces subjective "it seems to work" judgments with reproducible tests, measurable behavioral metrics, and structured evaluation reports.

---

## 1. Core Operating & Safety Principles

The evaluation framework verifies adherence to ATLAS core principles:

> **Understand → Plan → Authorize → Execute → Verify → Remember → Report**  
> **The LLM proposes. The system authorizes. The tools execute. The system verifies.**

All evaluations use synthetic datasets, mocked tools, and isolated in-memory stores. Automated evaluations never perform live LLM provider network calls, never mutate real external services (Google, GitHub), and never access live Supabase databases or `.env` secrets.

---

## 2. Evaluation Architecture

```
                                  CLI Runner (scripts/run_evals.py)
                                  or Pytest (backend/tests)
                                              │
                                              ▼
                                   EvaluationRunner
                                              │
        ┌───────────────────┬─────────────────┼───────────────────┬───────────────────┐
        ▼                   ▼                 ▼                   ▼                   ▼
   Answer Quality   Tool Authorization   Workflows        Memory & Dialogues   Reliability & Errors
    (7 Cases)           (7 Cases)        (7 Cases)            (7 Cases)            (8 Cases)
        │                   │                 │                   │                   │
        └───────────────────┴─────────────────┼───────────────────┴───────────────────┘
                                              │
                                              ▼
                               Metric & Safety Invariant Engine
                                 - Pass/Fail Evaluation
                                 - Critical Invariant Enforcement (must be 0)
                                              │
                                              ▼
                             Terminal Summary & Machine-Readable JSON
                             (reports/evaluations/evaluation_report_*.json)
```

### Module Organization

- **`backend/app/evaluation/models.py`**: Pydantic schemas defining `EvaluationCategory`, `CaseEvaluationResult`, `EvaluationMetrics`, and `EvaluationRunReport`.
- **`backend/app/evaluation/suites/`**:
  - `answer_quality.py`: Evaluates intent classification, bounded capability reporting, prompt construction, and clarification gating.
  - `tool_authorization.py`: Evaluates permission engine boundaries, argument validation, confirmation gating, and prompt injection immunity.
  - `workflow_correctness.py`: Evaluates DAG validation, cycle detection, failure cascading, confirmation replays, and truthful verification status.
  - `memory_conversation.py`: Evaluates semantic retrieval, credential rejection on write, query suppression, untrusted prompt sandboxing, and tenant isolation.
  - `reliability_error.py`: Evaluates LLM gateway errors, rate limiting, request size limits, log redaction, and disabled integration safeguards.
- **`backend/app/evaluation/runner.py`**: Orchestrates suite execution, computes metrics, enforces safety invariants, outputs terminal summaries, and generates JSON reports.
- **`scripts/run_evals.py`**: Top-level command-line entry point.

---

## 3. Evaluation Categories & Cases

| Category | Suite Name | Cases | Focus Areas |
|---|---|:---:|---|
| **Answer Quality** | `answer_quality` | 7 | Intent classification, capability boundaries, vague request clarification, task planning, conversation continuity. |
| **Tool Authorization** | `tool_authorization` | 7 | Registered tool access, unknown tool denial, strict argument validation, high-risk confirmation gating, injection immunity. |
| **Workflow Correctness** | `workflow_correctness` | 7 | Topological DAG ordering, cycle rejection, missing dependency rejection, failure cascading, replay prevention, verification truthfulness. |
| **Memory & Conversations** | `memory_conversation` | 7 | Preference retrieval, credential rejection on write, query secret suppression, prompt sandboxing, multi-tenant isolation. |
| **Reliability & Errors** | `reliability_error` | 8 | Provider timeouts/5xx, malformed/oversized responses, rate limiting, request size limits, log redaction, integration guards. |

Total: **36 automated deterministic evaluation cases**.

---

## 4. Metrics & Critical Safety Invariants

### A. Aggregate Metrics
- **Overall Pass Rate**: `(passed_cases / total_cases) * 100` (Target: 100%).
- **Category Pass Rates**: Individual compliance scores across each of the 5 behavioral categories.
- **Evaluation Time**: Total execution duration in seconds.

### B. Critical Safety Invariants
Regardless of the overall pass rate, the evaluation run will immediately **FAIL** (exit code `1`) if any of the following safety invariants is violated:

1. **Unauthorized Tool Executions (`unauthorized_tool_executions == 0`)**: No tool can execute without verified authorization.
2. **Critical Actions Silently Authorized (`critical_actions_silently_authorized == 0`)**: High-risk actions must require explicit confirmation.
3. **Failed Actions Falsely Reported as Success (`failed_actions_reported_as_success == 0`)**: Failed, denied, or skipped operations must never be reported as completed or verified.
4. **Secret Leakage in Outputs (`secret_leakage_count == 0`)**: Tokens, passwords, and private keys must never appear in outputs or logs.

---

## 5. Running Evaluations

### Run All Evaluation Suites (CLI)
```bash
python scripts/run_evals.py
```
Or via module invocation:
```bash
python -m backend.app.evaluation.runner
```

### Run a Specific Suite or Category
```bash
# Run only Tool Authorization suite
python scripts/run_evals.py --suite tool_authorization

# Run only Memory and Conversation category
python scripts/run_evals.py --category memory_conversation
```

### Specify Output Directory or Disable Saving
```bash
python scripts/run_evals.py --output-dir reports/custom --no-save
```

### Run via Pytest
```bash
pytest backend/tests/test_evaluation_framework.py
```

---

## 6. Report Format

Machine-readable JSON reports are saved to `reports/evaluations/`:
- Timestamped report: `reports/evaluations/evaluation_report_<YYYYMMDD_HHMMSS>.json`
- Latest link: `reports/evaluations/latest_report.json`

Example structure:
```json
{
  "framework_version": "1.0.0",
  "dataset_version": "2026.10-v1",
  "timestamp": "2026-10-17T13:09:17.219957+00:00",
  "overall_status": "PASSED",
  "metrics": {
    "total_cases": 36,
    "passed_cases": 36,
    "failed_cases": 0,
    "pass_rate": 100.0,
    "unauthorized_tool_executions": 0,
    "critical_actions_silently_authorized": 0,
    "failed_actions_reported_as_success": 0,
    "secret_leakage_count": 0,
    "critical_invariants_satisfied": true,
    "duration_seconds": 0.055
  },
  "invariant_violations": [],
  "results": [ ... ]
}
```

---

## 7. Deterministic Evaluations vs. Optional LLM Judges

- **Deterministic Evaluations (Standard)**: Use static property assertions, schema validation, mock responses, and exact pattern matches. Fast (<0.1s), zero cost, reproducible in CI without API keys.
- **Optional LLM Judges (Future / Advisory)**: For subjective writing style or complex semantic grading. Marked as non-deterministic and never required for CI or regression passes.

---

## 8. Adding New Evaluation Cases

To add a new evaluation case:
1. Locate the appropriate category in `backend/app/evaluation/suites/`.
2. Define the input request, context, and expected behavioral constraints.
3. Record duration and evaluate assertions.
4. If the case evaluates a critical safety boundary (e.g. authorization or secret protection), set `safety_critical=True` and configure `critical_invariant_violated=True` if violated.
5. Append the `CaseEvaluationResult` to the suite's returned list.

