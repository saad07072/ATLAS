from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from cryptography.fernet import Fernet, InvalidToken

from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import GoogleCredentials


class EncryptedSQLiteTokenStore:
    _TOKEN_KEY = "google"

    def __init__(self, path: str, encryption_key: str) -> None:
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None
        self._lock = RLock()
        try:
            self._fernet = Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            raise GoogleIntegrationError(
                "configuration_error",
                "Google token encryption is not configured correctly.",
            ) from None
        self._initialize()

    def save_credentials(self, credentials: GoogleCredentials) -> None:
        encrypted = self._fernet.encrypt(
            credentials.model_dump_json().encode("utf-8")
        )
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO google_credentials (id, payload)
                    VALUES (?, ?)
                    ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                    """,
                    (self._TOKEN_KEY, encrypted),
                )
        except sqlite3.Error:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None

    def load_credentials(self) -> GoogleCredentials | None:
        try:
            with self._lock, closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT payload FROM google_credentials WHERE id = ?",
                    (self._TOKEN_KEY,),
                ).fetchone()
        except sqlite3.Error:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None
        if row is None:
            return None
        try:
            decrypted = self._fernet.decrypt(row[0])
            return GoogleCredentials.model_validate_json(decrypted)
        except (InvalidToken, ValueError):
            raise GoogleIntegrationError(
                "credential_store_error",
                "Stored Google credentials could not be read securely.",
            ) from None

    def delete_credentials(self) -> None:
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    "DELETE FROM google_credentials WHERE id = ?",
                    (self._TOKEN_KEY,),
                )
        except sqlite3.Error:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None

    def store_state(self, state: str, *, expires_at: float) -> None:
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO oauth_states (state_hash, expires_at)
                    VALUES (?, ?)
                    """,
                    (state_hash, expires_at),
                )
        except sqlite3.Error:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None

    def consume_state(self, state: str, *, now: float) -> bool:
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    "DELETE FROM oauth_states WHERE expires_at <= ?",
                    (now,),
                )
                cursor = connection.execute(
                    "DELETE FROM oauth_states WHERE state_hash = ? AND expires_at > ?",
                    (state_hash, now),
                )
                return cursor.rowcount == 1
        except sqlite3.Error:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None

    def _connect(self) -> sqlite3.Connection:
        try:
            return sqlite3.connect(self.path, timeout=5.0)
        except sqlite3.Error:
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None

    def _initialize(self) -> None:
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS google_credentials (
                        id TEXT PRIMARY KEY,
                        payload BLOB NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS oauth_states (
                        state_hash TEXT PRIMARY KEY,
                        expires_at REAL NOT NULL
                    )
                    """
                )
            if self.path.exists():
                self.path.chmod(0o600)
        except (OSError, sqlite3.Error):
            raise GoogleIntegrationError(
                "credential_store_error",
                "Google credential storage is unavailable.",
            ) from None


def credential_expiry(expires_in: int) -> datetime:
    return datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + expires_in,
        timezone.utc,
    )
