from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import GoogleCredentials


class PostgresGoogleCredentialStore:
    def __init__(self, database_url: str | None, encryption_key: str | None) -> None:
        if not database_url:
            raise GoogleIntegrationError(
                "configuration_error",
                "Google credential storage is not configured.",
            )
        if not encryption_key:
            raise GoogleIntegrationError(
                "configuration_error",
                "Google token encryption is not configured.",
            )
        self._database_url = database_url
        try:
            self._fernet = Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            raise GoogleIntegrationError(
                "configuration_error",
                "Google token encryption is not configured correctly.",
            ) from None

    def save_credentials(
        self,
        user_id: str,
        credentials: GoogleCredentials,
    ) -> None:
        encrypted = self._fernet.encrypt(
            credentials.model_dump_json().encode("utf-8")
        )
        self._run(
            user_id,
            lambda connection: connection.execute(
                """
                INSERT INTO public.atlas_google_connections
                    (user_id, credentials_ciphertext, updated_at)
                VALUES (%s::uuid, %s, now())
                ON CONFLICT (user_id) DO UPDATE
                SET credentials_ciphertext = EXCLUDED.credentials_ciphertext,
                    updated_at = now()
                """,
                (user_id, encrypted),
            ),
        )

    def load_credentials(self, user_id: str) -> GoogleCredentials | None:
        row = self._run(
            user_id,
            lambda connection: connection.execute(
                """
                SELECT credentials_ciphertext
                FROM public.atlas_google_connections
                WHERE user_id = %s::uuid
                """,
                (user_id,),
            ).fetchone(),
        )
        if row is None:
            return None
        try:
            plaintext = self._fernet.decrypt(row["credentials_ciphertext"])
            return GoogleCredentials.model_validate_json(plaintext)
        except (InvalidToken, ValueError):
            raise GoogleIntegrationError(
                "credential_store_error",
                "Stored Google credentials could not be read securely.",
            ) from None

    def delete_credentials(self, user_id: str) -> None:
        self._run(
            user_id,
            lambda connection: connection.execute(
                """
                DELETE FROM public.atlas_google_connections
                WHERE user_id = %s::uuid
                """,
                (user_id,),
            ),
        )

    def store_state(
        self,
        user_id: str,
        state: str,
        binding_hash: str,
        *,
        expires_at: float,
    ) -> None:
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        expiry = datetime.fromtimestamp(expires_at, timezone.utc)
        self._run(
            user_id,
            lambda connection: connection.execute(
                """
                INSERT INTO public.atlas_google_oauth_states
                    (state_hash, user_id, binding_hash, expires_at)
                VALUES (%s, %s::uuid, %s, %s)
                """,
                (state_hash, user_id, binding_hash, expiry),
            ),
        )

    def consume_state(
        self,
        state: str,
        binding_hash: str,
        *,
        now: float,
    ) -> str | None:
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        current_time = datetime.fromtimestamp(now, timezone.utc)

        def consume(connection: Any) -> str | None:
            connection.execute(
                """
                DELETE FROM public.atlas_google_oauth_states
                WHERE expires_at <= %s
                """,
                (current_time,),
            )
            row = connection.execute(
                """
                DELETE FROM public.atlas_google_oauth_states
                WHERE state_hash = %s AND binding_hash = %s
                  AND expires_at > %s
                RETURNING user_id::text AS user_id
                """,
                (state_hash, binding_hash, current_time),
            ).fetchone()
            return row["user_id"] if row else None

        return self._run_backend(consume)

    def _run(
        self,
        user_id: str,
        operation: Callable[[Any], Any],
    ) -> Any:
        claims = json.dumps(
            {
                "aud": "authenticated",
                "role": "authenticated",
                "sub": user_id,
                "atlas_backend": "true",
            }
        )
        return self._execute(
            operation,
            claims=claims,
            user_id=user_id,
        )

    def _run_backend(self, operation: Callable[[Any], Any]) -> Any:
        claims = json.dumps(
            {
                "aud": "authenticated",
                "role": "authenticated",
                "atlas_backend": "true",
            }
        )
        return self._execute(operation, claims=claims)

    def _execute(
        self,
        operation: Callable[[Any], Any],
        *,
        claims: str,
        user_id: str | None = None,
    ) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None

        try:
            with psycopg.connect(
                self._database_url,
                row_factory=dict_row,
                connect_timeout=5,
            ) as connection:
                connection.execute("SET LOCAL ROLE authenticated")
                connection.execute(
                    """
                    SELECT set_config('request.jwt.claim.sub', %s, true),
                           set_config('request.jwt.claims', %s, true)
                    """,
                    (user_id or "", claims),
                )
                return operation(connection)
        except psycopg.Error:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None
