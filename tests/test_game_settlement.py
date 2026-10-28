from __future__ import annotations

import pytest

from ghost_league.game.rules import GameError, group_quota
from ghost_league.game.store import GameStore


def build_week(
    store: GameStore,
    week: str,
    *,
    tier: str,
    seconds: dict[str, int],
    at: str,
) -> None:
    player_ids = list(seconds)
    for player_id in player_ids:
        store.create_player(
            player_id,
            kind="human" if player_ids.index(player_id) == 0 else "ai",
            joined_week="2026-10-05",
            now="2026-10-05T00:00:00+08:00",
        )
    group = store.create_group(
        week,
        tier=tier,
        player_ids=player_ids,
        now=f"{week}T00:00:00+08:00",
    )
    assert group["member_count"] == 15
    for player_id, value in seconds.items():
        store.ingest_activity(
            player_id,
            event_id=f"{week}:{player_id}",
            seconds=value,
            occurred_at=f"{week}T12:00:00+08:00",
            source="local_increment",
            now=f"{week}T12:00:00+08:00",
        )


def base_scores() -> dict[str, int]:
    return {f"p{index:02d}": 15000 - index * 500 for index in range(1, 16)}


def test_bronze_ranking_promotions_and_no_demotion(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    week = "2026-10-19"
    scores = base_scores()
    scores["p08"] = scores["p07"]  # tie -> player_id ascending
    build_week(store, week, tier="Bronze", seconds=scores, at=week)

    with pytest.raises(GameError):
        store.settle_week(week, now="2026-10-25T23:59:00+08:00")

    result = store.settle_week(week, now="2026-10-26T00:05:00+08:00")
    assert result["already_settled"] is False
    rows = result["results"]
    quota = group_quota(15)
    assert quota == 3
    assert [row["rank"] for row in rows] == list(range(1, 16))
    assert [row["player_id"] for row in rows[:quota]] == ["p01", "p02", "p03"]
    assert all(row["promoted"] for row in rows[:quota])
    assert not any(row["promoted"] for row in rows[quota:])
    assert not any(row["demoted"] for row in rows)
    ranks = {row["player_id"]: row["rank"] for row in rows}
    assert ranks["p07"] < ranks["p08"]

    history = store.history("p01")
    assert len(history) == 1
    assert history[0]["rank"] == 1
    assert history[0]["promoted"] is True


def test_rerun_is_idempotent_and_does_not_recalculate(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    week = "2026-10-19"
    build_week(store, week, tier="Bronze", seconds=base_scores(), at=week)
    first = store.settle_week(week, now="2026-10-26T00:05:00+08:00")
    second = store.settle_week(week, now="2026-11-02T00:05:00+08:00")
    assert second["already_settled"] is True
    assert second["results"] == first["results"]
    with store.transaction() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM weekly_results WHERE week_start = ?",
            (week,),
        ).fetchone()["n"]
    assert count == 15


def test_silver_demotes_bottom_three_and_diamond_never_promotes(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    players = [f"p{index:02d}" for index in range(1, 16)]
    for player_id in players:
        store.create_player(
            player_id,
            kind="human" if player_id == "p01" else "ai",
            joined_week="2026-10-05",
            now="2026-10-05T00:00:00+08:00",
        )

    silver = "2026-10-19"
    store.create_group(
        silver, tier="Silver", player_ids=players, now=f"{silver}T00:00:00+08:00"
    )
    for index, player_id in enumerate(players):
        store.ingest_activity(
            player_id,
            event_id=f"s:{player_id}",
            seconds=12000 - index * 100,
            occurred_at=f"{silver}T12:00:00+08:00",
            source="local_increment",
            now=f"{silver}T12:00:00+08:00",
        )
    silver_result = store.settle_week(silver, now="2026-10-26T00:05:00+08:00")
    quota = group_quota(15)
    assert [row["player_id"] for row in silver_result["results"][:quota]] == [
        "p01",
        "p02",
        "p03",
    ]
    assert all(row["promoted"] for row in silver_result["results"][:quota])
    assert all(row["demoted"] for row in silver_result["results"][-quota:])

    diamond = "2026-10-26"
    store.create_group(
        diamond, tier="Diamond", player_ids=players, now=f"{diamond}T00:00:00+08:00"
    )
    for index, player_id in enumerate(players):
        store.ingest_activity(
            player_id,
            event_id=f"d:{player_id}",
            seconds=12000 - index * 100,
            occurred_at=f"{diamond}T12:00:00+08:00",
            source="local_increment",
            now=f"{diamond}T12:00:00+08:00",
        )
    diamond_result = store.settle_week(diamond, now="2026-11-02T00:05:00+08:00")
    assert diamond_result["results"][0]["rank"] == 1
    assert diamond_result["results"][0]["promoted"] is False
    assert diamond_result["results"][-1]["demoted"] is True


def test_empty_history_is_not_fabricated(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    assert store.history("missing") == []
    empty = store.settle_week("2026-01-05", now="2026-10-28T00:00:00+08:00")
    assert empty["results"] == []
    assert store.history("missing") == []
    with store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM weekly_results WHERE week_start = '2026-01-05'"
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM weeks WHERE week_start = '2026-01-05'"
            ).fetchone()["n"]
            == 0
        )
