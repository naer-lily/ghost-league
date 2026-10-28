"""Connection, schema, migrations, and shared week/meta helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .. import calendar as cal
from ..progression import CATALOG_ITEMS, CATALOG_TITLES

SCHEMA_VERSION = "3"
ALGORITHM_VERSION = "phase1-v1"
DEFAULT_DB_PATH = Path("data/league/league.db")
SOURCE_AI = "wakatime_public_leaderboard"
SOURCE_HUMAN = "local_increment"
SOURCE_CHANNEL = "channel_ingest"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS epochs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived'))
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('human', 'ai')),
    controller TEXT NOT NULL CHECK (controller IN ('human', 'ai')),
    source_kind TEXT NOT NULL,
    source_key_hash TEXT,
    display_name TEXT NOT NULL,
    joined_week TEXT NOT NULL,
    last_seen_week TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key_hash TEXT NOT NULL UNIQUE,
    anchor_seconds INTEGER NOT NULL CHECK (anchor_seconds >= 0),
    effective_seconds INTEGER NOT NULL DEFAULT 0
        CHECK (effective_seconds >= 0),
    p75_seconds INTEGER NOT NULL DEFAULT 0 CHECK (p75_seconds >= 0),
    normalization_version TEXT NOT NULL DEFAULT 'legacy',
    anchor_week TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    stale_weeks INTEGER NOT NULL DEFAULT 0 CHECK (stale_weeks >= 0)
);

CREATE TABLE IF NOT EXISTS opponent_week_plan (
    player_id TEXT NOT NULL,
    week_start TEXT NOT NULL,
    anchor_seconds INTEGER NOT NULL CHECK (anchor_seconds >= 0),
    target_seconds INTEGER NOT NULL CHECK (target_seconds >= 0),
    target_xp INTEGER NOT NULL CHECK (target_xp >= 0),
    percentile REAL NOT NULL CHECK (percentile >= 0 AND percentile <= 1),
    seed TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (player_id, week_start)
);
CREATE INDEX IF NOT EXISTS idx_opponent_plan_week
    ON opponent_week_plan (week_start);

CREATE TABLE IF NOT EXISTS channel_players (
    channel_id TEXT NOT NULL,
    player_ref TEXT NOT NULL,
    player_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('human', 'ai')),
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, player_ref)
);
CREATE INDEX IF NOT EXISTS idx_channel_players_player
    ON channel_players (player_id);

CREATE TABLE IF NOT EXISTS channel_events (
    event_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    player_ref TEXT NOT NULL,
    player_id TEXT NOT NULL,
    seconds INTEGER NOT NULL CHECK (seconds >= 0),
    occurred_at TEXT NOT NULL,
    week_start TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_events_player
    ON channel_events (player_id, week_start);

CREATE TABLE IF NOT EXISTS channel_week_roster (
    week_start TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    player_ref TEXT NOT NULL,
    player_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (week_start, channel_id, player_ref)
);
CREATE INDEX IF NOT EXISTS idx_channel_week_roster_player
    ON channel_week_roster (player_id, week_start);

CREATE TABLE IF NOT EXISTS activity_events (
    player_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    seconds INTEGER NOT NULL CHECK (seconds >= 0),
    occurred_at TEXT NOT NULL,
    week_start TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (player_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_activity_player_week
    ON activity_events (player_id, week_start);
CREATE INDEX IF NOT EXISTS idx_activity_player_occurred
    ON activity_events (player_id, occurred_at);

CREATE TABLE IF NOT EXISTS weeks (
    week_start TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'locked', 'settled')),
    settled_at TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    tier TEXT NOT NULL,
    group_no INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (week_start, tier, group_no)
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    tier_at_start TEXT NOT NULL,
    is_human INTEGER NOT NULL CHECK (is_human IN (0, 1)),
    joined_at TEXT NOT NULL,
    UNIQUE (group_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_group_members_player
    ON group_members (player_id);

CREATE TABLE IF NOT EXISTS weekly_scores (
    week_start TEXT NOT NULL,
    player_id TEXT NOT NULL,
    group_id INTEGER,
    seconds INTEGER NOT NULL DEFAULT 0 CHECK (seconds >= 0),
    xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
    locked_at TEXT,
    rank INTEGER,
    promoted INTEGER NOT NULL DEFAULT 0 CHECK (promoted IN (0, 1)),
    demoted INTEGER NOT NULL DEFAULT 0 CHECK (demoted IN (0, 1)),
    PRIMARY KEY (week_start, player_id)
);

CREATE TABLE IF NOT EXISTS weekly_results (
    week_start TEXT NOT NULL,
    player_id TEXT NOT NULL,
    group_id INTEGER NOT NULL,
    tier TEXT NOT NULL,
    rank INTEGER NOT NULL,
    xp INTEGER NOT NULL,
    promoted INTEGER NOT NULL DEFAULT 0 CHECK (promoted IN (0, 1)),
    demoted INTEGER NOT NULL DEFAULT 0 CHECK (demoted IN (0, 1)),
    repaired_days INTEGER NOT NULL DEFAULT 0,
    clean_checkins INTEGER NOT NULL DEFAULT 0,
    settled_at TEXT NOT NULL,
    PRIMARY KEY (week_start, player_id)
);

CREATE TABLE IF NOT EXISTS checkins (
    player_id TEXT NOT NULL,
    date TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('verified', 'repaired')),
    seconds INTEGER NOT NULL CHECK (seconds >= 0),
    xp INTEGER NOT NULL CHECK (xp >= 0),
    checked_at TEXT NOT NULL,
    repaired_at TEXT,
    repair_cost INTEGER NOT NULL DEFAULT 0 CHECK (repair_cost >= 0),
    status TEXT NOT NULL,
    PRIMARY KEY (player_id, date)
);

CREATE TABLE IF NOT EXISTS feed_events (
    id INTEGER PRIMARY KEY,
    player_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    day TEXT NOT NULL,
    week_start TEXT NOT NULL,
    body TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (player_id, kind, day)
);
CREATE INDEX IF NOT EXISTS idx_feed_events_created
    ON feed_events (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_feed_events_player
    ON feed_events (player_id, week_start);

CREATE TABLE IF NOT EXISTS feed_reactions (
    event_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    emoji TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (event_id, actor_id, emoji)
);
CREATE INDEX IF NOT EXISTS idx_feed_reactions_event
    ON feed_reactions (event_id);

CREATE TABLE IF NOT EXISTS feed_tags (
    event_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (event_id, actor_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_feed_tags_event
    ON feed_tags (event_id);

CREATE TABLE IF NOT EXISTS ember_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    week_start TEXT NOT NULL,
    delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    reason TEXT NOT NULL,
    ref TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ember_ledger_player
    ON ember_ledger (player_id, week_start);

CREATE TABLE IF NOT EXISTS ember_balance (
    player_id TEXT PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    week_earned INTEGER NOT NULL DEFAULT 0 CHECK (week_earned >= 0),
    week_start TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS streaks (
    player_id TEXT PRIMARY KEY,
    current INTEGER NOT NULL DEFAULT 0 CHECK (current >= 0),
    longest INTEGER NOT NULL DEFAULT 0 CHECK (longest >= 0),
    clean_current INTEGER NOT NULL DEFAULT 0 CHECK (clean_current >= 0),
    last_checked_date TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS milestones (
    player_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    awarded_at TEXT NOT NULL,
    week_start TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (player_id, milestone_id)
);
CREATE INDEX IF NOT EXISTS idx_milestones_player
    ON milestones (player_id, awarded_at);

CREATE TABLE IF NOT EXISTS catalog_titles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slot TEXT NOT NULL CHECK (slot IN ('frame', 'backdrop', 'badge_accent')),
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_titles (
    player_id TEXT NOT NULL,
    title_id TEXT NOT NULL,
    awarded_at TEXT NOT NULL,
    season_id TEXT,
    UNIQUE (player_id, title_id)
);

CREATE TABLE IF NOT EXISTS player_items (
    player_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    awarded_at TEXT NOT NULL,
    season_id TEXT,
    UNIQUE (player_id, item_id)
);

CREATE TABLE IF NOT EXISTS loadouts (
    player_id TEXT PRIMARY KEY,
    title_id TEXT,
    frame_id TEXT,
    backdrop_id TEXT,
    badge_accent_id TEXT,
    updated_at TEXT NOT NULL
);
"""

