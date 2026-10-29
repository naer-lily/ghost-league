from __future__ import annotations

import pytest

from ghost_league.game.rules import DuplicateIdempotencyKey, RepairRejected
from ghost_league.game.store import GameStore


def new_player(store: GameStore, player_id: str, week: str = "2026-10-05") -> str:
    store.create_player(
        player_id,
        kind="human",
        joined_week=week,
        now=f"{week}T00:00:00+08:00",
    )
    return player_id


def add(store: GameStore, player_id: str, event_id: str, seconds: int, at: str) -> None:
    store.ingest_activity(
        player_id,
        event_id=event_id,
        seconds=seconds,
        occurred_at=at,
        source="local_increment",
        now=at,
    )


def grant(store: GameStore, player_id: str, day: str, now: str) -> dict:
    return store.grant_daily_embers(player_id, day, now=now)


def test_auto_checkin_threshold_and_duplicate_event(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    pid = new_player(store, "auto")
    add(store, pid, "a", 599, "2026-10-05T10:00:00+08:00")
    assert store.get_checkin(pid, "2026-10-05") is None
    result = add(store, pid, "b", 1, "2026-10-05T11:00:00+08:00")
    checkin = store.get_checkin(pid, "2026-10-05")
    assert checkin["source"] == "verified"
    assert checkin["seconds"] == 600
    assert checkin["xp"] == 100
    add(store, pid, "b", 1, "2026-10-05T11:00:00+08:00")
    assert store.get_checkin(pid, "2026-10-05")["seconds"] == 600
    assert result is None  # helper intentionally does not return values
    assert store.get_streak(pid)["current"] == 1


def test_streak_break_grants_clown_title_and_frame(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    pid = new_player(store, "clown")
    add(store, pid, "day-one", 600, "2026-10-05T10:00:00+08:00")
    streak = store.get_streak(pid)
    assert streak is not None and streak["current"] == 1
    store.refresh_streak(pid, today="2026-10-07", now="2026-10-07T00:05:00+08:00")
    collection = store.collection(pid)
    assert "title_clown" in {title["id"] for title in collection["titles"]}
    assert "frame_clown" in {item["id"] for item in collection["items"]}
    streak = store.get_streak(pid)
    assert streak is not None and streak["current"] == 0


def test_ember_grant_weekly_cap_and_balance_cap(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")

    weekly = new_player(store, "weekly", "2026-10-05")
    add(store, weekly, "w1", 24000, "2026-10-05T10:00:00+08:00")
    first = grant(store, weekly, "2026-10-05", "2026-10-06T00:05:00+08:00")
    second = grant(store, weekly, "2026-10-06", "2026-10-07T00:05:00+08:00")
    add(store, weekly, "w2", 24000, "2026-10-06T10:00:00+08:00")
    third = grant(store, weekly, "2026-10-06", "2026-10-07T00:06:00+08:00")
    assert first["granted"] == 2
    assert second["granted"] == 0
    assert third["granted"] == 0
    assert store.get_ember_balance(weekly)["balance"] == 2

    capped = new_player(store, "capped", "2026-10-05")
    add(store, capped, "c1", 48000, "2026-10-05T10:00:00+08:00")
    assert grant(store, capped, "2026-10-05", "2026-10-06T00:05:00+08:00")[
        "balance"
    ] == 2
    add(store, capped, "c2", 48000, "2026-10-12T10:00:00+08:00")
    assert grant(store, capped, "2026-10-12", "2026-10-13T00:05:00+08:00")[
        "balance"
    ] == 3
    add(store, capped, "c3", 48000, "2026-10-19T10:00:00+08:00")
    at_cap = grant(store, capped, "2026-10-19", "2026-10-20T00:05:00+08:00")
    assert at_cap["granted"] == 0
    assert at_cap["balance"] == 3
    assert at_cap["week_earned"] == 0


def test_repair_restores_streak_without_changing_weekly_score(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    pid = new_player(store, "repairer", "2026-10-12")
    add(store, pid, "mon", 24000, "2026-10-19T10:00:00+08:00")
    grant(store, pid, "2026-10-19", "2026-10-20T00:05:00+08:00")
    add(store, pid, "tue", 300, "2026-10-20T10:00:00+08:00")
    before = store.get_week_score(pid, "2026-10-19")

    result = store.repair_checkin(
        pid,
        "2026-10-20",
        idempotency_key="repair-tue",
        now="2026-10-21T12:00:00+08:00",
    )
    assert result["repaired"] is True
    assert result["embers_spent"] == 1
    assert result["balance"] == 1
    assert result["current_streak"] == 2
    assert result["clean_current"] == 1
    checkin = store.get_checkin(pid, "2026-10-20")
    assert checkin["source"] == "repaired"
    assert checkin["repair_cost"] == 1
    after = store.get_week_score(pid, "2026-10-19")
    assert after["seconds"] == before["seconds"]
    assert after["xp"] == before["xp"]
    assert after["rank"] == before["rank"]

    duplicate = store.repair_checkin(
        pid,
        "2026-10-20",
        idempotency_key="repair-tue",
        now="2026-10-21T13:00:00+08:00",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["balance"] == 1
    with pytest.raises(RepairRejected) as exc:
        store.repair_checkin(
            pid,
            "2026-10-20",
            idempotency_key="repair-tue-2",
            now="2026-10-21T13:00:00+08:00",
        )
    assert exc.value.code == "already_checked_in"


def test_repair_accepts_t_minus_two_within_window(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    pid = new_player(store, "two-days", "2026-10-12")
    add(store, pid, "prev", 24000, "2026-10-12T10:00:00+08:00")
    grant(store, pid, "2026-10-12", "2026-10-13T00:05:00+08:00")
    add(store, pid, "target", 200, "2026-10-19T10:00:00+08:00")
    result = store.repair_checkin(
        pid,
        "2026-10-19",
        idempotency_key="t-2",
        now="2026-10-21T12:00:00+08:00",
    )
    assert result["repaired"] is True
    assert result["seconds"] == 200


def test_repair_window_is_seven_days_for_d7_and_rejects_d8(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")
    pid = new_player(store, "seven-day-window", "2026-10-26")
    add(store, pid, "ember", 24000, "2026-10-27T10:00:00+08:00")
    grant(store, pid, "2026-10-27", "2026-10-28T00:05:00+08:00")
    add(store, pid, "d7", 300, "2026-11-01T10:00:00+08:00")
    add(store, pid, "d8", 300, "2026-10-31T10:00:00+08:00")

    repaired = store.repair_checkin(
        pid,
        "2026-11-01",
        idempotency_key="d7-repair",
        now="2026-11-08T23:59:00+08:00",
    )
    assert repaired["repaired"] is True
    assert repaired["date"] == "2026-11-01"

    with pytest.raises(RepairRejected) as exc:
        store.repair_checkin(
            pid,
            "2026-10-31",
            idempotency_key="d8-repair",
            now="2026-11-08T12:00:00+08:00",
        )
    assert exc.value.code == "outside_window"


def test_repair_rejections_are_explicit_and_idempotent_key_is_global(tmp_path) -> None:
    store = GameStore(tmp_path / "league.db", epoch_reason="test")

    zero = new_player(store, "zero", "2026-10-12")
    add(store, zero, "z-prev", 24000, "2026-10-12T10:00:00+08:00")
    grant(store, zero, "2026-10-12", "2026-10-13T00:05:00+08:00")
    with pytest.raises(RepairRejected) as exc:
        store.repair_checkin(
            zero,
            "2026-10-20",
            idempotency_key="zero-key",
            now="2026-10-21T12:00:00+08:00",
        )
    assert exc.value.code == "zero_xp"

    poor = new_player(store, "poor", "2026-10-12")
    add(store, poor, "p", 300, "2026-10-20T10:00:00+08:00")
    with pytest.raises(RepairRejected) as exc:
        store.repair_checkin(
            poor,
            "2026-10-20",
            idempotency_key="poor-key",
            now="2026-10-21T12:00:00+08:00",
        )
    assert exc.value.code == "insufficient_embers"

    old = new_player(store, "old", "2026-10-12")
    with pytest.raises(RepairRejected) as exc:
        store.repair_checkin(
            old,
            "2026-10-13",
            idempotency_key="old-key",
            now="2026-10-21T12:00:00+08:00",
        )
    assert exc.value.code == "outside_window"

    today = new_player(store, "today", "2026-10-12")
    with pytest.raises(RepairRejected) as exc:
        store.repair_checkin(
            today,
            "2026-10-21",
            idempotency_key="today-key",
            now="2026-10-21T12:00:00+08:00",
        )
    assert exc.value.code == "today_or_future"

    natural = new_player(store, "natural", "2026-10-12")
    add(store, natural, "n-prev", 24000, "2026-10-12T10:00:00+08:00")
    grant(store, natural, "2026-10-12", "2026-10-13T00:05:00+08:00")
    add(store, natural, "n", 600, "2026-10-20T10:00:00+08:00")
    with pytest.raises(RepairRejected) as exc:
        store.repair_checkin(
            natural,
            "2026-10-20",
            idempotency_key="natural-key",
            now="2026-10-21T12:00:00+08:00",
        )
    assert exc.value.code == "already_checked_in"

    # Reusing a successful key for a different request is rejected.
    repairer = new_player(store, "key-owner", "2026-10-12")
    add(store, repairer, "k-prev", 24000, "2026-10-12T10:00:00+08:00")
    grant(store, repairer, "2026-10-12", "2026-10-13T00:05:00+08:00")
    add(store, repairer, "k", 300, "2026-10-20T10:00:00+08:00")
    store.repair_checkin(
        repairer,
        "2026-10-20",
        idempotency_key="shared-key",
        now="2026-10-21T12:00:00+08:00",
    )
    with pytest.raises(DuplicateIdempotencyKey):
        store.repair_checkin(
            repairer,
            "2026-10-19",
            idempotency_key="shared-key",
            now="2026-10-21T12:00:00+08:00",
        )
