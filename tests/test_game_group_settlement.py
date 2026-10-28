from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ghost_league.api import GameService
from ghost_league.game.rules import group_movement, group_quota
from ghost_league.game.store import SOURCE_HUMAN, GameStore

CHANNEL = "group-settlement-channel"
CHANNEL_TOKEN = "group-settlement-token"
WEEK_1 = "2026-10-26"
WEEK_2 = "2026-11-02"
WEEK_3 = "2026-11-09"


def at(week: str, *, hour: int = 23) -> datetime:
    return datetime.fromisoformat(f"{week}T{hour:02d}:00:00+08:00")


def settle_at(week: str) -> datetime:
    next_week = datetime.fromisoformat(f"{week}T00:00:00+08:00") + timedelta(days=7)
    return next_week + timedelta(minutes=5)


def make_service(
    tmp_path: Path,
    clock: dict[str, datetime],
) -> GameService:
    api_dir = tmp_path / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    return GameService(
        game_db_path=tmp_path / "league.db",
        cache_path=tmp_path / "unused-cache.json",
        avatars_path=api_dir / "avatars.json",
        api_dir=api_dir,
        accounts_db=api_dir / "accounts.db",
        channel_token=CHANNEL_TOKEN,
        game_now_fn=lambda: clock["now"],
    )


def seed_group(
    store: GameStore,
    week: str,
    *,
    tier: str,
    prefix: str,
    scores: dict[str, int],
) -> dict:
    player_ids = list(scores)
    for index, player_id in enumerate(player_ids):
        store.create_player(
            player_id,
            kind="human" if index == 0 else "ai",
            joined_week="2026-10-05",
            now="2026-10-05T00:00:00+08:00",
        )
    group = store.create_group(
        week,
        tier=tier,
        player_ids=player_ids,
        now=f"{week}T00:00:00+08:00",
    )
    for player_id, seconds in scores.items():
        store.ingest_activity(
            player_id,
            event_id=f"{week}:{prefix}:{player_id}",
            seconds=seconds,
            occurred_at=f"{week}T12:00:00+08:00",
            source=SOURCE_HUMAN,
            now=f"{week}T12:00:00+08:00",
        )
    return group


