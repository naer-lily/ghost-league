from __future__ import annotations

from pathlib import Path

from ghost_league.game.jobs import run_weekly_settlement
from ghost_league.game.rules import group_quota
from ghost_league.game.store import GameStore

WEEK = "2026-10-19"
NEXT_MONDAY = "2026-10-26T00:05:00+08:00"


def seeded_group(tmp_path: Path) -> GameStore:
    """Create a current-week Bronze group with fifteen active players."""

    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    players = [f"p{index:02d}" for index in range(1, 16)]
    for player_id in players:
        store.create_player(
            player_id,
            kind="human",
            joined_week=WEEK,
            now=f"{WEEK}T00:00:00+08:00",
        )
    store.create_group(
        WEEK,
        tier="Bronze",
        player_ids=players,
        now=f"{WEEK}T00:00:00+08:00",
    )
    for index, player_id in enumerate(players):
        store.ingest_activity(
            player_id,
            event_id=f"event-{player_id}",
            seconds=9_000 - index * 100,
            occurred_at="2026-10-24T12:00:00+08:00",
            source="local_increment",
            now="2026-10-24T12:00:00+08:00",
        )
    return store


def test_monday_settles_previous_week(tmp_path) -> None:
    store = seeded_group(tmp_path)

    settled = run_weekly_settlement(store.path, at=NEXT_MONDAY)
    assert settled["status"] == "settled"
    assert settled["already_settled"] is False
    assert settled["week_start"] == WEEK
    assert [row["rank"] for row in settled["results"]] == list(range(1, 16))
    assert all(row["promoted"] for row in settled["results"][:3])
    assert not any(row["demoted"] for row in settled["results"])
    assert store.get_week(WEEK)["status"] == "settled"
    # Only the previous week was touched; no future week was pre-created.
    assert store.get_week("2026-10-26") is None


def test_settle_before_monday_skips_and_leaves_current_week_active(tmp_path) -> None:
    store = seeded_group(tmp_path)

    result = run_weekly_settlement(store.path, at="2026-10-25T23:30:00+08:00")
    assert result["status"] == "skipped"
    assert result["skipped"] is True
    assert result["week_start"] == "2026-10-12"
    assert result["results"] == []
    assert store.get_week(WEEK)["status"] == "active"
    assert store.history("p01") == []


def test_repeated_settle_returns_already_settled(tmp_path) -> None:
    store = seeded_group(tmp_path)

    first = run_weekly_settlement(store.path, at=NEXT_MONDAY)
    second = run_weekly_settlement(store.path, at=NEXT_MONDAY)
    assert first["status"] == "settled"
    assert second["status"] == "already_settled"
    assert second["already_settled"] is True
    assert second["results"] == first["results"]


def test_settle_without_a_group_is_skipped(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    store.ensure_week(WEEK)

    result = run_weekly_settlement(store.path, at=NEXT_MONDAY)
    assert result["status"] == "skipped"
    assert result["reason"] == "no_group"
    assert result["week_start"] == WEEK
    assert result["results"] == []
    assert store.get_week(WEEK)["status"] == "active"
    assert store.get_week("2026-10-26") is None


def test_small_group_ranks_and_movements(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    players = [f"p{index:02d}" for index in range(1, 6)]
    for player_id in players:
        store.create_player(
            player_id,
            kind="human",
            joined_week=WEEK,
            now=f"{WEEK}T00:00:00+08:00",
        )
    store.create_group(
        WEEK,
        tier="Silver",
        player_ids=players,
        now=f"{WEEK}T00:00:00+08:00",
    )
    for index, player_id in enumerate(players):
        store.ingest_activity(
            player_id,
            event_id=f"event-{player_id}",
            seconds=9_000 - index * 1_000,
            occurred_at="2026-10-24T12:00:00+08:00",
            source="local_increment",
            now="2026-10-24T12:00:00+08:00",
        )

    result = run_weekly_settlement(store.path, at=NEXT_MONDAY)
    rows = result["results"]
    assert result["status"] == "settled"
    assert [(row["player_id"], row["rank"]) for row in rows] == [
        ("p01", 1),
        ("p02", 2),
        ("p03", 3),
        ("p04", 4),
        ("p05", 5),
    ]
    quota = group_quota(5)
    assert quota == 1
    assert [row["promoted"] for row in rows] == [True, False, False, False, False]
    assert [row["demoted"] for row in rows] == [False, False, False, False, True]
    assert store.tier_for_player("p01", "2026-10-26") == "Gold"
    assert store.tier_for_player("p03", "2026-10-26") == "Silver"
    assert store.tier_for_player("p05", "2026-10-26") == "Bronze"
    assert store.get_week("2026-10-26") is None
