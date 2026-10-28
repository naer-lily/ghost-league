from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from ghost_league.game.roster import (
    ensure_all_groups,
    source_key_hash,
    sync_week_roster,
)
from ghost_league.game.store import GameStore

WEEK_1 = "2026-10-26"
WEEK_2 = "2026-11-02"
WEEK_3 = "2026-11-09"
AT_1 = f"{WEEK_1}T00:00:00+08:00"
AT_2 = f"{WEEK_2}T00:00:00+08:00"
AT_3 = f"{WEEK_3}T00:00:00+08:00"


def make_rows(count: int, *, start: int = 0) -> list[dict]:
    return [
        {
            "id": f"anchor-{index:04d}",
            "seconds": 500_000 - (index % 400) * 1_000,
            "rank": index + 1,
        }
        for index in range(start, start + count)
    ]


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def sync(
    store: GameStore,
    week: str,
    rows: list[dict],
    *,
    at: str,
) -> dict:
    return sync_week_roster(store, week, rows, at=at)


def add_human(store: GameStore, player_id: str, week: str, at: str) -> None:
    store.ensure_human_player(
        player_id,
        display_name=player_id,
        joined_week=week,
        now=at,
    )


def player_id_for(store: GameStore, source_id: str) -> str:
    player = store.get_player_by_source_key_hash(source_key_hash(source_id))
    assert player is not None
    return str(player["id"])


def group_sizes(groups: list[dict]) -> list[int]:
    return sorted((int(group["member_count"]) for group in groups), reverse=True)


def flat_members(groups: list[dict]) -> list[str]:
    return [
        str(member["player_id"])
        for group in groups
        for member in group["members"]
    ]


def test_1000_row_snapshot_creates_every_ai_idempotently(tmp_path) -> None:
    store = make_store(tmp_path)
    rows = make_rows(1000)

    first = sync(store, WEEK_1, rows, at=AT_1)
    assert first["source_count"] == 1000
    assert first["count"] == 1000
    assert first["created"] == 1000
    assert first["existing"] == 0

    players = store.list_players(kind="ai")
    assert len(players) == 1000
    assert len({player["source_key_hash"] for player in players}) == 1000
    assert len(store.list_opponent_week_plans(WEEK_1)) == 1000

    original_ids = {str(player["id"]) for player in players}
    replay = sync(store, WEEK_1, rows, at=AT_1)
    assert replay["created"] == 0
    assert replay["existing"] == 1000
    assert replay["count"] == 1000
    assert {str(player["id"]) for player in store.list_players(kind="ai")} == original_ids
    assert len(store.list_opponent_week_plans(WEEK_1)) == 1000


def test_one_human_gets_a_full_human_group_and_all_ai_are_conserved(tmp_path) -> None:
    store = make_store(tmp_path)
    rows = make_rows(1000)
    sync(store, WEEK_1, rows, at=AT_1)
    add_human(store, "human-1", WEEK_1, AT_1)

    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    human_group = store.group_for_player("human-1", WEEK_1)
    assert human_group is not None
    members = store.group_members(int(human_group["id"]))
    assert len(members) == 15
    assert sum(1 for member in members if member["kind"] == "human") == 1
    assert sum(1 for member in members if member["kind"] == "ai") == 14

    sizes = group_sizes(groups)
    assert len(groups) == 67
    assert sizes == [15] * 63 + [14] * 4
    ai_members = [
        member
        for group in groups
        for member in group["members"]
        if member["kind"] == "ai"
    ]
    assert len(ai_members) == 1000
    assert len(flat_members(groups)) == 1001
    assert len(set(flat_members(groups))) == 1001
    assert all(size <= 15 for size in sizes)


def test_37_players_are_split_13_12_12_without_a_tail_group(tmp_path) -> None:
    store = make_store(tmp_path)
    rows = make_rows(37)
    sync(store, WEEK_1, rows, at=AT_1)

    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(groups) == 3
    assert group_sizes(groups) == [13, 12, 12]
    assert len(flat_members(groups)) == 37
    assert len(set(flat_members(groups))) == 37


