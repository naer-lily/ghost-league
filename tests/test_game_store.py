from __future__ import annotations

import sqlite3

import pytest

from ghost_league.game.store import SOURCE_WAKA, GameStore


def make_store(tmp_path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def test_schema_meta_and_epoch(tmp_path) -> None:
    store = make_store(tmp_path)
    with store.transaction() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "meta",
        "epochs",
        "players",
        "sources",
        "opponent_week_plan",
        "activity_events",
        "weeks",
        "groups",
        "group_members",
        "weekly_scores",
        "weekly_results",
        "checkins",
        "ember_ledger",
        "ember_balance",
        "streaks",
        "milestones",
        "catalog_titles",
        "catalog_items",
        "player_titles",
        "player_items",
        "loadouts",
        "player_stars",
        "shop_cap_upgrades",
        "bets",
        "group_bets",
        "task_definitions",
        "task_instances",
        "job_runs",
        "game_config",
        "diamond_boosts",
    } <= tables
    meta = store.meta_snapshot()
    assert meta["schema_version"] == "14"
    assert meta["algorithm_version"] == "phase1-v1"
    assert meta["epoch_id"]
    assert store.active_epoch()["status"] == "active"
    assert store.integrity_check() == "ok"


def test_fresh_database_has_no_player_identity_columns(tmp_path) -> None:
    store = make_store(tmp_path)
    with store._reader() as conn:
        player_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(players)")
        }
        channel_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(channel_players)")
        }
    assert "kind" not in player_columns
    assert "controller" not in player_columns
    assert "kind" not in channel_columns


def test_transaction_rolls_back_on_error(tmp_path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(RuntimeError), store.transaction() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('rollback_probe', 'yes')"
        )
        raise RuntimeError("boom")
    assert store.get_meta("rollback_probe") is None

    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('commit_probe', 'yes')"
        )
    assert store.get_meta("commit_probe") == "yes"


def test_activity_event_is_idempotent_and_updates_one_score(tmp_path) -> None:
    store = make_store(tmp_path)
    week = "2026-10-26"
    store.create_player(
        "human-1",
        joined_week=week,
        now="2026-10-26T00:00:00+08:00",
    )
    first = store.ingest_activity(
        "human-1",
        event_id="event-1",
        seconds=600,
        occurred_at="2026-10-26T10:00:00+08:00",
        source="local_increment",
        now="2026-10-26T10:00:00+08:00",
    )
    replay = store.ingest_activity(
        "human-1",
        event_id="event-1",
        seconds=600,
        occurred_at="2026-10-26T10:00:00+08:00",
        source="local_increment",
        now="2026-10-26T10:00:01+08:00",
    )
    assert first["accepted"] is True
    assert first["checkin"]["created"] is True
    assert replay["duplicate"] is True
    score = store.get_week_score("human-1", week)
    assert score["seconds"] == 600
    assert score["xp"] == 100
    assert store.get_checkin("human-1", "2026-10-26")["source"] == "verified"
    assert len(store.checkins_between("human-1", week, "2026-11-02")) == 1


def test_channel_seconds_between_aggregates_local_days(tmp_path) -> None:
    store = make_store(tmp_path)
    week = "2026-10-26"
    store.create_player(
        "ai-1",
        joined_week=week,
        now="2026-10-26T00:00:00+08:00",
    )
    with store.transaction() as conn:
        for event_id, seconds, occurred_at in (
            ("day-1-a", 60, "2026-10-26T01:00:00+08:00"),
            ("day-1-b", 90, "2026-10-26T23:59:59+08:00"),
            ("day-2", 120, "2026-10-27T00:00:00+08:00"),
            ("outside", 999, "2026-10-25T23:59:59+08:00"),
        ):
            conn.execute(
                "INSERT INTO channel_events "
                "(event_id, channel_id, player_ref, player_id, seconds, "
                "occurred_at, week_start, created_at) "
                "VALUES (?, 'test-channel', 'ai-1', 'ai-1', ?, ?, ?, ?)",
                (
                    event_id,
                    seconds,
                    occurred_at,
                    week,
                    occurred_at,
                ),
            )
    assert store.channel_seconds_between("ai-1", week, "2026-10-28") == [
        {"date": "2026-10-26", "seconds": 150},
        {"date": "2026-10-27", "seconds": 120},
    ]
    assert store.channel_seconds_between("ai-1", week, week) == []
    assert store.channel_seconds_on_day("ai-1", "2026-10-26") == 150
    assert store.channel_seconds_on_day("ai-1", "2026-10-27") == 120
    assert store.channel_seconds_on_day("ai-1", "2026-10-28") == 0


