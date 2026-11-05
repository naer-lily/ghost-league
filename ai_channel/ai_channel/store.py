"""Local SQLite state for the AI channel.

This database is a Channel secret: it stores ordinary account tokens so ticks
can act later.  The file is created with mode ``0600`` and tokens are never
printed by the CLI.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    token TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    seconds INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, event_id)
);
"""


class StateStore:
    """Account ownership plus a small idempotent run log."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def _now(self) -> str:
        return self._now_fn().isoformat(timespec="seconds")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _restrict_permissions(self) -> None:
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.executescript(SCHEMA)
        self._restrict_permissions()

    def save_account(self, user_id: str, display_name: str, token: str) -> None:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be a non-empty string")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("display_name must be a non-empty string")
        if not isinstance(token, str) or not token:
            raise ValueError("token must be a non-empty string")
        created_at = self._now()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO accounts (user_id, display_name, token, created_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "display_name = excluded.display_name, "
                    "token = excluded.token, "
                    "created_at = excluded.created_at",
                    (user_id, display_name, token, created_at),
                )
        self._restrict_permissions()

    def get_account(
        self, user_id: str, *, include_token: bool = False
    ) -> dict[str, Any] | None:
        columns = "user_id, display_name, created_at"
        if include_token:
            columns += ", token"
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {columns} FROM accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_accounts(self, *, include_tokens: bool = False) -> list[dict[str, Any]]:
        columns = "user_id, display_name, created_at"
        if include_tokens:
            columns += ", token"
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM accounts ORDER BY created_at, user_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def record_run(
        self,
        user_id: str,
        event_id: str,
        seconds: int,
        created_at: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO runs "
                    "(user_id, event_id, seconds, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, event_id, int(seconds), created_at or self._now()),
                )


__all__ = ["SCHEMA", "StateStore"]
