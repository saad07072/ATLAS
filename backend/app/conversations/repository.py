from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from backend.app.conversations.errors import ConversationStoreUnavailable
from backend.app.conversations.models import (
    DEFAULT_CONVERSATION_TITLE,
    ConversationMessage,
    ConversationRecord,
    ConversationRole,
)
from backend.app.memory.models import contains_secret


class ConversationRepository(Protocol):
    def create(self, user_id: str, title: str) -> ConversationRecord: ...

    def list(
        self,
        user_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationRecord], bool]: ...

    def get(
        self,
        user_id: str,
        conversation_id: str,
    ) -> ConversationRecord | None: ...

    def rename(
        self,
        user_id: str,
        conversation_id: str,
        title: str,
    ) -> ConversationRecord | None: ...

    def delete(self, user_id: str, conversation_id: str) -> bool: ...

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[ConversationMessage], bool]: ...

    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        *,
        excluding_message_id: str,
        limit: int,
    ) -> list[ConversationMessage] | None: ...

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        *,
        role: ConversationRole,
        content: str,
    ) -> ConversationMessage | None: ...


class PostgresConversationRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url

    def create(self, user_id: str, title: str) -> ConversationRecord:
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                INSERT INTO public.atlas_conversations (user_id, title)
                VALUES (%s, %s)
                RETURNING id::text AS id, title, created_at, updated_at
                """,
                (user_id, title),
            ).fetchone(),
        )
        return ConversationRecord.model_validate(row)

    def list(
        self,
        user_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationRecord], bool]:
        rows = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                SELECT id::text AS id, title, created_at, updated_at
                FROM public.atlas_conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, limit + 1, offset),
            ).fetchall(),
        )
        has_more = len(rows) > limit
        return (
            [ConversationRecord.model_validate(row) for row in rows[:limit]],
            has_more,
        )

    def get(
        self,
        user_id: str,
        conversation_id: str,
    ) -> ConversationRecord | None:
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                SELECT id::text AS id, title, created_at, updated_at
                FROM public.atlas_conversations
                WHERE user_id = %s AND id = %s
                """,
                (user_id, conversation_id),
            ).fetchone(),
        )
        return ConversationRecord.model_validate(row) if row else None

    def rename(
        self,
        user_id: str,
        conversation_id: str,
        title: str,
    ) -> ConversationRecord | None:
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                UPDATE public.atlas_conversations
                SET title = %s, updated_at = now()
                WHERE user_id = %s AND id = %s
                RETURNING id::text AS id, title, created_at, updated_at
                """,
                (title, user_id, conversation_id),
            ).fetchone(),
        )
        return ConversationRecord.model_validate(row) if row else None

    def delete(self, user_id: str, conversation_id: str) -> bool:
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                DELETE FROM public.atlas_conversations
                WHERE user_id = %s AND id = %s
                RETURNING id
                """,
                (user_id, conversation_id),
            ).fetchone(),
        )
        return row is not None

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[ConversationMessage], bool]:
        def query(connection: Any) -> tuple[list[dict[str, Any]], bool] | None:
            if not self._conversation_exists(connection, user_id, conversation_id):
                return None
            rows = connection.execute(
                """
                SELECT id::text AS id, conversation_id::text AS conversation_id,
                       role, content, created_at
                FROM (
                    SELECT id, conversation_id, role, content, created_at
                    FROM public.atlas_conversation_messages
                    WHERE user_id = %s AND conversation_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s OFFSET %s
                ) AS recent
                ORDER BY created_at ASC, id ASC
                """,
                (user_id, conversation_id, limit + 1, offset),
            ).fetchall()
            return rows, len(rows) > limit

        result = self._run(user_id, query)
        if result is None:
            return [], False
        rows, has_more = result
        return (
            [ConversationMessage.model_validate(row) for row in rows[-limit:]],
            has_more,
        )

    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        *,
        excluding_message_id: str,
        limit: int,
    ) -> list[ConversationMessage] | None:
        def query(connection: Any) -> list[dict[str, Any]] | None:
            if not self._conversation_exists(connection, user_id, conversation_id):
                return None
            rows = connection.execute(
                """
                SELECT id::text AS id, conversation_id::text AS conversation_id,
                       role, content, created_at
                FROM (
                    SELECT id, conversation_id, role, content, created_at
                    FROM public.atlas_conversation_messages
                    WHERE user_id = %s AND conversation_id = %s
                      AND id <> %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                ) AS recent
                ORDER BY created_at ASC, id ASC
                """,
                (user_id, conversation_id, excluding_message_id, limit),
            ).fetchall()
            return rows

        rows = self._run(user_id, query)
        if rows is None:
            return None
        return [ConversationMessage.model_validate(row) for row in rows]

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        *,
        role: ConversationRole,
        content: str,
    ) -> ConversationMessage | None:
        normalized = content.strip()
        if not normalized or len(normalized) > 8000 or contains_secret(normalized):
            raise ValueError("Messages must be valid and must not contain secrets.")

        def insert(connection: Any) -> dict[str, Any] | None:
            if not self._conversation_exists(connection, user_id, conversation_id):
                return None
            row = connection.execute(
                """
                INSERT INTO public.atlas_conversation_messages
                    (user_id, conversation_id, role, content)
                VALUES (%s, %s, %s, %s)
                RETURNING id::text AS id, conversation_id::text AS conversation_id,
                          role, content, created_at
                """,
                (user_id, conversation_id, role, normalized),
            ).fetchone()
            if role == "user":
                connection.execute(
                    """
                    UPDATE public.atlas_conversations
                    SET title = CASE
                            WHEN title = %s THEN left(%s, 80)
                            ELSE title
                        END,
                        updated_at = now()
                    WHERE user_id = %s AND id = %s
                    """,
                    (
                        DEFAULT_CONVERSATION_TITLE,
                        normalized,
                        user_id,
                        conversation_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE public.atlas_conversations
                    SET updated_at = now()
                    WHERE user_id = %s AND id = %s
                    """,
                    (user_id, conversation_id),
                )
            return row

        row = self._run(user_id, insert)
        return ConversationMessage.model_validate(row) if row else None

    @staticmethod
    def _conversation_exists(
        connection: Any,
        user_id: str,
        conversation_id: str,
    ) -> bool:
        return (
            connection.execute(
                """
                SELECT 1
                FROM public.atlas_conversations
                WHERE user_id = %s AND id = %s
                """,
                (user_id, conversation_id),
            ).fetchone()
            is not None
        )

    def _run(self, user_id: str, operation: Callable[[Any], Any]) -> Any:
        if not self._database_url:
            raise ConversationStoreUnavailable(
                "Persistent conversation storage is not configured."
            )
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise ConversationStoreUnavailable(
                "Persistent conversation storage is unavailable."
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
            raise ConversationStoreUnavailable(
                "Persistent conversation storage is unavailable."
            ) from None