def test_source_upsert_is_unique_and_players_cannot_duplicate(tmp_path) -> None:
    store = make_store(tmp_path)
    week = "2026-10-26"
    first_id = store.upsert_source(
        "hash-a",
        anchor_seconds=12000,
        anchor_week=week,
        fetched_at="2026-10-26T00:00:00+08:00",
    )
    second_id = store.upsert_source(
        "hash-a",
        anchor_seconds=24000,
        anchor_week=week,
        fetched_at="2026-10-26T01:00:00+08:00",
    )
    assert first_id == second_id
    source = store.get_source("hash-a")
    assert source["anchor_seconds"] == 24000
    assert source["effective_seconds"] == 24000
    assert source["p75_seconds"] == 0
    assert source["normalization_version"] == "legacy"
    store.upsert_source(
        "hash-a",
        anchor_seconds=30000,
        effective_seconds=18000,
        p75_seconds=12000,
        normalization_version="p75-soft-0.2-v1",
        anchor_week=week,
        fetched_at="2026-10-26T02:00:00+08:00",
    )
    source = store.get_source("hash-a")
    assert source["anchor_seconds"] == 30000
    assert source["effective_seconds"] == 18000
    assert source["p75_seconds"] == 12000
    assert source["normalization_version"] == "p75-soft-0.2-v1"
    store.create_player(
        "ai-1",
        source_kind="wakatime_public_leaderboard",
        source_key_hash="hash-a",
        joined_week=week,
        now="2026-10-26T00:00:00+08:00",
    )
    store.create_player(
        "ai-1",
        display_name="ignored duplicate",
        joined_week=week,
        now="2026-10-26T00:00:00+08:00",
    )
    assert len(store.list_players(source_kind=SOURCE_WAKA)) == 1