_TABLE_NAMES = (
    "meta",
    "epochs",
    "players",
    "sources",
    "opponent_week_plan",
    "channel_players",
    "channel_events",
    "channel_week_roster",
    "activity_events",
    "weeks",
    "groups",
    "group_members",
    "weekly_scores",
    "weekly_results",
    "checkins",
    "feed_events",
    "feed_reactions",
    "feed_tags",
    "ember_ledger",
    "ember_balance",
    "streaks",
    "milestones",
    "catalog_titles",
    "catalog_items",
    "player_titles",
    "player_items",
    "loadouts",
)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class CoreMixin:
    """Transactional access to one ``league.db`` file."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        initialize: bool = True,
        epoch_reason: str = "initialize",
        epoch_started_at: datetime | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DB_PATH
        self._epoch_reason = epoch_reason
        self._epoch_started_at = epoch_started_at
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if initialize:
            self.initialize()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def initialize(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            had_old_progression_data = (
                self._table_count(conn, "checkins") > 0
                or self._table_count(conn, "weekly_results") > 0
            )
            conn.executescript(_SCHEMA)
            self._migrate_sources(conn)
            self._migrate_players(conn)
            now = cal.iso_ts(
                cal.parse_datetime(self._epoch_started_at)
                if self._epoch_started_at is not None
                else cal.now_local()
            )
            self._seed_catalog(conn)
            self._seed_progression_start(
                conn,
                now=now,
                had_old_data=had_old_progression_data,
            )
            defaults = {
                "schema_version": SCHEMA_VERSION,
                "algorithm_version": ALGORITHM_VERSION,
            }
            for key, value in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    (key, value),
                )
            conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                (SCHEMA_VERSION,),
            )
            epoch = conn.execute(
                "SELECT id FROM epochs WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if epoch is None:
                cursor = conn.execute(
                    "INSERT INTO epochs (started_at, reason, status) VALUES (?, ?, 'active')",
                    (now, self._epoch_reason),
                )
                epoch_id = int(cursor.lastrowid)
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('epoch_id', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(epoch_id),),
                )
            else:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('epoch_id', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(epoch["id"]),),
                )
        finally:
            conn.close()

    @staticmethod
    def _table_count(conn: sqlite3.Connection, table: str) -> int:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

    @staticmethod
    def _seed_catalog(conn: sqlite3.Connection) -> None:
        for row in CATALOG_TITLES:
            conn.execute(
                "INSERT INTO catalog_titles (id, name, description) "
                "VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "name = excluded.name, description = excluded.description",
                (row["id"], row["name"], row["description"]),
            )
        for row in CATALOG_ITEMS:
            conn.execute(
                "INSERT INTO catalog_items (id, name, slot, description) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "name = excluded.name, slot = excluded.slot, "
                "description = excluded.description",
                (row["id"], row["name"], row["slot"], row["description"]),
            )

    def _seed_progression_start(
        self,
        conn: sqlite3.Connection,
        *,
        now: str,
        had_old_data: bool,
    ) -> None:
        existing = conn.execute(
            "SELECT 1 FROM meta WHERE key = 'progression_started_at'"
        ).fetchone()
        if existing is not None:
            return
        if self._epoch_started_at is not None:
            start = cal.iso_ts(cal.parse_datetime(self._epoch_started_at))
        elif had_old_data:
            # Existing databases may carry old check-ins/results.  They never
            # feed the new progression layer retroactively.
            start = now
        else:
            # A freshly created database has no history to protect.  Tests and
            # late Channel events may legitimately carry earlier timestamps.
            start = "1970-01-01T00:00:00+08:00"
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('progression_started_at', ?)",
            (start,),
        )

    @staticmethod
    def _migrate_sources(conn: sqlite3.Connection) -> None:
        """Add source-normalization columns to an older database in place.

        Existing rows keep their raw value as the effective value and are
        marked ``legacy``; future upserts always write explicit normalization
        metadata.  Added columns stay backward compatible with old callers.
        """

        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(sources)")
        }
        added_effective = "effective_seconds" not in columns
        if added_effective:
            conn.execute(
                "ALTER TABLE sources ADD COLUMN effective_seconds INTEGER "
                "NOT NULL DEFAULT 0 CHECK (effective_seconds >= 0)"
            )
        if "p75_seconds" not in columns:
            conn.execute(
                "ALTER TABLE sources ADD COLUMN p75_seconds INTEGER "
                "NOT NULL DEFAULT 0 CHECK (p75_seconds >= 0)"
            )
        if "normalization_version" not in columns:
            conn.execute(
                "ALTER TABLE sources ADD COLUMN normalization_version TEXT "
                "NOT NULL DEFAULT 'legacy'"
            )
        if added_effective:
            conn.execute(
                "UPDATE sources SET effective_seconds = anchor_seconds "
                "WHERE effective_seconds = 0"
            )

    @staticmethod
    def _migrate_players(conn: sqlite3.Connection) -> None:
        """Add the weekly roster freshness marker to an older database.

        Existing AI players keep their history.  Their first ``last_seen_week``
        is backfilled from the latest locked weekly plan, falling back to the
        week they joined when no plan exists.
        """

        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(players)")
        }
        if "last_seen_week" not in columns:
            conn.execute(
                "ALTER TABLE players ADD COLUMN last_seen_week TEXT "
                "NOT NULL DEFAULT ''"
            )
        conn.execute(
            "UPDATE players SET last_seen_week = COALESCE("
            "(SELECT MAX(week_start) FROM opponent_week_plan "
            " WHERE opponent_week_plan.player_id = players.id), "
            "joined_week) WHERE last_seen_week = ''"
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def integrity_check(self) -> str:
        with self._reader() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return str(row[0])

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._reader() as conn:
            existing = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for table in _TABLE_NAMES:
                if table not in existing:
                    counts[table] = 0
                    continue
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                counts[table] = int(row["n"])
        return counts

    # ------------------------------------------------------------------
    # Meta / epochs / weeks
    # ------------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        with self._reader() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str, *, conn: sqlite3.Connection | None = None) -> None:
        if conn is not None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
            return
        with self.transaction() as tx:
            tx.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def meta_snapshot(self) -> dict[str, str]:
        with self._reader() as conn:
            return {
                str(row["key"]): str(row["value"])
                for row in conn.execute("SELECT key, value FROM meta ORDER BY key")
            }

    def active_epoch(self) -> dict[str, Any] | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM epochs WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return _row_to_dict(row)

    def create_epoch(self, *, reason: str, now: datetime | None = None) -> int:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE epochs SET status = 'archived' WHERE status = 'active'"
            )
            cursor = conn.execute(
                "INSERT INTO epochs (started_at, reason, status) VALUES (?, ?, 'active')",
                (cal.iso_ts(local_now), reason),
            )
            epoch_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('epoch_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(epoch_id),),
            )
            return epoch_id

    def ensure_week(
        self,
        week: date | datetime | str,
        *,
        status: str = "active",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        week_iso = cal.iso_date(cal.week_start(week))
        if status not in {"active", "locked", "settled"}:
            raise ValueError(f"unknown week status: {status}")
        if conn is not None:
            return self._ensure_week_with(conn, week_iso, status)
        with self.transaction() as tx:
            return self._ensure_week_with(tx, week_iso, status)

    def _ensure_week_with(
        self, conn: sqlite3.Connection, week_iso: str, status: str
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM weeks WHERE week_start = ?", (week_iso,)
        ).fetchone()
        if row is not None:
            return dict(row)
        epoch_id = self._epoch_id(conn)
        conn.execute(
            "INSERT INTO weeks (week_start, epoch_id, status, settled_at) "
            "VALUES (?, ?, ?, NULL)",
            (week_iso, epoch_id, status),
        )
        row = conn.execute(
            "SELECT * FROM weeks WHERE week_start = ?", (week_iso,)
        ).fetchone()
        return dict(row)

    def get_week(self, week: date | datetime | str) -> dict[str, Any] | None:
        week_iso = cal.iso_date(cal.week_start(week))
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM weeks WHERE week_start = ?", (week_iso,)
            ).fetchone()
            return _row_to_dict(row)

    def _epoch_id(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT id FROM epochs WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO epochs (started_at, reason, status) VALUES (?, ?, 'active')",
                (cal.iso_ts(cal.now_local()), "implicit"),
            )
            return int(cursor.lastrowid)
        return int(row["id"])
