from __future__ import annotations

import sqlite3
from pathlib import Path

from ghost_league.game.store import GameStore

WEEK = "2026-11-02"
NOW = "2026-11-05T12:00:00+08:00"


def _make_old_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE players (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('human', 'ai')),
                controller TEXT NOT NULL CHECK (controller IN ('human', 'ai')),
                source_kind TEXT NOT NULL,
                source_key_hash TEXT,
                display_name TEXT NOT NULL,
                joined_week TEXT NOT NULL,
                last_seen_week TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                power INTEGER,
                power_percentile REAL,
                power_week TEXT,
                power_updated_at TEXT,
                power_provisional INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE channel_players (
                channel_id TEXT NOT NULL,
                player_ref TEXT NOT NULL,
                player_id TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK (kind IN ('human', 'ai')),
                profile_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, player_ref)
            );
            CREATE INDEX idx_channel_players_player
                ON channel_players (player_id);
            CREATE TABLE group_members (
                group_id INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                tier_at_start TEXT NOT NULL,
                is_human INTEGER NOT NULL CHECK (is_human IN (0, 1)),
                joined_at TEXT NOT NULL,
                UNIQUE (group_id, player_id)
            );
            CREATE TABLE weekly_scores (
                week_start TEXT NOT NULL,
                player_id TEXT NOT NULL,
                group_id INTEGER,
                seconds INTEGER NOT NULL DEFAULT 0 CHECK (seconds >= 0),
                xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
                locked_at TEXT,
                rank INTEGER,
                promoted INTEGER NOT NULL DEFAULT 0
                    CHECK (promoted IN (0, 1)),
                demoted INTEGER NOT NULL DEFAULT 0 CHECK (demoted IN (0, 1)),
                PRIMARY KEY (week_start, player_id)
            );
            CREATE TABLE diamond_balance (
                player_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO players "
            "(id, kind, controller, source_kind, source_key_hash, display_name, "
            "joined_week, last_seen_week, created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            [
                (
                    "local-old",
                    "human",
                    "human",
                    "local_increment",
                    None,
                    "Local Old",
                    WEEK,
                    WEEK,
                    NOW,
                ),
                (
                    "waka-old",
                    "ai",
                    "ai",
                    "wakatime_public_leaderboard",
                    "source-hash-old",
                    "Waka Old",
                    WEEK,
                    WEEK,
                    NOW,
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO channel_players "
            "(channel_id, player_ref, player_id, kind, profile_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "waka",
                    "ref-old",
                    "waka-old",
                    "ai",
                    '{"display_name":"Waka Old"}',
                    NOW,
                    NOW,
                )
            ],
        )
        conn.executemany(
            "INSERT INTO group_members "
            "(group_id, player_id, tier_at_start, is_human, joined_at) "
            "VALUES (?, ?, 'Bronze', ?, ?)",
            [
                (1, "local-old", 1, NOW),
                (1, "waka-old", 0, NOW),
            ],
        )
        conn.executemany(
            "INSERT INTO weekly_scores "
            "(week_start, player_id, group_id, seconds, xp) "
            "VALUES (?, ?, 1, ?, ?)",
            [
                (WEEK, "local-old", 600, 100),
                (WEEK, "waka-old", 1200, 200),
            ],
        )
        conn.execute(
            "INSERT INTO diamond_balance (player_id, balance, updated_at) "
            "VALUES ('local-old', 777, ?)",
            (NOW,),
        )
        conn.commit()
    finally:
        conn.close()


def _snapshot(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        players = [
            dict(row)
            for row in conn.execute("SELECT * FROM players ORDER BY id")
        ]
        mappings = [
            dict(row)
            for row in conn.execute(
                "SELECT channel_id, player_ref, player_id, profile_json "
                "FROM channel_players ORDER BY channel_id, player_ref"
            )
        ]
        memberships = [
            tuple(row)
            for row in conn.execute(
                "SELECT group_id, player_id, tier_at_start, is_human "
                "FROM group_members ORDER BY player_id"
            )
        ]
        scores = [
            tuple(row)
            for row in conn.execute(
                "SELECT week_start, player_id, seconds, xp "
                "FROM weekly_scores ORDER BY player_id"
            )
        ]
        wallet = conn.execute(
            "SELECT balance FROM diamond_balance WHERE player_id = 'local-old'"
        ).fetchone()[0]
    return {
        "players": players,
        "mappings": mappings,
        "memberships": memberships,
        "scores": scores,
        "wallet": int(wallet),
    }


def test_old_identity_schema_is_rebuilt_with_data_preserved(tmp_path: Path) -> None:
    path = tmp_path / "league.db"
    _make_old_database(path)
    before = _snapshot(path)

    store = GameStore(path, epoch_reason="migration")
    after = _snapshot(path)

    with store._reader() as conn:
        player_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(players)")
        }
        channel_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(channel_players)")
        }
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_channel_players_player'"
        ).fetchone()

    assert "kind" not in player_columns
    assert "controller" not in player_columns
    assert "kind" not in channel_columns
    assert index is not None

    assert [row["id"] for row in after["players"]] == ["local-old", "waka-old"]
    assert after["scores"] == before["scores"]
    assert after["mappings"] == before["mappings"]
    assert after["wallet"] == before["wallet"] == 777
    assert after["memberships"] == [
        (1, "local-old", "Bronze", 1),
        (1, "waka-old", "Bronze", 1),
    ]
    waka = next(row for row in after["players"] if row["id"] == "waka-old")
    assert waka["source_kind"] == "wakatime_public_leaderboard"
    assert waka["source_key_hash"] == "source-hash-old"

    backups = list(tmp_path.glob("league.db.backup-player-identity-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        old_columns = {
            row[1] for row in backup.execute("PRAGMA table_info(players)")
        }
        old_count = backup.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    assert {"kind", "controller"} <= old_columns
    assert old_count == 2

    # Re-opening a migrated database is a no-op and creates no second backup.
    GameStore(path, epoch_reason="migration")
    assert len(list(tmp_path.glob("league.db.backup-player-identity-*"))) == 1
    assert _snapshot(path) == after
