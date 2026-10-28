from __future__ import annotations

import sqlite3

import pytest

from ghost_league.game.store import GameStore


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
    } <= tables
    meta = store.meta_snapshot()
    assert meta["schema_version"] == "3"
    assert meta["algorithm_version"] == "phase1-v1"
    assert meta["epoch_id"]
    assert store.active_epoch()["status"] == "active"
    assert store.integrity_check() == "ok"


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
        kind="human",
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
        kind="ai",
        source_kind="wakatime_public_leaderboard",
        source_key_hash="hash-a",
        joined_week=week,
        now="2026-10-26T00:00:00+08:00",
    )
    store.create_player(
        "ai-1",
        kind="ai",
        display_name="ignored duplicate",
        joined_week=week,
        now="2026-10-26T00:00:00+08:00",
    )
    assert len(store.list_players(kind="ai")) == 1


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
            kind="ai",
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
            kind="human",
            joined_week=week,
            now=at,
        )
    groups = store.ensure_current_group(week, now=f"{week}T01:00:00+08:00")
    assert len(groups) == 2
    assert sorted(group["member_count"] for group in groups) == [8, 8]
    human_groups = [
        group
        for group in groups
        if any(member["is_human"] for member in group["members"])
    ]
    assert len(human_groups) == 1
    human_group = human_groups[0]
    assert human_group["member_count"] == 8
    assert sum(
        1 for member in human_group["members"] if member["is_human"]
    ) == 2

    # A later human joins the same human-first group; the balanced seat
    # allocation grows from 8/8 to 9/8 without creating a tail group.
    store.create_player(
        "human-c",
        kind="human",
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