def rows_by_group(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(int(row["group_id"]), []).append(row)
    for group_rows in grouped.values():
        group_rows.sort(key=lambda row: int(row["rank"]))
    return grouped


@pytest.mark.parametrize(
    ("size", "expected"),
    [(15, 3), (14, 3), (12, 2), (5, 1), (3, 1), (2, 1), (7, 1), (8, 2)],
)
def test_group_quota_is_round_half_up_with_a_minimum_of_one(
    size: int, expected: int
) -> None:
    assert group_quota(size) == expected


def test_group_movement_uses_group_rank_and_tier_edges() -> None:
    assert group_movement(1, "Silver", 3) == (True, False)
    assert group_movement(2, "Silver", 3) == (False, False)
    assert group_movement(3, "Silver", 3) == (False, True)
    assert group_movement(1, "Silver", 2) == (True, False)
    assert group_movement(2, "Silver", 2) == (False, True)
    assert group_movement(1, "Silver", 1) == (False, False)
    assert group_movement(1, "Diamond", 15) == (False, False)
    assert group_movement(15, "Bronze", 15) == (False, False)

    with pytest.raises(ValueError):
        group_movement(4, "Silver", 3)
    with pytest.raises(ValueError):
        group_movement(1, "Platinum", 3)


def test_three_person_group_promotes_one_and_demotes_one(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    week = WEEK_1
    scores = {"p01": 9_000, "p02": 6_000, "p03": 3_000}
    seed_group(store, week, tier="Silver", prefix="three", scores=scores)

    result = store.settle_week(week, now=settle_at(week))
    rows = sorted(result["results"], key=lambda row: int(row["rank"]))
    assert group_quota(3) == 1
    assert [(row["player_id"], row["rank"]) for row in rows] == [
        ("p01", 1),
        ("p02", 2),
        ("p03", 3),
    ]
    assert [row["promoted"] for row in rows] == [True, False, False]
    assert [row["demoted"] for row in rows] == [False, False, True]
    assert not any(row["promoted"] and row["demoted"] for row in rows)


def test_strong_and_weak_groups_move_independently_within_one_tier(
    tmp_path,
) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    week = WEEK_1
    strong = {f"a{index:02d}": 30_000 - index * 100 for index in range(1, 16)}
    weak = {f"b{index:02d}": 10_000 - index * 100 for index in range(1, 16)}
    strong_group = seed_group(
        store, week, tier="Gold", prefix="strong", scores=strong
    )
    weak_group = seed_group(store, week, tier="Gold", prefix="weak", scores=weak)
    assert strong["a04"] > weak["b01"]

    result = store.settle_week(week, now=settle_at(week))
    grouped = rows_by_group(result["results"])
    strong_rows = grouped[int(strong_group["id"])]
    weak_rows = grouped[int(weak_group["id"])]
    assert len(strong_rows) == len(weak_rows) == 15

    strong_moves = {
        row["player_id"]: (row["promoted"], row["demoted"]) for row in strong_rows
    }
    weak_moves = {
        row["player_id"]: (row["promoted"], row["demoted"]) for row in weak_rows
    }

    # The weak group's own top three promote even though every strong-group
    # player (including rank four) scored higher than them.
    assert [row["player_id"] for row in weak_rows[:3]] == ["b01", "b02", "b03"]
    assert all(weak_moves[f"b{index:02d}"][0] for index in range(1, 4))
    assert weak_moves["b04"] == (False, False)

    # The strong group's fourth place does not promote just because its tier
    # contains weaker groups.
    assert [row["player_id"] for row in strong_rows[:3]] == ["a01", "a02", "a03"]
    assert all(strong_moves[f"a{index:02d}"][0] for index in range(1, 4))
    assert strong_moves["a04"] == (False, False)

    # Both groups independently demote their own bottom three.
    assert all(weak_moves[f"b{index:02d}"][1] for index in range(13, 16))
    assert all(strong_moves[f"a{index:02d}"][1] for index in range(13, 16))
    assert all(
        not (promoted and demoted)
        for promoted, demoted in (*strong_moves.values(), *weak_moves.values())
    )


def test_bronze_never_demotes_and_diamond_never_promotes(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    week = WEEK_1
    bronze = {f"br{index:02d}": 5_000 - index * 10 for index in range(1, 6)}
    diamond = {f"di{index:02d}": 50_000 - index * 10 for index in range(1, 6)}
    bronze_group = seed_group(
        store, week, tier="Bronze", prefix="bronze", scores=bronze
    )
    diamond_group = seed_group(
        store, week, tier="Diamond", prefix="diamond", scores=diamond
    )

    result = store.settle_week(week, now=settle_at(week))
    grouped = rows_by_group(result["results"])
    bronze_rows = grouped[int(bronze_group["id"])]
    diamond_rows = grouped[int(diamond_group["id"])]

    assert group_quota(5) == 1
    assert bronze_rows[0]["promoted"] is True
    assert all(row["demoted"] is False for row in bronze_rows)
    assert diamond_rows[0]["promoted"] is False
    assert all(row["promoted"] is False for row in diamond_rows)
    assert diamond_rows[-1]["demoted"] is True
    assert bronze_rows[-1]["demoted"] is False


def test_978_channel_ai_plus_human_three_week_history(tmp_path) -> None:
    clock = {"now": at(WEEK_1)}
    service = make_service(tmp_path, clock)
    refs = [f"channel-ai-{index:04d}" for index in range(978)]
    first = service.channel_roster(
        CHANNEL, [{"player_ref": ref, "kind": "ai"} for ref in refs]
    )
    assert first["week_start"] == WEEK_1
    assert first["count"] == first["created"] == 978
    store = service.store
    assert store is not None
    store.ensure_human_player(
        "human-1",
        display_name="Human One",
        joined_week=WEEK_1,
        now=at(WEEK_1),
    )
    player_ids = {row["player_id"] for row in first["players"]} | {"human-1"}
    assert len(player_ids) == 979

    group_counts: list[int] = []
    tier_counts: dict[str, Counter[str]] = {}
    settled_results: dict[str, dict] = {}
    movement: dict[str, tuple[Counter[str], Counter[str]]] = {}

    for week_index, week in enumerate((WEEK_1, WEEK_2, WEEK_3)):
        now = at(week)
        clock["now"] = now
        roster = service.channel_roster(
            CHANNEL, [{"player_ref": ref, "kind": "ai"} for ref in refs]
        )
        assert roster["week_start"] == week
        assert roster["count"] == 978

        groups = store.ensure_all_groups(week, now=now)
        sizes = [int(group["member_count"]) for group in groups]
        group_counts.append(len(groups))
        assert sizes
        assert set(sizes) == {14, 15}
        assert min(sizes) == 14

        members = {
            str(member["player_id"])
            for group in groups
            for member in group["members"]
        }
        assert members == player_ids
        for group in groups:
            for member in group["members"]:
                assert store.tier_for_player(
                    str(member["player_id"]), week
                ) == str(group["tier"])

        counts: Counter[str] = Counter()
        for group in groups:
            counts[str(group["tier"])] += int(group["member_count"])
        tier_counts[week] = counts

        # One AI stays at zero seconds to prove an inactive roster member still
        # keeps a place and a weekly result.
        occurred_at = datetime.fromisoformat(f"{week}T12:00:00+08:00")
        for index, ref in enumerate(refs):
            if index == 0:
                continue
            seconds = 300 + ((index * 37 + week_index * 1_000) % 12_000)
            service.channel_increment(
                CHANNEL,
                player_ref=ref,
                event_id=f"{week}:{ref}",
                seconds=seconds,
                occurred_at=occurred_at,
            )
        store.ingest_activity(
            "human-1",
            event_id=f"{week}:human-1",
            seconds=7_000 + week_index * 100,
            occurred_at=occurred_at,
            source=SOURCE_HUMAN,
            now=now,
        )

        settled = store.settle_week(week, now=settle_at(week))
        assert settled["already_settled"] is False
        assert len(settled["results"]) == 979
        assert len({row["player_id"] for row in settled["results"]}) == 979
        assert {row["player_id"] for row in settled["results"]} == player_ids

        group_size = {
            int(group["id"]): int(group["member_count"]) for group in groups
        }
        for group_id, group_rows in rows_by_group(settled["results"]).items():
            assert sorted(int(row["rank"]) for row in group_rows) == list(
                range(1, group_size[group_id] + 1)
            )
        assert all(
            not (row["promoted"] and row["demoted"])
            for row in settled["results"]
        )

        with store.transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM weekly_results WHERE week_start = ?",
                (week,),
            ).fetchone()["n"]
            duplicates = conn.execute(
                "SELECT COUNT(*) AS n FROM ("
                "SELECT player_id FROM weekly_results WHERE week_start = ? "
                "GROUP BY player_id HAVING COUNT(*) > 1)",
                (week,),
            ).fetchone()["n"]
        assert count == 979
        assert duplicates == 0

        movement[week] = (
            Counter(
                row["tier"] for row in settled["results"] if row["promoted"]
            ),
            Counter(row["tier"] for row in settled["results"] if row["demoted"]),
        )
        settled_results[week] = settled

    assert group_counts == [66, 67, 67]
    assert tier_counts[WEEK_1] == Counter({"Bronze": 979})
    assert tier_counts[WEEK_2] == Counter({"Bronze": 781, "Silver": 198})
    assert tier_counts[WEEK_3] == Counter(
        {"Bronze": 664, "Silver": 273, "Gold": 42}
    )

    assert movement[WEEK_1] == (Counter({"Bronze": 198}), Counter())
    assert movement[WEEK_2] == (
        Counter({"Bronze": 159, "Silver": 42}),
        Counter({"Silver": 42}),
    )
    assert movement[WEEK_3] == (
        Counter({"Bronze": 135, "Silver": 57, "Gold": 9}),
        Counter({"Silver": 57, "Gold": 9}),
    )

    # Every settled week is immutable, including older weeks rerun after the
    # whole three-week loop has finished.
    for week in (WEEK_1, WEEK_2, WEEK_3):
        rerun = store.settle_week(week, now=settle_at(WEEK_3))
        assert rerun["already_settled"] is True
        assert rerun["results"] == settled_results[week]["results"]

    with store.transaction() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM weekly_results"
        ).fetchone()["n"]
    assert total == 3 * 979
    assert store.get_week("2026-11-16") is None
