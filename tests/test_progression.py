from __future__ import annotations

import json

import pytest

from ghost_league.game.store import GameStore

WEEK = "2026-10-19"
NEXT_WEEK = "2026-10-26"


def make_store(tmp_path, *, epoch_started_at=None) -> GameStore:
    return GameStore(
        tmp_path / "league.db",
        epoch_reason="test",
        epoch_started_at=epoch_started_at,
    )


def make_player(
    store: GameStore,
    player_id: str,
    *,
    kind: str = "human",
    joined_week: str = WEEK,
) -> None:
    store.create_player(
        player_id,
        kind=kind,
        joined_week=joined_week,
        now=f"{joined_week}T00:00:00+08:00",
    )


def checkin(
    store: GameStore,
    player_id: str,
    day: str,
    *,
    event_id: str | None = None,
    seconds: int = 600,
) -> dict:
    return store.ingest_activity(
        player_id,
        event_id=event_id or f"evt:{player_id}:{day}",
        seconds=seconds,
        occurred_at=f"{day}T10:00:00+08:00",
        source="local_increment",
        now=f"{day}T10:00:00+08:00",
    )


def milestone_ids(store: GameStore, player_id: str) -> list[str]:
    return [row["milestone_id"] for row in store.awarded_milestones(player_id)]


def test_first_checkin_awards_once_and_replay_is_idempotent(tmp_path) -> None:
    store = make_store(tmp_path)
    make_player(store, "human-1")
    first = checkin(store, "human-1", "2026-10-19")
    assert first["checkin"]["created"] is True
    assert milestone_ids(store, "human-1") == ["first_checkin"]

    collection = store.collection("human-1")
    assert [row["id"] for row in collection["titles"]] == ["title_ignition"]
    assert [row["id"] for row in collection["items"]] == ["frame_ember"]

    # The same event and a different event on the same day both stay idempotent.
    checkin(store, "human-1", "2026-10-19", event_id="evt:human-1:2026-10-19")
    checkin(store, "human-1", "2026-10-19", event_id="evt:extra", seconds=60)
    assert milestone_ids(store, "human-1") == ["first_checkin"]
    with store.transaction() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM player_titles WHERE player_id = 'human-1'"
        ).fetchone()["n"] == 1
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM player_items WHERE player_id = 'human-1'"
        ).fetchone()["n"] == 1


def test_three_and_seven_day_streaks_each_award_once(tmp_path) -> None:
    store = make_store(tmp_path)
    make_player(store, "human-1")
    days = [f"2026-10-{day:02d}" for day in range(19, 26)]
    for day in days[:3]:
        checkin(store, "human-1", day)
    assert "streak_3" in milestone_ids(store, "human-1")
    assert "streak_7" not in milestone_ids(store, "human-1")
    for day in days[3:]:
        checkin(store, "human-1", day)
    assert "streak_7" in milestone_ids(store, "human-1")

    ids = milestone_ids(store, "human-1")
    assert ids.count("streak_3") == 1
    assert ids.count("streak_7") == 1
    # Day settlement is another trigger and still must not duplicate awards.
    store.grant_daily_embers(
        "human-1", days[-1], now=f"{days[-1]}T23:00:00+08:00"
    )
    assert milestone_ids(store, "human-1").count("streak_7") == 1
    collection = store.collection("human-1")
    assert "backdrop_night" in [row["id"] for row in collection["items"]]


def test_repaired_checkin_counts_for_three_day_streak(tmp_path) -> None:
    store = make_store(tmp_path)
    make_player(store, "human-1")
    checkin(store, "human-1", "2026-10-19")
    checkin(store, "human-1", "2026-10-20", seconds=300)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO ember_balance "
            "(player_id, balance, week_earned, week_start, updated_at) "
            "VALUES ('human-1', 1, 0, ?, ?)",
            (WEEK, "2026-10-21T09:00:00+08:00"),
        )
    repaired = store.repair_checkin(
        "human-1",
        "2026-10-20",
        idempotency_key="repair-1",
        now="2026-10-21T09:00:00+08:00",
    )
    assert repaired["repaired"] is True
    checkin(store, "human-1", "2026-10-21")
    assert "streak_3" in milestone_ids(store, "human-1")
    # Repairing did not fabricate a weekly result or change XP/rank.
    assert store.history("human-1") == []


def test_weekly_rank_top3_champion_and_promotion_are_idempotent(tmp_path) -> None:
    store = make_store(tmp_path)
    players = ["p01", "p02", "p03", "p04", "p05"]
    for player_id in players:
        make_player(store, player_id, kind="ai" if player_id == "p02" else "human")
    store.create_group(
        WEEK,
        tier="Bronze",
        player_ids=players,
        now=f"{WEEK}T00:00:00+08:00",
    )
    for index, player_id in enumerate(players):
        store.ingest_activity(
            player_id,
            event_id=f"week:{player_id}",
            seconds=6000 - index * 600,
            occurred_at=f"{WEEK}T12:00:00+08:00",
            source="local_increment",
            now=f"{WEEK}T12:00:00+08:00",
        )
    first = store.settle_week(WEEK, now=f"{NEXT_WEEK}T00:05:00+08:00")
    assert first["already_settled"] is False

    assert {"top_3", "champion", "promoted"} <= set(milestone_ids(store, "p01"))
    assert "top_3" in milestone_ids(store, "p02")
    assert "champion" not in milestone_ids(store, "p02")
    assert "top_3" in milestone_ids(store, "p03")
    assert "top_3" not in milestone_ids(store, "p04")

    before = {player: len(store.awarded_milestones(player)) for player in players}
    second = store.settle_week(WEEK, now=f"{NEXT_WEEK}T00:06:00+08:00")
    assert second["already_settled"] is True
    assert {player: len(store.awarded_milestones(player)) for player in players} == before


