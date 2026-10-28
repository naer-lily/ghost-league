"""Small persistence helpers for one-way follows.

Follows deliberately live in their own SQLite database.  The account database
stores credentials and the league state stores simulation data; keeping social
state separate makes it hard to accidentally expose either through a profile
join in the future.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .schedule import TZ


class FollowStore:
    """Idempotent one-way follow relationships."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._now_fn = now_fn or (lambda: datetime.now(TZ))
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS follows (
                    follower_id TEXT NOT NULL,
                    followee_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (follower_id, followee_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_follows_followee
                ON follows (followee_id)
                """
            )
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    def follow(self, follower_id: str, followee_id: str) -> bool:
        """Insert a follow; return True when it was newly created."""

        created_at = self._now_fn().isoformat(timespec="seconds")
        with self._lock, sqlite3.connect(self.db_path, timeout=10) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO follows (follower_id, followee_id, created_at) "
                "VALUES (?, ?, ?)",
                (follower_id, followee_id, created_at),
            )
            return cursor.rowcount == 1

    def unfollow(self, follower_id: str, followee_id: str) -> bool:
        with self._lock, sqlite3.connect(self.db_path, timeout=10) as connection:
            cursor = connection.execute(
                "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?",
                (follower_id, followee_id),
            )
            return cursor.rowcount > 0

    def is_following(self, follower_id: str, followee_id: str) -> bool:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            row = connection.execute(
                "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
                (follower_id, followee_id),
            ).fetchone()
        return row is not None

    def following_ids(self, follower_id: str) -> list[str]:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            rows = connection.execute(
                "SELECT followee_id FROM follows WHERE follower_id = ? "
                "ORDER BY created_at DESC, followee_id",
                (follower_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def follower_ids(self, followee_id: str) -> list[str]:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            rows = connection.execute(
                "SELECT follower_id FROM follows WHERE followee_id = ? "
                "ORDER BY created_at DESC, follower_id",
                (followee_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def counts(self, user_id: str) -> tuple[int, int]:
        """Return ``(following_count, followers_count)`` for one user."""

        with sqlite3.connect(self.db_path, timeout=10) as connection:
            following = connection.execute(
                "SELECT COUNT(*) FROM follows WHERE follower_id = ?",
                (user_id,),
            ).fetchone()[0]
            followers = connection.execute(
                "SELECT COUNT(*) FROM follows WHERE followee_id = ?",
                (user_id,),
            ).fetchone()[0]
        return int(following), int(followers)


__all__ = ["FollowStore"]
