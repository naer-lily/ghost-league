"""Players, human/AI identity, and legacy source/target plans."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from .. import calendar as cal
from ..rules import PlayerNotFound
from .core import SOURCE_AI, SOURCE_HUMAN, _row_to_dict

class PlayersMixin:
    """Player identity and the legacy source/target plan tables."""

    def create_player(
        self,
        player_id: str,
        *,
        kind: str,
        display_name: str | None = None,
        joined_week: date | datetime | str,
        last_seen_week: date | datetime | str | None = None,
        source_kind: str | None = None,
        source_key_hash: str | None = None,
        controller: str | None = None,
        is_active: bool = True,
        now: datetime | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if not player_id:
            raise ValueError("player_id must be non-empty")
        if kind not in {"human", "ai"}:
            raise ValueError("kind must be human or ai")
        controller = controller or ("human" if kind == "human" else "ai")
        if controller not in {"human", "ai"}:
            raise ValueError("controller must be human or ai")
        source_kind = source_kind or (SOURCE_HUMAN if kind == "human" else SOURCE_AI)
        joined = cal.iso_date(cal.week_start(joined_week))
        seen = (
            cal.iso_date(cal.week_start(last_seen_week))
            if last_seen_week is not None
            else joined
        )
        created = cal.iso_ts(cal.parse_datetime(now) if now is not None else cal.now_local())
        values = (
            player_id,
            kind,
            controller,
            source_kind,
            source_key_hash,
            display_name or player_id,
            joined,
            seen,
            created,
            1 if is_active else 0,
        )
        if conn is not None:
            self._insert_player(conn, values)
            return self._get_player_with(conn, player_id)
        with self.transaction() as tx:
            self._insert_player(tx, values)
            return self._get_player_with(tx, player_id)

    @staticmethod
    def _insert_player(conn: sqlite3.Connection, values: tuple[Any, ...]) -> None:
        conn.execute(
            "INSERT INTO players (id, kind, controller, source_kind, source_key_hash, "
            "display_name, joined_week, last_seen_week, created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO NOTHING",
            values,
        )

    def get_player(self, player_id: str) -> dict[str, Any]:
        with self._reader() as conn:
            return self._get_player_with(conn, player_id)

    def _get_player_with(
        self, conn: sqlite3.Connection, player_id: str
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            raise PlayerNotFound(player_id)
        return dict(row)

    def get_player_by_source_key_hash(
        self,
        source_key_hash: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """Find the stable AI identity bound to one anonymous source key."""

        sql = (
            "SELECT * FROM players WHERE kind = 'ai' "
            "AND source_key_hash = ? ORDER BY id LIMIT 1"
        )
        if conn is not None:
            row = conn.execute(sql, (source_key_hash,)).fetchone()
            return _row_to_dict(row)
        with self._reader() as reader:
            row = reader.execute(sql, (source_key_hash,)).fetchone()
            return _row_to_dict(row)

    def upsert_ai_player(
        self,
        source_key_hash: str,
        *,
        display_name: str,
        joined_week: date | datetime | str,
        last_seen_week: date | datetime | str,
        now: datetime | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create or refresh one AI player keyed only by ``source_key_hash``.

        Returns ``(player, created)``.  An AI that reappears after a missing
        week keeps its original player id and history; only the freshness
        marker moves forward.
        """

        seen = cal.iso_date(cal.week_start(last_seen_week))
        joined = cal.iso_date(cal.week_start(joined_week))
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        if conn is not None:
            return self._upsert_ai_player_with(
                conn,
                source_key_hash,
                display_name=display_name,
                joined_week=joined,
                last_seen_week=seen,
                now=local_now,
            )
        with self.transaction() as tx:
            return self._upsert_ai_player_with(
                tx,
                source_key_hash,
                display_name=display_name,
                joined_week=joined,
                last_seen_week=seen,
                now=local_now,
            )

    def _upsert_ai_player_with(
        self,
        conn: sqlite3.Connection,
        source_key_hash: str,
        *,
        display_name: str,
        joined_week: str,
        last_seen_week: str,
        now: datetime,
    ) -> tuple[dict[str, Any], bool]:
        row = conn.execute(
            "SELECT * FROM players WHERE kind = 'ai' "
            "AND source_key_hash = ? ORDER BY id LIMIT 1",
            (source_key_hash,),
        ).fetchone()
        if row is not None:
            player_id = str(row["id"])
            conn.execute(
                "UPDATE players SET display_name = ?, last_seen_week = ?, "
                "is_active = 1 WHERE id = ?",
                (display_name, last_seen_week, player_id),
            )
            return self._get_player_with(conn, player_id), False
        player_id = f"ai-{source_key_hash[:12]}"
        conn.execute(
            "INSERT INTO players "
            "(id, kind, controller, source_kind, source_key_hash, display_name, "
            "joined_week, last_seen_week, created_at, is_active) "
            "VALUES (?, 'ai', 'ai', ?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(id) DO NOTHING",
            (
                player_id,
                SOURCE_AI,
                source_key_hash,
                display_name,
                joined_week,
                last_seen_week,
                cal.iso_ts(now),
            ),
        )
        # A hash-prefix collision must never make two sources share one AI.
        stored = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if stored is not None and stored["source_key_hash"] != source_key_hash:
            player_id = f"ai-{source_key_hash}"
            conn.execute(
                "INSERT INTO players "
                "(id, kind, controller, source_kind, source_key_hash, display_name, "
                "joined_week, last_seen_week, created_at, is_active) "
                "VALUES (?, 'ai', 'ai', ?, ?, ?, ?, ?, ?, 1)",
                (
                    player_id,
                    SOURCE_AI,
                    source_key_hash,
                    display_name,
                    joined_week,
                    last_seen_week,
                    cal.iso_ts(now),
                ),
            )
        return self._get_player_with(conn, player_id), True

    def list_players(
        self, *, kind: str | None = None, active_only: bool = True
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM players WHERE 1 = 1"
        params: list[Any] = []
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY id"
        with self._reader() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def set_player_active(self, player_id: str, active: bool) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE players SET is_active = ? WHERE id = ?",
                (1 if active else 0, player_id),
            )

    def ensure_human_player(
        self,
        player_id: str,
        *,
        display_name: str,
        joined_week: date | datetime | str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Create or refresh the human player bound to one account.

        Account rows are the identity source.  The game row only mirrors the
        public display name and stays active so a restart or a late account
        creation always produces a groupable human.
        """

        joined = cal.iso_date(cal.week_start(joined_week))
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM players WHERE id = ?", (player_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO players "
                    "(id, kind, controller, source_kind, source_key_hash, "
                    "display_name, joined_week, last_seen_week, created_at, is_active) "
                    "VALUES (?, 'human', 'human', ?, NULL, ?, ?, ?, ?, 1)",
                    (
                        player_id,
                        SOURCE_HUMAN,
                        display_name,
                        joined,
                        joined,
                        cal.iso_ts(local_now),
                    ),
                )
            else:
                conn.execute(
                    "UPDATE players SET display_name = ?, last_seen_week = ?, "
                    "is_active = 1 WHERE id = ? AND kind = 'human'",
                    (display_name, joined, player_id),
                )
            return self._get_player_with(conn, player_id)

    def upsert_source(
        self,
        source_key_hash: str,
        *,
        anchor_seconds: int,
        anchor_week: date | datetime | str,
        fetched_at: datetime | str,
        effective_seconds: int | None = None,
        p75_seconds: int = 0,
        normalization_version: str = "legacy",
        stale_weeks: int = 0,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Persist raw and effective source values together.

        ``effective_seconds`` defaults to the raw anchor so older callers keep
        working; the roster always supplies the normalized value explicitly.
        """

        if isinstance(anchor_seconds, bool) or anchor_seconds < 0:
            raise ValueError("anchor_seconds must be non-negative")
        effective = anchor_seconds if effective_seconds is None else effective_seconds
        if isinstance(effective, bool) or effective < 0:
            raise ValueError("effective_seconds must be non-negative")
        if isinstance(p75_seconds, bool) or p75_seconds < 0:
            raise ValueError("p75_seconds must be non-negative")
        if not isinstance(normalization_version, str) or not normalization_version:
            raise ValueError("normalization_version must be a non-empty string")
        week_iso = cal.iso_date(cal.week_start(anchor_week))
        fetched = cal.iso_ts(cal.parse_datetime(fetched_at))
        values = (
            source_key_hash,
            int(anchor_seconds),
            int(effective),
            int(p75_seconds),
            normalization_version,
            week_iso,
            fetched,
            stale_weeks,
        )
        if conn is not None:
            return self._upsert_source_with(conn, values)
        with self.transaction() as tx:
            return self._upsert_source_with(tx, values)

    @staticmethod
    def _upsert_source_with(conn: sqlite3.Connection, values: tuple[Any, ...]) -> int:
        conn.execute(
            "INSERT INTO sources (source_key_hash, anchor_seconds, "
            "effective_seconds, p75_seconds, normalization_version, "
            "anchor_week, fetched_at, stale_weeks) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source_key_hash) DO UPDATE SET "
            "anchor_seconds = excluded.anchor_seconds, "
            "effective_seconds = excluded.effective_seconds, "
            "p75_seconds = excluded.p75_seconds, "
            "normalization_version = excluded.normalization_version, "
            "anchor_week = excluded.anchor_week, "
            "fetched_at = excluded.fetched_at, "
            "stale_weeks = excluded.stale_weeks",
            values,
        )
        row = conn.execute(
            "SELECT id FROM sources WHERE source_key_hash = ?", (values[0],)
        ).fetchone()
        return int(row["id"])

    def get_source(self, source_key_hash: str) -> dict[str, Any] | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM sources WHERE source_key_hash = ?",
                (source_key_hash,),
            ).fetchone()
            return _row_to_dict(row)

    # ------------------------------------------------------------------
    # AI weekly target plans
    # ------------------------------------------------------------------
    def upsert_opponent_week_plan(
        self,
        player_id: str,
        week: date | datetime | str,
        *,
        anchor_seconds: int,
        target_seconds: int,
        percentile: float,
        seed: str,
        algorithm_version: str,
        target_xp: int | None = None,
        created_at: datetime | str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Persist one immutable ``(player_id, week_start)`` target plan.

        Re-running the deterministic seed for the same week keeps the first
        plan.  A plan is never silently rewritten from a later anchor refresh,
        so the AI target is locked when the week is created.
        """

        if isinstance(anchor_seconds, bool) or anchor_seconds < 0:
            raise ValueError("anchor_seconds must be non-negative")
        if isinstance(target_seconds, bool) or target_seconds < 0:
            raise ValueError("target_seconds must be non-negative")
        xp = target_seconds // 6 if target_xp is None else target_xp
        if isinstance(xp, bool) or xp < 0:
            raise ValueError("target_xp must be non-negative")
        if percentile < 0 or percentile > 1:
            raise ValueError("percentile must be in 0..1")
        if not seed:
            raise ValueError("seed must be non-empty")
        if not algorithm_version:
            raise ValueError("algorithm_version must be non-empty")
        week_iso = cal.iso_date(cal.week_start(week))
        created = cal.iso_ts(
            cal.parse_datetime(created_at) if created_at is not None else cal.now_local()
        )
        values = (
            player_id,
            week_iso,
            int(anchor_seconds),
            int(target_seconds),
            int(xp),
            float(percentile),
            str(seed),
            str(algorithm_version),
            created,
        )
        if conn is not None:
            self._upsert_opponent_week_plan_with(conn, values)
            return self._get_opponent_week_plan_with(conn, player_id, week_iso)
        with self.transaction() as tx:
            self._upsert_opponent_week_plan_with(tx, values)
            return self._get_opponent_week_plan_with(tx, player_id, week_iso)

    @staticmethod
    def _upsert_opponent_week_plan_with(
        conn: sqlite3.Connection, values: tuple[Any, ...]
    ) -> None:
        conn.execute(
            "INSERT INTO opponent_week_plan "
            "(player_id, week_start, anchor_seconds, target_seconds, target_xp, "
            "percentile, seed, algorithm_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(player_id, week_start) DO NOTHING",
            values,
        )

    @staticmethod
    def _get_opponent_week_plan_with(
        conn: sqlite3.Connection, player_id: str, week_iso: str
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM opponent_week_plan "
            "WHERE player_id = ? AND week_start = ?",
            (player_id, week_iso),
        ).fetchone()
        if row is None:
            raise PlayerNotFound(f"no opponent week plan for {player_id} {week_iso}")
        return dict(row)

    def get_opponent_week_plan(
        self, player_id: str, week: date | datetime | str
    ) -> dict[str, Any] | None:
        week_iso = cal.iso_date(cal.week_start(week))
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM opponent_week_plan "
                "WHERE player_id = ? AND week_start = ?",
                (player_id, week_iso),
            ).fetchone()
            return _row_to_dict(row)

    def list_opponent_week_plans(
        self, week: date | datetime | str
    ) -> list[dict[str, Any]]:
        week_iso = cal.iso_date(cal.week_start(week))
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM opponent_week_plan WHERE week_start = ? "
                "ORDER BY player_id",
                (week_iso,),
            ).fetchall()
            return [dict(row) for row in rows]
