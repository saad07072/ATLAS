from collections.abc import Callable
import json
from typing import Any, Protocol

from backend.app.memory.errors import (
    MemoryConflict,
    MemoryNotFound,
    MemoryStoreUnavailable,
)
from backend.app.memory.models import MemoryCandidate, MemoryRecord, MemoryUpdate


class MemoryRepository(Protocol):
    def list(
        self,
        user_id: str,
        *,
        memory_type: str | None,
        limit: int,
    ) -> list[MemoryRecord]: ...

    def create(
        self,
        user_id: str,
        candidate: MemoryCandidate,
        *,
        source: str,
    ) -> MemoryRecord: ...

    def update(
        self,
        user_id: str,
        memory_id: str,
        changes: MemoryUpdate,
    ) -> MemoryRecord | None: ...

    def delete(self, user_id: str, memory_id: str) -> bool: ...

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        memory_type: str | None,
        limit: int,
    ) -> list[MemoryRecord]: ...


class PostgresMemoryRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url

    def list(
        self,
        user_id: str,
        *,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        rows = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                SELECT id::text AS id, memory_type AS type, memory_key, content,
                       source, created_at, updated_at
                FROM public.atlas_memories
                WHERE user_id = %s AND (%s IS NULL OR memory_type = %s)
                ORDER BY updated_at DESC, id
                LIMIT %s
                """,
                (user_id, memory_type, memory_type, limit),
            ).fetchall()
        )
        return [MemoryRecord.model_validate(row) for row in rows]

    def create(
        self,
        user_id: str,
        candidate: MemoryCandidate,
        *,
        source: str,
    ) -> MemoryRecord:
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                INSERT INTO public.atlas_memories
                    (user_id, memory_type, memory_key, content, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, memory_type, memory_key)
                DO UPDATE SET content = EXCLUDED.content,
                              source = EXCLUDED.source,
                              updated_at = now()
                RETURNING id::text AS id, memory_type AS type, memory_key, content,
                          source, created_at, updated_at
                """,
                (
                    user_id,
                    candidate.type.value,
                    candidate.memory_key,
                    candidate.content,
                    source,
                ),
            ).fetchone()
        )
        return MemoryRecord.model_validate(row)

    def update(
        self,
        user_id: str,
        memory_id: str,
        changes: MemoryUpdate,
    ) -> MemoryRecord | None:
        fields = changes.model_dump(exclude_unset=True)
        assignments: list[str] = []
        values: list[str] = []
        if "type" in fields:
            assignments.append("memory_type = %s")
            values.append(fields["type"].value)
        if "memory_key" in fields:
            assignments.append("memory_key = %s")
            values.append(fields["memory_key"])
        if "content" in fields:
            assignments.append("content = %s")
            values.append(fields["content"])
        if not assignments:
            raise ValueError("At least one memory field must be updated.")

        values.extend((user_id, memory_id))
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                f"""
                UPDATE public.atlas_memories
                SET {", ".join(assignments)}, updated_at = now()
                WHERE user_id = %s AND id = %s
                RETURNING id::text AS id, memory_type AS type, memory_key, content,
                          source, created_at, updated_at
                """,
                tuple(values),
            ).fetchone()
        )
        return MemoryRecord.model_validate(row) if row else None

    def delete(self, user_id: str, memory_id: str) -> bool:
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                DELETE FROM public.atlas_memories
                WHERE user_id = %s AND id = %s
                RETURNING id
                """,
                (user_id, memory_id),
            ).fetchone()
        )
        return row is not None

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        memory_type: str | None = None,
        limit: int = 5,
    ) -> list[MemoryRecord]:
        rows = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                WITH search_query AS (
                    SELECT websearch_to_tsquery('simple', %s) AS terms
                )
                SELECT m.id::text AS id, m.memory_type AS type, m.memory_key,
                       m.content, m.source, m.created_at, m.updated_at,
                       LEAST(
                           1.0,
                           ts_rank_cd(m.search_document, q.terms) * 0.70
                           + (
                               1.0 / (
                                   1.0 + EXTRACT(
                                       EPOCH FROM (now() - m.updated_at)
                                   ) / 2592000.0
                               )
                           ) * 0.20
                           + CASE m.memory_type
                               WHEN 'user_preference' THEN 0.040
                               WHEN 'durable_fact' THEN 0.035
                               WHEN 'project_context' THEN 0.030
                               ELSE 0.015
                             END
                       )::double precision AS relevance
                FROM public.atlas_memories AS m
                CROSS JOIN search_query AS q
                WHERE m.user_id = %s
                  AND (%s IS NULL OR m.memory_type = %s)
                  AND m.search_document @@ q.terms
                ORDER BY relevance DESC, m.updated_at DESC, m.id
                LIMIT %s
                """,
                (query, user_id, memory_type, memory_type, limit),
            ).fetchall()
        )
        return [MemoryRecord.model_validate(row) for row in rows]

    def _run(self, user_id: str, operation: Callable[[Any], Any]) -> Any:
        if not self._database_url:
            raise MemoryStoreUnavailable(
                "Persistent memory storage is not configured."
            )
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise MemoryStoreUnavailable(
                "Persistent memory storage is unavailable."
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
        except psycopg.errors.UniqueViolation:
            raise MemoryConflict(
                "A memory with this type and key already exists."
            ) from None
        except psycopg.Error:
            raise MemoryStoreUnavailable(
                "Persistent memory storage is unavailable."
            ) from None