def test_second_week_disappeared_and_new_ai_are_reconciled(tmp_path) -> None:
    store = make_store(tmp_path)
    rows = make_rows(40)
    sync(store, WEEK_1, rows, at=AT_1)
    add_human(store, "human-1", WEEK_1, AT_1)
    ensure_all_groups(store, WEEK_1, now=AT_1)

    removed = rows[30:]
    added = make_rows(5, start=1000)
    current = rows[:30] + added
    result = sync(store, WEEK_2, current, at=AT_2)
    add_human(store, "human-1", WEEK_2, AT_2)
    groups = ensure_all_groups(store, WEEK_2, now=AT_2)

    assert result["source_count"] == 35
    assert result["disappeared"] == 10
    assert len(store.list_players(kind="ai")) == 45
    assert len(store.list_opponent_week_plans(WEEK_1)) == 40
    assert len(store.list_opponent_week_plans(WEEK_2)) == 35

    active_ids = {player_id_for(store, row["id"]) for row in current}
    removed_ids = {player_id_for(store, row["id"]) for row in removed}
    added_ids = {player_id_for(store, row["id"]) for row in added}

    assert removed_ids.isdisjoint(active_ids)
    assert added_ids <= active_ids
    assert not (removed_ids & set(flat_members(groups)))
    assert set(flat_members(groups)) == active_ids | {"human-1"}

    for player_id in removed_ids:
        assert store.get_opponent_week_plan(player_id, WEEK_2) is None
        assert store.group_for_player(player_id, WEEK_2) is None
        assert store.get_opponent_week_plan(player_id, WEEK_1) is not None
        assert store.get_player(player_id)["last_seen_week"] == WEEK_1

    for player_id in added_ids:
        player = store.get_player(player_id)
        assert player["joined_week"] == WEEK_2
        assert player["last_seen_week"] == WEEK_2
        assert store.tier_for_player(player_id, WEEK_2) == "Bronze"
        assert store.get_opponent_week_plan(player_id, WEEK_2) is not None
        assert player_id in set(flat_members(groups))

    replay = sync(store, WEEK_2, current, at=AT_2)
    assert replay["created"] == 0
    assert replay["existing"] == 35
    assert len(store.list_players(kind="ai")) == 45
    assert len(store.list_opponent_week_plans(WEEK_2)) == 35


def test_zero_second_ai_still_gets_a_plan_and_a_group(tmp_path) -> None:
    store = make_store(tmp_path)
    rows = [
        {"id": "zero-anchor", "seconds": 0, "rank": 1},
        {"id": "anchor-a", "seconds": 10_000, "rank": 2},
        {"id": "anchor-b", "seconds": 20_000, "rank": 3},
    ]
    sync(store, WEEK_1, rows, at=AT_1)
    add_human(store, "human-1", WEEK_1, AT_1)

    zero_id = player_id_for(store, "zero-anchor")
    plan = store.get_opponent_week_plan(zero_id, WEEK_1)
    assert plan is not None
    assert plan["target_seconds"] == 0
    assert plan["target_xp"] == 0

    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert zero_id in set(flat_members(groups))
    assert len(flat_members(groups)) == 4


def test_ai_returning_after_a_missing_week_reuses_player_id_and_history(tmp_path) -> None:
    store = make_store(tmp_path)
    rows = make_rows(3)
    sync(store, WEEK_1, rows, at=AT_1)
    original_id = player_id_for(store, "anchor-0001")

    sync(store, WEEK_2, [rows[0], rows[2]], at=AT_2)
    assert store.get_opponent_week_plan(original_id, WEEK_2) is None
    assert store.get_player(original_id)["last_seen_week"] == WEEK_1
    assert store.get_opponent_week_plan(original_id, WEEK_1) is not None

    result = sync(store, WEEK_3, rows, at=AT_3)
    assert result["created"] == 0
    assert player_id_for(store, "anchor-0001") == original_id
    player = store.get_player(original_id)
    assert player["joined_week"] == WEEK_1
    assert player["last_seen_week"] == WEEK_3
    assert store.get_opponent_week_plan(original_id, WEEK_3) is not None
    assert len(store.list_players(kind="ai")) == 3