def test_ai_and_humans_use_the_same_awards_and_ai_taste_is_unlocked(tmp_path) -> None:
    store = make_store(tmp_path)
    make_player(store, "human-1")
    make_player(store, "ai-1", kind="ai")
    for player_id in ("human-1", "ai-1"):
        checkin(store, player_id, "2026-10-19")
    assert milestone_ids(store, "ai-1") == milestone_ids(store, "human-1")
    assert "title_ignition" in [row["id"] for row in store.collection("ai-1")["titles"]]

    first = store.loadout_view("ai-1")
    second = store.loadout_view("ai-1")
    assert first == second
    unlocked_titles = {row["id"] for row in store.collection("ai-1")["titles"]}
    unlocked_items = {row["id"] for row in store.collection("ai-1")["items"]}
    assert first["title_id"] in unlocked_titles
    for field in ("frame_id", "backdrop_id", "badge_accent_id"):
        assert first[field] is None or first[field] in unlocked_items


def test_loadout_only_accepts_unlocked_slot_matches(tmp_path) -> None:
    store = make_store(tmp_path)
    make_player(store, "human-1")
    checkin(store, "human-1", "2026-10-19")
    equipped = store.update_loadout(
        "human-1", title_id="title_ignition", frame_id="frame_ember"
    )
    assert equipped["title"] == "点火"
    assert equipped["frame"] == "余烬"
    assert store.collection("human-1")["equipped"]["title_id"] == "title_ignition"

    with pytest.raises(ValueError):
        store.update_loadout("human-1", title_id="title_missing")
    with pytest.raises(ValueError):
        store.update_loadout("human-1", title_id="frame_ember")
    with pytest.raises(ValueError):
        store.update_loadout("human-1", frame_id="badge_champion")
    with pytest.raises(ValueError):
        # Known catalog item, but this player has not unlocked it.
        store.update_loadout("human-1", backdrop_id="backdrop_night")
    # Clearing an equipped slot is allowed.
    cleared = store.update_loadout("human-1", title_id=None)
    assert cleared["title_id"] is None


def test_old_history_is_not_backfilled_into_a_new_epoch(tmp_path) -> None:
    start = "2026-10-28T00:00:00+08:00"
    store = make_store(tmp_path, epoch_started_at=start)
    make_player(store, "human-1", joined_week="2026-10-19")
    with store.transaction() as conn:
        for day in ("2026-10-19", "2026-10-20", "2026-10-21"):
            conn.execute(
                "INSERT INTO checkins "
                "(player_id, date, source, seconds, xp, checked_at, repaired_at, "
                "repair_cost, status) VALUES (?, ?, 'verified', 600, 100, ?, NULL, 0, 'verified')",
                ("human-1", day, f"{day}T10:00:00+08:00"),
            )
    # Triggering old-day settlement must not look backwards.
    store.grant_daily_embers(
        "human-1",
        "2026-10-21",
        now="2026-10-28T09:00:00+08:00",
    )
    assert store.awarded_milestones("human-1") == []
    checkin(store, "human-1", "2026-10-28")
    ids = milestone_ids(store, "human-1")
    assert "first_checkin" in ids
    assert "streak_3" not in ids
    assert "streak_7" not in ids


def test_milestones_do_not_change_xp_rank_or_group(tmp_path) -> None:
    store = make_store(tmp_path)
    players = ["p01", "p02", "p03"]
    for player_id in players:
        make_player(store, player_id)
    group = store.create_group(
        WEEK, tier="Silver", player_ids=players, now=f"{WEEK}T00:00:00+08:00"
    )
    for index, player_id in enumerate(players):
        store.ingest_activity(
            player_id,
            event_id=f"score:{player_id}",
            seconds=6000 - index * 600,
            occurred_at=f"{WEEK}T12:00:00+08:00",
            source="local_increment",
            now=f"{WEEK}T12:00:00+08:00",
        )
    before_scores = {
        player_id: store.get_week_score(player_id, WEEK)["seconds"]
        for player_id in players
    }
    store.settle_week(WEEK, now=f"{NEXT_WEEK}T00:05:00+08:00")
    after_scores = {
        player_id: store.get_week_score(player_id, WEEK)["seconds"]
        for player_id in players
    }
    assert after_scores == before_scores
    assert store.group_for_player("p01", WEEK)["id"] == group["id"]
    assert json.dumps(store.collection("p01"), ensure_ascii=False)
