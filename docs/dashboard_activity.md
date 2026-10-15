# ATLAS Dashboard & Activity Feed

Phase 14 delivers a unified, production-grade operational hub for ATLAS (Autonomous Task & Life Assistant System). It transforms the main root dashboard (`/`) and the dedicated Activity view (`/activity`) into authenticated, truthful interfaces that surface live workflow executions, approval bottlenecks, chronological event feeds, recent conversations, and integration statuses.

---

## 1. Design Philosophy: Operational Truthfulness

ATLAS adheres to the core principle of **truthful reporting**:

1. **No Phantom Metrics**: Dashboard numbers (completed, failed, running, pending confirmations) are derived directly from the authenticated user's persisted records in PostgreSQL / Supabase, never hardcoded mocks or optimistic guesses.
2. **Deterministic Status Tracking**: If an external dependency or service is unavailable (e.g., conversation store down or integration credentials not configured), the interface degrades gracefully and truthfully reports `"degraded"` or `"disconnected"` without breaking the page.
3. **Strict Resource Attribution & Multi-Tenancy**: All queries for events, workflows, and conversations are rigorously isolated to `user_id == authenticated_user_id`. One tenant cannot observe another tenant's activities, executions, or integration statuses.
4. **Execution Safety Boundaries**: External action execution for third-party integrations (Google Workspace, GitHub) remains strictly gated with `actions_enabled=False` until secure, per-user OAuth execution authorization is fully established.

---

## 2. Dashboard Architecture (`/`)

The main dashboard provides an operational cockpit organized into logical visual panels:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ High-Risk Approval Alert Banner (Visible only when approvals are pending)   │
├───────────────────┬───────────────────┬───────────────────┬─────────────────┤
│ Active Workflows  │ Completed Tasks   │ High-Risk Pending │ Total Activity  │
├───────────────────┴───────────────────┴───────────────────┴─────────────────┤
│ Operational Center (Split View)                                             │
│ ┌───────────────────────────────────────┬─────────────────────────────────┐ │
│ │ Running Workflows & Progress Bars     │ Chronological Activity Feed     │ │
│ │ - Deterministic step progress (%)     │ - Real execution events         │ │
│ │ - Direct links to /workflows          │ - Timestamped event badges      │ │
│ ├───────────────────────────────────────┼─────────────────────────────────┤ │
│ │ Connected Integrations                │ Recent Conversations            │ │
│ │ - Google & GitHub connection status   │ - Interactive session links     │ │
│ │ - Explicit read-only actions badge    │ - Safe empty / error states     │ │
│ └───────────────────────────────────────┴─────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Embedded Quick Assistant Panel (<ChatPanel />)                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Components & State Management

- **Status Banner**: Alert ribbon that displays immediately when `pending_confirmations > 0`, linking users directly to `/workflows` for confirmation review.
- **Metric Cards**: Four high-contrast statistics showing Active, Completed, Pending Approval, and Total Executions.
- **Running Workflows Panel**: Displays workflows currently in `running` or `waiting_for_confirmation` status, including progress bars computed from completed step counts against total steps.
- **Activity Feed**: The most recent 5 chronological events with status chips (`success`, `failure`, `paused`, `started`), workflow titles, and UTC relative timestamps.
- **Connected Services**: Real-time connection indicators for Google and GitHub, explicitly noting `Read-Only Gated` to avoid confusing users about execution capabilities.
- **Recent Conversations**: Compact listing of the user's latest chat sessions with timestamps and direct navigation.

---

## 3. Activity Feed (`/activity`)

The Activity page provides a comprehensive audit trail of system and workflow events.

### Key Capabilities

1. **Chronological Event Stream**: Queries `atlas_workflow_events` joined with `atlas_workflows` for titles, ordered by `created_at DESC`.
2. **Status Metrics Summary**: Displays live counts for Completed, In Progress, Awaiting Confirmation, and Failed/Partial workflows.
3. **Filter Navigation**: Filter tabs to switch between all events, running workflows, awaiting approvals, and completed tasks.
4. **Bounded Pagination**: Safe pagination controls (`limit=20`, default max `100`), calculating total items, total pages, and maintaining page state without unbounded queries.
5. **Zero Mock Fallbacks**: Completely eliminated all hardcoded mock activity items. When no events exist, an honest empty state is presented with a prompt to run a workflow.