def test_database_constraints_reject_negative_balance(tmp_path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(sqlite3.IntegrityError), store.transaction() as conn:
        conn.execute(
            "INSERT INTO ember_balance "
            "(player_id, balance, week_earned, week_start, updated_at) "
            "VALUES ('p', -1, 0, '2026-10-26', 'x')"
        )


def test_humans_are_placed_first_and_groups_stay_balanced(tmp_path) -> None:
    store = make_store(tmp_path)
    week = "2026-10-26"
    at = f"{week}T00:00:00+08:00"
    ai_ids = []
    for index in range(14):
        player_id = f"ai-{index:02d}"
        ai_ids.append(player_id)
        store.create_player(
            player_id,
            source_kind=SOURCE_WAKA,
            joined_week=week,
            now=at,
        )
        store.upsert_opponent_week_plan(
            player_id,
            week,
            anchor_seconds=12_000,
            target_seconds=10_000,
            percentile=0.5,
            seed=player_id,
            algorithm_version="test",
            created_at=at,
        )
    for name in ("human-a", "human-b"):
        store.create_player(
            name,
            joined_week=week,
            now=at,
        )
    groups = store.ensure_current_group(week, now=f"{week}T01:00:00+08:00")
    assert len(groups) == 2
    assert sorted(group["member_count"] for group in groups) == [8, 8]
    human_group = next(
        group
        for group in groups
        if any(
            member["player_id"] in {"human-a", "human-b"}
            for member in group["members"]
        )
    )
    assert human_group["member_count"] == 8
    assert {
        member["player_id"]
        for member in human_group["members"]
        if member["player_id"].startswith("human-")
    } == {"human-a", "human-b"}
    # The retained UI column marks every ordinary contestant as human=1.
    assert all(member["is_human"] == 1 for group in groups for member in group["members"])

    # A later human joins the same human-first group; the balanced seat
    # allocation grows from 8/8 to 9/8 without creating a tail group.
    store.create_player(
        "human-c",
        joined_week=week,
        now=f"{week}T02:00:00+08:00",
    )
    later = store.ensure_group_for_player(
        "human-c", week, now=f"{week}T02:00:00+08:00"
    )
    groups = store.ensure_all_groups(week, now=f"{week}T02:00:00+08:00")
    assert len(groups) == 2
    assert sorted(group["member_count"] for group in groups) == [8, 9]
    assert later["id"] == human_group["id"]
    assert len(store.group_members(human_group["id"])) == 9
    members = [
        member
        for group in groups
        for member in store.group_members(group["id"])
    ]
    assert len(members) == 17
    assert {member["player_id"] for member in members} == set(
        ["human-a", "human-b", "human-c", *ai_ids]
    )


def test_old_sources_table_is_migrated_without_losing_raw_values(tmp_path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE sources ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source_key_hash TEXT NOT NULL UNIQUE, "
            "anchor_seconds INTEGER NOT NULL CHECK (anchor_seconds >= 0), "
            "anchor_week TEXT NOT NULL, "
            "fetched_at TEXT NOT NULL, "
            "stale_weeks INTEGER NOT NULL DEFAULT 0 CHECK (stale_weeks >= 0))"
        )
        conn.execute(
            "INSERT INTO sources (source_key_hash, anchor_seconds, anchor_week, "
            "fetched_at) VALUES ('old-hash', 36000, '2026-10-26', "
            "'2026-10-26T00:00:00+08:00')"
        )
        conn.commit()
    finally:
        conn.close()

    store = GameStore(path, epoch_reason="test")
    source = store.get_source("old-hash")
    assert source is not None
    assert source["anchor_seconds"] == 36000
    assert source["effective_seconds"] == 36000
    assert source["p75_seconds"] == 0
    assert source["normalization_version"] == "legacy"

    # Re-opening an already migrated database must not overwrite later values.
    store.upsert_source(
        "old-hash",
        anchor_seconds=40000,
        effective_seconds=20000,
        p75_seconds=15000,
        normalization_version="p75-soft-0.2-v1",
        anchor_week="2026-10-26",
        fetched_at="2026-10-26T01:00:00+08:00",
    )
    GameStore(path, epoch_reason="test")
    source = store.get_source("old-hash")
    assert source["effective_seconds"] == 20000
    assert source["normalization_version"] == "p75-soft-0.2-v1"


def test_task_order_migration_backfills_definitions_and_instances(tmp_path) -> None:
    path = tmp_path / "league.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE task_definitions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 3),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE task_instances (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                definition_id TEXT,
                source TEXT NOT NULL
                    CHECK(source IN ('daily_manual', 'repair', 'weekend')),
                system_key TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
                chest_tier INTEGER NOT NULL CHECK(chest_tier BETWEEN 1 AND 5),
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                completion_mode TEXT NOT NULL
                    CHECK(completion_mode IN ('manual', 'dsl')),
                condition_json TEXT,
                status TEXT NOT NULL
                    CHECK(status IN ('active', 'completed', 'expired')),
                completed_at TEXT,
                proof_path TEXT,
                proof_mime TEXT,
                chest_status TEXT NOT NULL DEFAULT 'none'
                    CHECK(chest_status IN ('none', 'available', 'claimed', 'forfeited')),
                claimed_at TEXT,
                chest_amount INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO task_definitions VALUES
                ('td_b', 'u', 'B', '', 1, 1,
                 '2026-11-01T00:00:00+08:00', '2026-11-01T00:00:00+08:00'),
                ('td_a', 'u', 'A', '', 1, 1,
                 '2026-11-02T00:00:00+08:00', '2026-11-02T00:00:00+08:00');
            INSERT INTO task_instances VALUES
                ('ti_a', 'u', 'td_a', 'daily_manual',
                 'daily:td_a:2026-11-04', 'A', '', 1, 1,
                 '2026-11-04T00:00:00+08:00', '2026-11-05T00:00:00+08:00',
                 'manual', NULL, 'active', NULL, NULL, NULL, 'none', NULL, NULL,
                 '2026-11-04T01:00:00+08:00', '2026-11-04T01:00:00+08:00'),
                ('ti_done', 'u', 'td_b', 'daily_manual',
                 'daily:td_b:2026-11-03', 'B', '', 1, 1,
                 '2026-11-03T00:00:00+08:00', '2026-11-04T00:00:00+08:00',
                 'manual', NULL, 'completed', NULL, NULL, NULL, 'none', NULL,
                 NULL, '2026-11-03T01:00:00+08:00', '2026-11-03T01:00:00+08:00');
            """
        )

    store = GameStore(path, epoch_reason="test")
    assert [
        (row["title"], row["sort_order"])
        for row in store.list_task_definitions("u")
    ] == [("B", 10), ("A", 20)]
    with store.transaction() as conn:
        rows = conn.execute(
            "SELECT id, sort_order, chest_tier, chest_pool, "
            "chest_reward_type, chest_boost_minutes, chest_star_id "
            "FROM task_instances ORDER BY id"
        ).fetchall()
    assert [
        (
            row["id"],
            row["sort_order"],
            row["chest_tier"],
            row["chest_pool"],
            row["chest_reward_type"],
            row["chest_boost_minutes"],
            row["chest_star_id"],
        )
        for row in rows
    ] == [
        ("ti_a", 20, 1, "daily_1", "diamonds", None, None),
        ("ti_done", 10, 1, "daily_1", "diamonds", None, None),
    ]
    with sqlite3.connect(path) as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'task_instances'"
        ).fetchone()[0]
        assert "'checkin'" in sql
        assert "'weekly_chain'" in sql
        # The rebuilt CHECK accepts the new sources and keeps old rows valid.
        conn.execute(
            "INSERT INTO task_instances "
            "(id, user_id, definition_id, source, system_key, title, "
            "description, difficulty, chest_tier, starts_at, ends_at, "
            "completion_mode, condition_json, status, completed_at, "
            "proof_path, proof_mime, chest_status, claimed_at, chest_amount, "
            "chest_reward_type, chest_boost_minutes, sort_order, created_at, "
            "updated_at) "
            "VALUES ('ti_checkin', 'u', NULL, 'checkin', "
            "'checkin:2026-11-04', '每日打卡', '', 1, 1, "
            "'2026-11-04T00:00:00+08:00', '2026-11-05T00:00:00+08:00', "
            "'dsl', NULL, 'active', NULL, NULL, NULL, 'none', NULL, NULL, "
            "'diamonds', NULL, 0, '2026-11-04T01:00:00+08:00', "
            "'2026-11-04T01:00:00+08:00')"
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM task_instances WHERE source = 'checkin'"
        ).fetchone()[0] == 1
        conn.execute(
            "INSERT INTO task_instances "
            "(id, user_id, definition_id, source, system_key, title, "
            "description, difficulty, chest_tier, chest_pool, starts_at, "
            "ends_at, completion_mode, condition_json, status, completed_at, "
            "proof_path, proof_mime, chest_status, claimed_at, chest_amount, "
            "chest_reward_type, chest_boost_minutes, sort_order, created_at, "
            "updated_at) "
            "VALUES ('ti_weekly', 'u', NULL, 'weekly_chain', "
            "'weekly_chain:2026-11-02:1', '本周 1000 XP', '', 1, 1, "
            "'weekly_chain_1', '2026-11-02T00:00:00+08:00', "
            "'2026-11-09T00:00:00+08:00', 'dsl', NULL, 'active', NULL, "
            "NULL, NULL, 'none', NULL, NULL, 'diamonds', NULL, 10, "
            "'2026-11-04T01:00:00+08:00', '2026-11-04T01:00:00+08:00')"
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM task_instances "
            "WHERE source = 'weekly_chain'"
        ).fetchone()[0] == 1
