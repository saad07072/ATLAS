from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from backend.app.security.models import (
    ConfirmationState,
    PermissionDecision,
    RiskLevel,
)
from backend.app.workflows.errors import (
    WorkflowConflictError,
    WorkflowStoreUnavailable,
)
from backend.app.workflows.models import (
    StepStatus,
    StepVerificationStatus,
    WorkflowEventRecord,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowStepRecord,
)

logger = logging.getLogger(__name__)


class WorkflowRepository(Protocol):
    def create(self, workflow: WorkflowRecord) -> WorkflowRecord: ...

    def get(self, user_id: str, workflow_id: str) -> WorkflowRecord | None: ...

    def list(
        self,
        user_id: str,
        *,
        limit: int,
        offset: int,
        status: WorkflowStatus | None = None,
    ) -> tuple[list[WorkflowRecord], bool, int]: ...

    def update_workflow(
        self,
        user_id: str,
        workflow_id: str,
        *,
        status: WorkflowStatus | None = None,
        current_step_id: str | None = None,
        completed_step_count: int | None = None,
        result_summary: str | None = None,
        error_summary: str | None = None,
        completed_at: datetime | None = None,
        expected_version: int | None = None,
    ) -> WorkflowRecord | None: ...

    def update_step(
        self,
        user_id: str,
        workflow_id: str,
        step_id: str,
        *,
        status: StepStatus | None = None,
        attempt_count: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        result_data: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
        confirmation_state: ConfirmationState | None = None,
        confirmation_hash: str | None = None,
        permission_decision: PermissionDecision | None = None,
        verification_status: StepVerificationStatus | None = None,
        verification_details: str | None = None,
    ) -> WorkflowStepRecord | None: ...

    def record_event(self, user_id: str, event: WorkflowEventRecord) -> None: ...

    def list_events(
        self, user_id: str, workflow_id: str
    ) -> list[WorkflowEventRecord]: ...


class InMemoryWorkflowRepository:
    """Thread-safe in-memory repository for unit tests and local execution."""

    def __init__(self) -> None:
        self._workflows: dict[tuple[str, str], WorkflowRecord] = {}
        self._events: dict[str, list[WorkflowEventRecord]] = {}

    def create(self, workflow: WorkflowRecord) -> WorkflowRecord:
        key = (workflow.user_id, workflow.id)
        if key in self._workflows:
            raise WorkflowConflictError("Workflow with this ID already exists.")
        stored = copy.deepcopy(workflow)
        self._workflows[key] = stored
        self._events[workflow.id] = []
        return copy.deepcopy(stored)

    def get(self, user_id: str, workflow_id: str) -> WorkflowRecord | None:
        record = self._workflows.get((user_id, workflow_id))
        return copy.deepcopy(record) if record else None

    def list(
        self,
        user_id: str,
        *,
        limit: int,
        offset: int,
        status: WorkflowStatus | None = None,
    ) -> tuple[list[WorkflowRecord], bool, int]:
        all_user_wfs = [
            wf
            for (uid, _), wf in self._workflows.items()
            if uid == user_id and (status is None or wf.status == status)
        ]
        # Sort by updated_at desc
        all_user_wfs.sort(key=lambda w: w.updated_at, reverse=True)
        total = len(all_user_wfs)
        paged = all_user_wfs[offset : offset + limit]
        has_more = (offset + limit) < total
        return [copy.deepcopy(w) for w in paged], has_more, total

    def update_workflow(
        self,
        user_id: str,
        workflow_id: str,
        *,
        status: WorkflowStatus | None = None,
        current_step_id: str | None = None,
        completed_step_count: int | None = None,
        result_summary: str | None = None,
        error_summary: str | None = None,
        completed_at: datetime | None = None,
        expected_version: int | None = None,
    ) -> WorkflowRecord | None:
        key = (user_id, workflow_id)
        existing = self._workflows.get(key)
        if not existing:
            return None

        if expected_version is not None and existing.version != expected_version:
            raise WorkflowConflictError(
                f"Workflow version conflict. Expected {expected_version}, found {existing.version}."
            )

        if status is not None:
            existing.status = status
        if current_step_id is not None:
            existing.current_step_id = current_step_id
        if completed_step_count is not None:
            existing.completed_step_count = completed_step_count
        if result_summary is not None:
            existing.result_summary = result_summary
        if error_summary is not None:
            existing.error_summary = error_summary
        if completed_at is not None:
            existing.completed_at = completed_at

        existing.version += 1
        existing.updated_at = datetime.now(timezone.utc)
        return copy.deepcopy(existing)

    def update_step(
        self,
        user_id: str,
        workflow_id: str,
        step_id: str,
        *,
        status: StepStatus | None = None,
        attempt_count: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        result_data: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
        confirmation_state: ConfirmationState | None = None,
        confirmation_hash: str | None = None,
        permission_decision: PermissionDecision | None = None,
        verification_status: StepVerificationStatus | None = None,
        verification_details: str | None = None,
    ) -> WorkflowStepRecord | None:
        key = (user_id, workflow_id)
        wf = self._workflows.get(key)
        if not wf:
            return None

        step = next((s for s in wf.steps if s.step_id == step_id), None)
        if not step:
            return None

        if status is not None:
            step.status = status
        if attempt_count is not None:
            step.attempt_count = attempt_count
        if started_at is not None:
            step.started_at = started_at
        if completed_at is not None:
            step.completed_at = completed_at
        if result_data is not None:
            step.result_data = result_data
        if error_info is not None:
            step.error_info = error_info
        if confirmation_state is not None:
            step.confirmation_state = confirmation_state
        if confirmation_hash is not None:
            step.confirmation_hash = confirmation_hash
        if permission_decision is not None:
            step.permission_decision = permission_decision
        if verification_status is not None:
            step.verification_status = verification_status
        if verification_details is not None:
            step.verification_details = verification_details

        wf.updated_at = datetime.now(timezone.utc)
        return copy.deepcopy(step)

    def record_event(self, user_id: str, event: WorkflowEventRecord) -> None:
        if (user_id, event.workflow_id) not in self._workflows:
            return
        self._events.setdefault(event.workflow_id, []).append(copy.deepcopy(event))

    def list_events(
        self, user_id: str, workflow_id: str
    ) -> list[WorkflowEventRecord]:
        if (user_id, workflow_id) not in self._workflows:
            return []
        events = self._events.get(workflow_id, [])
        return copy.deepcopy(events)


class PostgresWorkflowRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url

    def create(self, workflow: WorkflowRecord) -> WorkflowRecord:
        def insert_tx(connection: Any) -> WorkflowRecord:
            connection.execute(
                """
                INSERT INTO public.atlas_workflows (
                    id, user_id, conversation_id, title, user_request,
                    status, current_step_id, step_count, completed_step_count,
                    result_summary, error_summary, version, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    workflow.id,
                    workflow.user_id,
                    workflow.conversation_id,
                    workflow.title,
                    workflow.user_request,
                    workflow.status.value,
                    workflow.current_step_id,
                    workflow.step_count,
                    workflow.completed_step_count,
                    workflow.result_summary,
                    workflow.error_summary,
                    workflow.version,
                    workflow.created_at,
                    workflow.updated_at,
                ),
            )

            for step in workflow.steps:
                connection.execute(
                    """
                    INSERT INTO public.atlas_workflow_steps (
                        id, user_id, workflow_id, step_id, step_order, title,
                        tool_name, arguments, dependencies, status, attempt_count,
                        max_retries, risk_level, permission_required, permission_decision,
                        confirmation_state, confirmation_hash, started_at, completed_at,
                        result_data, error_info, verification_status, verification_details
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        step.id,
                        workflow.user_id,
                        workflow.id,
                        step.step_id,
                        step.step_order,
                        step.title,
                        step.tool_name,
                        json.dumps(step.arguments),
                        json.dumps(step.dependencies),
                        step.status.value,
                        step.attempt_count,
                        step.max_retries,
                        step.risk_level.value,
                        step.permission_required,
                        step.permission_decision.value if step.permission_decision else None,
                        step.confirmation_state.value,
                        step.confirmation_hash,
                        step.started_at,
                        step.completed_at,
                        json.dumps(step.result_data) if step.result_data else None,
                        json.dumps(step.error_info) if step.error_info else None,
                        step.verification_status.value,
                        step.verification_details,
                    ),
                )
            return workflow

        self._run(workflow.user_id, insert_tx)
        return workflow

    def get(self, user_id: str, workflow_id: str) -> WorkflowRecord | None:
        def fetch(connection: Any) -> WorkflowRecord | None:
            wf_row = connection.execute(
                """
                SELECT id::text AS id, user_id::text AS user_id, conversation_id::text AS conversation_id,
                       title, user_request, status, current_step_id, step_count,
                       completed_step_count, result_summary, error_summary, version,
                       created_at, updated_at, completed_at
                FROM public.atlas_workflows
                WHERE user_id = %s AND id = %s
                """,
                (user_id, workflow_id),
            ).fetchone()
            if not wf_row:
                return None

            step_rows = connection.execute(
                """
                SELECT id::text AS id, workflow_id::text AS workflow_id, step_id, step_order,
                       title, tool_name, arguments, dependencies, status, attempt_count,
                       max_retries, risk_level, permission_required, permission_decision,
                       confirmation_state, confirmation_hash, started_at, completed_at,
                       result_data, error_info, verification_status, verification_details
                FROM public.atlas_workflow_steps
                WHERE user_id = %s AND workflow_id = %s
                ORDER BY step_order ASC
                """,
                (user_id, workflow_id),
            ).fetchall()

            steps = [
                WorkflowStepRecord(
                    id=sr["id"],
                    workflow_id=sr["workflow_id"],
                    step_id=sr["step_id"],
                    step_order=sr["step_order"],
                    title=sr["title"],
                    tool_name=sr["tool_name"],
                    arguments=sr["arguments"] if isinstance(sr["arguments"], dict) else json.loads(sr["arguments"] or "{}"),
                    dependencies=sr["dependencies"] if isinstance(sr["dependencies"], list) else json.loads(sr["dependencies"] or "[]"),
                    status=StepStatus(sr["status"]),
                    attempt_count=sr["attempt_count"],
                    max_retries=sr["max_retries"],
                    risk_level=RiskLevel(sr["risk_level"]),
                    permission_required=sr["permission_required"],
                    permission_decision=PermissionDecision(sr["permission_decision"]) if sr["permission_decision"] else None,
                    confirmation_state=ConfirmationState(sr["confirmation_state"]),
                    confirmation_hash=sr["confirmation_hash"],
                    started_at=sr["started_at"],
                    completed_at=sr["completed_at"],
                    result_data=sr["result_data"] if isinstance(sr["result_data"], dict) else (json.loads(sr["result_data"]) if sr["result_data"] else None),
                    error_info=sr["error_info"] if isinstance(sr["error_info"], dict) else (json.loads(sr["error_info"]) if sr["error_info"] else None),
                    verification_status=StepVerificationStatus(sr["verification_status"]),
                    verification_details=sr["verification_details"],
                )
                for sr in step_rows
            ]

            return WorkflowRecord(
                id=wf_row["id"],
                user_id=wf_row["user_id"],
                conversation_id=wf_row["conversation_id"],
                title=wf_row["title"],
                user_request=wf_row["user_request"],
                status=WorkflowStatus(wf_row["status"]),
                current_step_id=wf_row["current_step_id"],
                step_count=wf_row["step_count"],
                completed_step_count=wf_row["completed_step_count"],
                result_summary=wf_row["result_summary"],
                error_summary=wf_row["error_summary"],
                version=wf_row["version"],
                created_at=wf_row["created_at"],
                updated_at=wf_row["updated_at"],
                completed_at=wf_row["completed_at"],
                steps=steps,
            )

        return self._run(user_id, fetch)

    def list(
        self,
        user_id: str,
        *,
        limit: int,
        offset: int,
        status: WorkflowStatus | None = None,
    ) -> tuple[list[WorkflowRecord], bool, int]:
        def fetch_list(connection: Any) -> tuple[list[WorkflowRecord], bool, int]:
            count_query = "SELECT count(*) AS total FROM public.atlas_workflows WHERE user_id = %s"
            params: list[Any] = [user_id]
            if status is not None:
                count_query += " AND status = %s"
                params.append(status.value)
            total = connection.execute(count_query, params).fetchone()["total"]

            query = """
                SELECT id::text AS id, user_id::text AS user_id, conversation_id::text AS conversation_id,
                       title, user_request, status, current_step_id, step_count,
                       completed_step_count, result_summary, error_summary, version,
                       created_at, updated_at, completed_at
                FROM public.atlas_workflows
                WHERE user_id = %s
            """
            list_params: list[Any] = [user_id]
            if status is not None:
                query += " AND status = %s"
                list_params.append(status.value)
            query += " ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s"
            list_params.extend([limit, offset])

            rows = connection.execute(query, list_params).fetchall()
            records = [
                WorkflowRecord(
                    id=r["id"],
                    user_id=r["user_id"],
                    conversation_id=r["conversation_id"],
                    title=r["title"],
                    user_request=r["user_request"],
                    status=WorkflowStatus(r["status"]),
                    current_step_id=r["current_step_id"],
                    step_count=r["step_count"],
                    completed_step_count=r["completed_step_count"],
                    result_summary=r["result_summary"],
                    error_summary=r["error_summary"],
                    version=r["version"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    completed_at=r["completed_at"],
                )
                for r in rows
            ]
            has_more = (offset + limit) < total
            return records, has_more, total

        return self._run(user_id, fetch_list)

    def update_workflow(
        self,
        user_id: str,
        workflow_id: str,
        *,
        status: WorkflowStatus | None = None,
        current_step_id: str | None = None,
        completed_step_count: int | None = None,
        result_summary: str | None = None,
        error_summary: str | None = None,
        completed_at: datetime | None = None,
        expected_version: int | None = None,
    ) -> WorkflowRecord | None:
        def update_tx(connection: Any) -> WorkflowRecord | None:
            clauses = ["version = version + 1", "updated_at = now()"]
            params: list[Any] = []

            if status is not None:
                clauses.append("status = %s")
                params.append(status.value)
            if current_step_id is not None:
                clauses.append("current_step_id = %s")
                params.append(current_step_id)
            if completed_step_count is not None:
                clauses.append("completed_step_count = %s")
                params.append(completed_step_count)
            if result_summary is not None:
                clauses.append("result_summary = %s")
                params.append(result_summary)
            if error_summary is not None:
                clauses.append("error_summary = %s")
                params.append(error_summary)
            if completed_at is not None:
                clauses.append("completed_at = %s")
                params.append(completed_at)

            where_clauses = ["user_id = %s", "id = %s"]
            where_params: list[Any] = [user_id, workflow_id]
            if expected_version is not None:
                where_clauses.append("version = %s")
                where_params.append(expected_version)

            sql = f"""
                UPDATE public.atlas_workflows
                SET {', '.join(clauses)}
                WHERE {' AND '.join(where_clauses)}
                RETURNING id
            """
            res = connection.execute(sql, params + where_params).fetchone()
            if not res and expected_version is not None:
                # Check if it was a version conflict
                exists = connection.execute(
                    "SELECT version FROM public.atlas_workflows WHERE user_id = %s AND id = %s",
                    (user_id, workflow_id),
                ).fetchone()
                if exists and exists["version"] != expected_version:
                    raise WorkflowConflictError("Concurrent workflow update conflict detected.")
            return self.get(user_id, workflow_id)

        return self._run(user_id, update_tx)

    def update_step(
        self,
        user_id: str,
        workflow_id: str,
        step_id: str,
        *,
        status: StepStatus | None = None,
        attempt_count: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        result_data: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
        confirmation_state: ConfirmationState | None = None,
        confirmation_hash: str | None = None,
        permission_decision: PermissionDecision | None = None,
        verification_status: StepVerificationStatus | None = None,
        verification_details: str | None = None,
    ) -> WorkflowStepRecord | None:
        def update_step_tx(connection: Any) -> WorkflowStepRecord | None:
            clauses = []
            params: list[Any] = []

            if status is not None:
                clauses.append("status = %s")
                params.append(status.value)
            if attempt_count is not None:
                clauses.append("attempt_count = %s")
                params.append(attempt_count)
            if started_at is not None:
                clauses.append("started_at = %s")
                params.append(started_at)
            if completed_at is not None:
                clauses.append("completed_at = %s")
                params.append(completed_at)
            if result_data is not None:
                clauses.append("result_data = %s")
                params.append(json.dumps(result_data))
            if error_info is not None:
                clauses.append("error_info = %s")
                params.append(json.dumps(error_info))
            if confirmation_state is not None:
                clauses.append("confirmation_state = %s")
                params.append(confirmation_state.value)
            if confirmation_hash is not None:
                clauses.append("confirmation_hash = %s")
                params.append(confirmation_hash)
            if permission_decision is not None:
                clauses.append("permission_decision = %s")
                params.append(permission_decision.value)
            if verification_status is not None:
                clauses.append("verification_status = %s")
                params.append(verification_status.value)
            if verification_details is not None:
                clauses.append("verification_details = %s")
                params.append(verification_details)

            if not clauses:
                return None

            sql = f"""
                UPDATE public.atlas_workflow_steps
                SET {', '.join(clauses)}
                WHERE user_id = %s AND workflow_id = %s AND step_id = %s
                RETURNING id::text AS id, workflow_id::text AS workflow_id, step_id, step_order,
                          title, tool_name, arguments, dependencies, status, attempt_count,
                          max_retries, risk_level, permission_required, permission_decision,
                          confirmation_state, confirmation_hash, started_at, completed_at,
                          result_data, error_info, verification_status, verification_details
            """
            sr = connection.execute(sql, params + [user_id, workflow_id, step_id]).fetchone()
            if not sr:
                return None

            connection.execute(
                "UPDATE public.atlas_workflows SET updated_at = now() WHERE user_id = %s AND id = %s",
                (user_id, workflow_id),
            )

            return WorkflowStepRecord(
                id=sr["id"],
                workflow_id=sr["workflow_id"],
                step_id=sr["step_id"],
                step_order=sr["step_order"],
                title=sr["title"],
                tool_name=sr["tool_name"],
                arguments=sr["arguments"] if isinstance(sr["arguments"], dict) else json.loads(sr["arguments"] or "{}"),
                dependencies=sr["dependencies"] if isinstance(sr["dependencies"], list) else json.loads(sr["dependencies"] or "[]"),
                status=StepStatus(sr["status"]),
                attempt_count=sr["attempt_count"],
                max_retries=sr["max_retries"],
                risk_level=RiskLevel(sr["risk_level"]),
                permission_required=sr["permission_required"],
                permission_decision=PermissionDecision(sr["permission_decision"]) if sr["permission_decision"] else None,
                confirmation_state=ConfirmationState(sr["confirmation_state"]),
                confirmation_hash=sr["confirmation_hash"],
                started_at=sr["started_at"],
                completed_at=sr["completed_at"],
                result_data=sr["result_data"] if isinstance(sr["result_data"], dict) else (json.loads(sr["result_data"]) if sr["result_data"] else None),
                error_info=sr["error_info"] if isinstance(sr["error_info"], dict) else (json.loads(sr["error_info"]) if sr["error_info"] else None),
                verification_status=StepVerificationStatus(sr["verification_status"]),
                verification_details=sr["verification_details"],
            )

        return self._run(user_id, update_step_tx)

    def record_event(self, user_id: str, event: WorkflowEventRecord) -> None:
        def insert_event(connection: Any) -> None:
            connection.execute(
                """
                INSERT INTO public.atlas_workflow_events (
                    id, user_id, workflow_id, step_id, event_type, details, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.id,
                    user_id,
                    event.workflow_id,
                    event.step_id,
                    event.event_type,
                    json.dumps(event.details),
                    event.created_at,
                ),
            )

        self._run(user_id, insert_event)

    def list_events(
        self, user_id: str, workflow_id: str
    ) -> list[WorkflowEventRecord]:
        def fetch_events(connection: Any) -> list[WorkflowEventRecord]:
            rows = connection.execute(
                """
                SELECT id::text AS id, workflow_id::text AS workflow_id, step_id,
                       event_type, details, created_at
                FROM public.atlas_workflow_events
                WHERE user_id = %s AND workflow_id = %s
                ORDER BY created_at ASC
                """,
                (user_id, workflow_id),
            ).fetchall()
            return [
                WorkflowEventRecord(
                    id=r["id"],
                    workflow_id=r["workflow_id"],
                    step_id=r["step_id"],
                    event_type=r["event_type"],
                    details=r["details"] if isinstance(r["details"], dict) else json.loads(r["details"] or "{}"),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

        return self._run(user_id, fetch_events)

    def _run(self, user_id: str, operation: Callable[[Any], Any]) -> Any:
        if not self._database_url:
            raise WorkflowStoreUnavailable(
                "Persistent workflow storage is not configured."
            )
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise WorkflowStoreUnavailable(
                "Persistent workflow storage is unavailable."
            ) from None

        try:
            with psycopg.connect(
                self._database_url,
                row_factory=dict_row,
                connect_timeout=5,
            ) as connection:
                claims = json.dumps(
                    {
                        "aud": "authenticated",
                        "atlas_backend": True,
                        "role": "authenticated",
                        "sub": user_id,
                    }
                )
                connection.execute("SET LOCAL ROLE authenticated")
                connection.execute(
                    """
                    SELECT
                        set_config('request.jwt.claim.sub', %s, true),
                        set_config('request.jwt.claims', %s, true)
                    """,
                    (user_id, claims),
                )
                return operation(connection)
        except psycopg.Error:
            raise WorkflowStoreUnavailable(
                "Persistent workflow storage is unavailable."
            ) from None