---

## 4. API Specifications

### `GET /api/v1/dashboard`

Retrieves an operational summary for the authenticated user.

- **Authentication**: Bearer JWT (`Authorization: Bearer <token>`).
- **Response Model**: `DashboardResponse`

```json
{
  "status_counts": {
    "total": 12,
    "draft": 0,
    "ready": 0,
    "running": 1,
    "waiting_for_confirmation": 1,
    "completed": 8,
    "partially_completed": 1,
    "failed": 1,
    "cancelled": 0
  },
  "running_workflows": [
    {
      "id": "e9c1c4f2-95f2-4ad5-9c92-38d7c0f16f5c",
      "title": "Data Pipeline Sync",
      "status": "running",
      "total_steps": 4,
      "completed_steps": 2,
      "created_at": "2026-10-15T12:00:00Z",
      "updated_at": "2026-10-15T12:05:00Z"
    }
  ],
  "pending_approvals_count": 1,
  "recent_events": [
    {
      "id": "f8a2c1b4-1111-2222-3333-444455556666",
      "workflow_id": "e9c1c4f2-95f2-4ad5-9c92-38d7c0f16f5c",
      "workflow_title": "Data Pipeline Sync",
      "step_id": "step_2",
      "event_type": "step_completed",
      "payload": {"tool_name": "data.extract"},
      "created_at": "2026-10-15T12:05:00Z"
    }
  ],
  "recent_conversations": [
    {
      "id": "c0a1b2c3-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
      "title": "Quarterly Plan Assistant",
      "created_at": "2026-10-15T11:00:00Z",
      "updated_at": "2026-10-15T11:45:00Z"
    }
  ],
  "connected_services": [
    {
      "service": "google",
      "connected": true,
      "actions_enabled": false
    },
    {
      "service": "github",
      "connected": true,
      "actions_enabled": false
    }
  ],
  "system_status": "operational"
}
```

### `GET /api/v1/workflows/events`

Returns a paginated list of operational workflow events for the authenticated user.

- **Authentication**: Bearer JWT (`Authorization: Bearer <token>`).
- **Query Parameters**:
  - `limit` (integer, default `20`, maximum `100`): Maximum events per page.
  - `offset` (integer, default `0`, minimum `0`): Pagination offset.
- **Response Model**: `WorkflowEventListResponse`

```json
{
  "events": [
    {
      "id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "workflow_id": "893c5d7a-1234-5678-9abc-def012345678",
      "workflow_title": "Automated Security Audit",
      "step_id": "step_verify",
      "event_type": "step_completed",
      "payload": {
        "tool_name": "system.verify",
        "result": {"status": "verified"}
      },
      "created_at": "2026-10-15T12:30:00Z"
    }
  ],
  "total": 45,
  "limit": 20,
  "offset": 0
}
```

---

## 5. Security & Isolation Boundaries

| Boundary | Policy & Implementation |
|---|---|
| **User Isolation** | All repositories filter by `user_id = :user_id`. No cross-user leakage in counts, events, or conversations. |
| **Integrations Safety** | `actions_enabled` is deterministically returned as `False` for Google and GitHub until per-user token authorization is active. |
| **Secret Sanitization** | `contains_secret()` guards ensure no raw API keys, bearer tokens, or client secrets are accepted in workflow arguments or emitted in events. |
| **Resilience & Degraded Stores** | If `ConversationStoreUnavailable` occurs, the dashboard catches the exception and returns an empty list for `recent_conversations` with `system_status = "degraded"` rather than an uncaught 500 error. |

---

## 6. Database Migration & Optimization

Migration file: `supabase/migrations/20261015000000_dashboard_activity.sql`

```sql
-- Phase 14: Dashboard & Activity optimization index
CREATE INDEX IF NOT EXISTS atlas_workflow_events_user_created_idx 
ON public.atlas_workflow_events (user_id, created_at DESC);
```

This composite B-tree index optimizes the paginated user event retrieval query (`WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3`), ensuring sub-millisecond query execution even with tens of thousands of workflow event records.