def test_multiple_humans_stay_together_and_no_player_crosses_groups(tmp_path) -> None:
    store = make_store(tmp_path)
    rows = make_rows(20)
    sync(store, WEEK_1, rows, at=AT_1)
    for index in range(3):
        add_human(store, f"human-{index}", WEEK_1, AT_1)

    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(groups) == 2
    assert group_sizes(groups) == [12, 11]
    human_groups = {
        int(group["id"])
        for group in groups
        for member in group["members"]
        if member["kind"] == "human"
    }
    assert len(human_groups) == 1
    human_group_id = next(iter(human_groups))
    human_members = [
        member
        for group in groups
        if int(group["id"]) == human_group_id
        for member in group["members"]
    ]
    assert sum(1 for member in human_members if member["kind"] == "human") == 3
    assert sum(1 for member in human_members if member["kind"] == "ai") == 9

    membership_counts: Counter[str] = Counter()
    with store.transaction() as conn:
        for row in conn.execute(
            "SELECT gm.player_id FROM group_members gm "
            "JOIN groups g ON g.id = gm.group_id WHERE g.week_start = ?",
            (WEEK_1,),
        ):
            membership_counts[str(row["player_id"])] += 1
    assert len(membership_counts) == 23
    assert all(count == 1 for count in membership_counts.values())


def test_old_league_db_without_last_seen_week_migrates_without_data_loss(tmp_path) -> None:
    path = tmp_path / "old-league.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE players ("
            "id TEXT PRIMARY KEY, "
            "kind TEXT NOT NULL, "
            "controller TEXT NOT NULL, "
            "source_kind TEXT NOT NULL, "
            "source_key_hash TEXT, "
            "display_name TEXT NOT NULL, "
            "joined_week TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "is_active INTEGER NOT NULL DEFAULT 1)"
        )
        conn.execute(
            "INSERT INTO players (id, kind, controller, source_kind, "
            "source_key_hash, display_name, joined_week, created_at, is_active) "
            "VALUES ('ai-old', 'ai', 'ai', 'wakatime_public_leaderboard', "
            "'old-hash', 'AI-OLD', '2026-10-19', "
            "'2026-10-19T00:00:00+08:00', 1)"
        )
        conn.execute(
            "CREATE TABLE opponent_week_plan ("
            "player_id TEXT NOT NULL, "
            "week_start TEXT NOT NULL, "
            "anchor_seconds INTEGER NOT NULL CHECK (anchor_seconds >= 0), "
            "target_seconds INTEGER NOT NULL CHECK (target_seconds >= 0), "
            "target_xp INTEGER NOT NULL CHECK (target_xp >= 0), "
            "percentile REAL NOT NULL, "
            "seed TEXT NOT NULL, "
            "algorithm_version TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "PRIMARY KEY (player_id, week_start))"
        )
        conn.execute(
            "INSERT INTO opponent_week_plan (player_id, week_start, "
            "anchor_seconds, target_seconds, target_xp, percentile, seed, "
            "algorithm_version, created_at) VALUES "
            "('ai-old', '2026-11-02', 12000, 10000, 1666, 0.5, 'ai-old', "
            "'legacy', '2026-11-02T00:00:00+08:00')"
        )
        conn.commit()
    finally:
        conn.close()

    store = GameStore(path, epoch_reason="migration")
    player = store.get_player("ai-old")
    assert player["display_name"] == "AI-OLD"
    assert player["source_key_hash"] == "old-hash"
    assert player["joined_week"] == "2026-10-19"
    assert player["last_seen_week"] == WEEK_2
    assert store.get_opponent_week_plan("ai-old", WEEK_2) is not None

    reopened = GameStore(path, epoch_reason="migration")
    assert reopened.get_player("ai-old")["last_seen_week"] == WEEK_2
    assert reopened.get_opponent_week_plan("ai-old", WEEK_2) is not None
