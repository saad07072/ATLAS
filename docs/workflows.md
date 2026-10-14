# ATLAS Workflow Engine

The ATLAS Workflow Engine provides deterministic, persistent, and secure multi-step task execution. It orchestrates complex tasks using Directed Acyclic Graphs (DAGs), enforces dependency resolution, pauses for interactive authorization on sensitive operations, verifies external outcomes, and reports partial or complete outcomes truthfully.

---

## 1. Core Architecture & Philosophy

The workflow engine adheres to the fundamental ATLAS security principle:

> **The LLM proposes. The system authorizes. The tools execute. The system verifies.**

The complete lifecycle follows seven discrete stages:

$$\text{Understand} \longrightarrow \text{Plan} \longrightarrow \text{Authorize} \longrightarrow \text{Execute} \longrightarrow \text{Verify} \longrightarrow \text{Remember} \longrightarrow \text{Report}$$

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Plan & Validate                                                          │
│   User/Agent Proposal ──> Cycle Detection (DAG) ──> Tool Schema Validation  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Authorize & Gate                                                         │
│   Dependency Check ──> PermissionEngine ──> High-Risk? ──> User Confirmation│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Execute & Verify                                                         │
│   ToolExecutor ──> Result Validation ──> Verification Step ──> State Update │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. Audit & Report                                                           │
│   Audit Trail Logging ──> Truthful Outcome (Completed / Partially Completed)│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. State Machine

Workflow and step lifecycles are governed by centrally enforced finite state machines.

### Workflow States

- `draft`: Initial plan persisted; not yet queued for execution.
- `ready`: Validated and queued for execution.
- `running`: Actively executing eligible steps.
- `waiting_for_confirmation`: Execution paused awaiting user approval of a high-risk step.
- `completed`: All steps completed and verified successfully.
- `partially_completed`: Some steps completed, but subsequent steps failed or were skipped due to unmet prerequisites.
- `failed`: Initial or critical steps failed with zero successful outcome.
- `cancelled`: Execution aborted by user request.

### Step States

- `pending`: Waiting for prerequisite dependencies to complete.
- `ready`: All dependencies satisfied; eligible for execution.
- `running`: Tool currently executing.
- `waiting_for_confirmation`: Paused awaiting explicit user authorization.
- `completed`: Tool execution succeeded and verified.
- `failed`: Tool execution failed or confirmation was rejected.
- `skipped`: Bypassed because a prerequisite step failed or was skipped.
- `cancelled`: Step aborted due to workflow cancellation.

---

## 3. Security, Authorization & Confirmation Lifecycle

1. **Trusted Metadata Derivation:** Risk levels (`low`, `medium`, `high`, `critical`) and permission requirements are derived strictly from registered `ToolMetadata`. User inputs, agent prompts, and LLM proposals cannot downgrade risk levels or bypass authorization policies.
2. **Mandatory Confirmation Gates:** Any step utilizing a tool classified as `high` or `critical` risk automatically pauses execution and transitions to `waiting_for_confirmation`.
3. **Cryptographic Confirmation Binding:** When confirmation is requested, ATLAS computes a deterministic SHA-256 hash:
   $$\text{Hash} = \text{SHA-256}(user\_id : workflow\_id : step\_id : tool\_name : \text{canonical\_json}(arguments))$$
   The confirmation cannot be replayed, applied to a different step, or used to authorize altered parameters.
4. **Integration Isolation:** Google Calendar, Gmail, and GitHub actions remain disabled in the tool executor until dedicated per-user execution bridges are verified. Any attempt to invoke disabled tools fails closed immediately.
5. **Secret Redaction:** Input arguments, error messages, and audit events are scrubbed of secret tokens and credentials before storage or transmission.

---

## 4. Truthful Verification & Outcome Reporting

Execution success does not guarantee external verification:

- A tool returning an HTTP 200 or structured dictionary does not prove the external goal succeeded.
- ATLAS employs verification steps (`system.verify`) to test target states and conditions.
- If an intermediate step fails, downstream dependent steps are marked `skipped`, and the workflow reports `partially_completed` with exact statistics (e.g., "1 succeeded, 1 failed, 1 skipped"). ATLAS **never** reports complete success when any step was skipped or failed.

---

## 5. Database Migration & Row-Level Security

### Apply the Database Migration Manually

Review `supabase/migrations/20261014000000_workflow_engine.sql` and apply it to the intended Supabase project:

```powershell
supabase link --project-ref <project-ref>
supabase db push
```

> [!IMPORTANT]
> ATLAS never applies live database migrations automatically. No new environment variables are required: workflows use the existing server-side `DATABASE_URL`.

### Schema Highlights

- `public.atlas_workflows`: Stores workflow metadata, current execution position, and progress counts.
- `public.atlas_workflow_steps`: Stores ordered DAG steps, dependencies, tool arguments, confirmation hashes, and verification statuses.
- `public.atlas_workflow_events`: Stores immutable, timestamped audit events for all status transitions and confirmation decisions.
- **Row-Level Security:** Tables enforce strict isolation via `auth.uid() = user_id AND auth.jwt() ->> 'atlas_backend' = 'true'`.

---

## 6. API Reference

All routes require a valid Supabase access token under `/api/v1/workflows`:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/workflows` | Validate and create a structured workflow plan. |
| `GET` | `/api/v1/workflows?limit=50&offset=0&status=...` | List authenticated user's workflows with pagination. |
| `GET` | `/api/v1/workflows/{id}` | Retrieve complete workflow details, steps, and progress. |
| `POST` | `/api/v1/workflows/{id}/start` | Start executing an eligible workflow. |
| `POST` | `/api/v1/workflows/{id}/resume` | Resume execution of a paused workflow. |
| `POST` | `/api/v1/workflows/{id}/cancel` | Safely cancel an active workflow. |
| `POST` | `/api/v1/workflows/{id}/steps/{step_id}/confirm` | Authorize or reject a pending step (`{"decision": "confirm" \| "reject", "reason": "..."}`). |
| `GET` | `/api/v1/workflows/{id}/events` | Retrieve sanitized audit trail events for a workflow. |

---

## 7. Frontend Workflow Experience

- **Workflows Dashboard (`/workflows`):** Interactive page featuring filter tabs, workflow status cards, visual execution pipeline, progress tracking, and collapsible audit logs.
- **Interactive Confirmation Banner:** Prominently alerts the user when a high-risk step requires explicit authorization, displays the exact validated parameters, and provides one-click approval or rejection.
- **Activity Page Integration (`/activity`):** Real-time aggregation of recent operations, active counts, and direct links to inspect workflow executions.

