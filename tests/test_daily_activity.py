from __future__ import annotations

from pathlib import Path

from ghost_league.game import calendar as cal
from ghost_league.game.store import GameStore

WEEK = "2026-11-02"
NOW = "2026-11-02T12:00:00+08:00"


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def add_player(store: GameStore, player_id: str = "p1") -> str:
    store.create_player(
        player_id,
        display_name=player_id,
        joined_week=WEEK,
        now=NOW,
    )
    return player_id


def seed_activity_event(
    store: GameStore,
    player_id: str,
    seconds: int,
    *,
    day: str,
    event_id: str,
) -> None:
    occurred_at = f"{day}T12:00:00+08:00"
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO activity_events "
            "(player_id, event_id, seconds, occurred_at, week_start, source, "
            "created_at) VALUES (?, ?, ?, ?, ?, 'local_increment', ?)",
            (
                player_id,
                event_id,
                seconds,
                occurred_at,
                cal.week_start(day).isoformat(),
                occurred_at,
            ),
        )


def seed_channel_event(
    store: GameStore,
    player_id: str,
    seconds: int,
    *,
    day: str,
    event_id: str,
) -> None:
    occurred_at = f"{day}T12:00:00+08:00"
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO channel_events "
            "(event_id, channel_id, player_ref, player_id, seconds, "
            "occurred_at, week_start, created_at) "
            "VALUES (?, 'test-channel', ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                player_id,
                player_id,
                seconds,
                occurred_at,
                cal.week_start(day).isoformat(),
                occurred_at,
            ),
        )


def seed_checkin(
    store: GameStore,
    player_id: str,
    *,
    day: str,
    xp: int,
    seconds: int,
) -> None:
    checked_at = f"{day}T09:00:00+08:00"
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO checkins "
            "(player_id, date, source, seconds, xp, checked_at, repaired_at, "
            "repair_cost, status, created_at) "
            "VALUES (?, ?, 'verified', ?, ?, ?, NULL, 0, 'verified', ?)",
            (player_id, day, seconds, xp, checked_at, 0),
        )


def test_checkin_is_authoritative_even_when_its_xp_is_zero(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store)
    seed_activity_event(store, "p1", 600, day=WEEK, event_id="activity")
    seed_channel_event(store, "p1", 600, day=WEEK, event_id="channel")
    seed_checkin(store, "p1", day=WEEK, xp=0, seconds=0)

    assert store.daily_activity_on_day("p1", WEEK) == {
        "checkin_source": "verified",
        "seconds": 0,
        "xp": 0,
    }
    assert store.daily_xp_between("p1", WEEK, "2026-11-03") == {WEEK: 0}


def test_without_checkin_raw_sources_use_the_daily_max(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "activity-wins")
    add_player(store, "channel-wins")
    seed_activity_event(
        store, "activity-wins", 300, day=WEEK, event_id="activity-a"
    )
    seed_activity_event(
        store, "activity-wins", 300, day=WEEK, event_id="activity-b"
    )
    seed_channel_event(
        store, "activity-wins", 420, day=WEEK, event_id="channel-a"
    )
    seed_activity_event(
        store, "channel-wins", 120, day=WEEK, event_id="activity-c"
    )
    seed_channel_event(
        store, "channel-wins", 240, day=WEEK, event_id="channel-b"
    )
    seed_channel_event(
        store, "channel-wins", 60, day=WEEK, event_id="channel-c"
    )

    activity = store.daily_activity_on_day("activity-wins", WEEK)
    assert activity == {
        "checkin_source": None,
        "seconds": 600,
        "xp": 100,
    }
    channel = store.daily_activity_on_day("channel-wins", WEEK)
    assert channel == {
        "checkin_source": None,
        "seconds": 300,
        "xp": 50,
    }


def test_without_checkin_one_source_or_none_is_still_resolved(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "activity-only")
    add_player(store, "channel-only")
    add_player(store, "empty")
    seed_activity_event(
        store, "activity-only", 180, day=WEEK, event_id="activity-only"
    )
    seed_channel_event(
        store, "channel-only", 240, day=WEEK, event_id="channel-only"
    )

    assert store.daily_activity_on_day("activity-only", WEEK) == {
        "checkin_source": None,
        "seconds": 180,
        "xp": 30,
    }
    assert store.daily_activity_on_day("channel-only", WEEK) == {
        "checkin_source": None,
        "seconds": 240,
        "xp": 40,
    }
    assert store.daily_activity_on_day("empty", WEEK) == {
        "checkin_source": None,
        "seconds": 0,
        "xp": 0,
    }


def test_daily_xp_between_returns_every_day_in_the_window(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store)
    days = [
        "2026-11-02",
        "2026-11-03",
        "2026-11-04",
        "2026-11-05",
        "2026-11-06",
        "2026-11-07",
        "2026-11-08",
    ]
    seed_checkin(store, "p1", day=days[0], xp=5, seconds=30)
    seed_activity_event(store, "p1", 300, day=days[2], event_id="activity")
    seed_channel_event(store, "p1", 240, day=days[6], event_id="channel")

    assert store.daily_xp_between("p1", days[0], "2026-11-09") == {
        days[0]: 5,
        days[1]: 0,
        days[2]: 50,
        days[3]: 0,
        days[4]: 0,
        days[5]: 0,
        days[6]: 40,
    }
    assert store.daily_xp_between("p1", days[0], days[0]) == {}
