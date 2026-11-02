from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ghost_league.game.jobs import run_auto_assign_rivals, run_daily_bets
from ghost_league.game.rival import (
    BetAlreadyPlaced,
    BetRejected,
    BetWindowClosed,
    RivalUnavailable,
)
from ghost_league.game.rules import InsufficientDiamonds
from ghost_league.game.store import GameStore
from ghost_league.schedule import TZ

WEEK = "2026-11-02"
MONDAY = datetime(2026, 11, 2, 10, 0, 0, tzinfo=TZ)
MONDAY_EVENING = datetime(2026, 11, 2, 19, 59, 59, tzinfo=TZ)
TUESDAY = datetime(2026, 11, 3, 0, 0, 0, tzinfo=TZ)
NEXT_MONDAY = datetime(2026, 11, 9, 0, 5, 0, tzinfo=TZ)


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def add_player(store: GameStore, player_id: str) -> str:
    store.create_player(
        player_id,
        kind="human",
        display_name=player_id,
        joined_week=WEEK,
        now=MONDAY,
    )
    return player_id


def set_week_xp(
    store: GameStore, player_id: str, xp: int, *, week: str = WEEK
) -> None:
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO weekly_scores "
            "(week_start, player_id, seconds, xp) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(week_start, player_id) DO UPDATE SET "
            "seconds = excluded.seconds, xp = excluded.xp",
            (week, player_id, xp * 6, xp),
        )


def add_activity(
    store: GameStore,
    player_id: str,
    *,
    event_id: str,
    seconds: int,
    occurred_at: datetime,
    now: datetime | None = None,
) -> None:
    store.ingest_activity(
        player_id,
        event_id=event_id,
        seconds=seconds,
        occurred_at=occurred_at,
        source="local_increment",
        now=now or occurred_at,
    )


def make_rival_pair(
    store: GameStore,
    left: str,
    right: str,
    *,
    left_power: int = 500,
    right_power: int = 700,
) -> None:
    add_player(store, left)
    add_player(store, right)
    store.create_group(WEEK, tier="Bronze", player_ids=[left], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=[right], now=MONDAY)
    with store.transaction() as conn:
        conn.execute(
            "UPDATE players SET power = ? WHERE id = ?", (left_power, left)
        )
        conn.execute(
            "UPDATE players SET power = ? WHERE id = ?", (right_power, right)
        )
    set_week_xp(store, left, 100)
    set_week_xp(store, right, 100)
    store.select_rival(left, right, now=MONDAY, request_id=f"rival-{left}")


def test_weekly_bet_debits_once_and_closes_after_monday(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "h1", "h2")
    make_rival_pair(store, "h3", "h4")

    bet = store.place_bet(
        "h1", "weekly", 20, None, now=MONDAY, request_id="weekly-1"
    )
    assert bet["kind"] == "weekly"
    assert bet["stake"] == 20
    assert bet["odds"] == 2.0
    assert bet["status"] == "placed"
    assert store.get_diamond_balance("h1", now=MONDAY) == 980

    repeat = store.place_bet(
        "h1", "weekly", 20, None, now=MONDAY, request_id="weekly-1"
    )
    assert repeat["id"] == bet["id"]
    assert store.get_diamond_balance("h1", now=MONDAY) == 980

    with pytest.raises(BetAlreadyPlaced):
        store.place_bet(
            "h1", "weekly", 40, None, now=MONDAY, request_id="weekly-2"
        )
    with pytest.raises(BetWindowClosed):
        store.place_bet(
            "h3", "weekly", 40, None, now=TUESDAY, request_id="weekly-3"
        )
    with pytest.raises(BetRejected):
        store.place_bet(
            "h3", "weekly", 30, None, now=MONDAY, request_id="weekly-4"
        )
    assert store.get_diamond_balance("h1", now=MONDAY) == 980


def test_bet_requires_rival_and_enough_diamonds(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "no-rival")
    with pytest.raises(RivalUnavailable):
        store.place_bet(
            "no-rival", "weekly", 20, None, now=MONDAY, request_id="none"
        )

    make_rival_pair(store, "poor", "rich")
    with store.transaction() as conn:
        conn.execute(
            "UPDATE diamond_balance SET balance = 10 WHERE player_id = ?",
            ("poor",),
        )
    with pytest.raises(InsufficientDiamonds):
        store.place_bet(
            "poor", "weekly", 60, None, now=MONDAY, request_id="poor-1"
        )
    assert store.bets_for("poor", now=MONDAY)["weekly"] is None
    assert store.get_diamond_balance("poor", now=MONDAY) == 10


def test_daily_bet_window_and_validation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "h1", "h2")
    make_rival_pair(store, "h3", "h4")

    bet = store.place_bet(
        "h1", "daily", None, 50, now=MONDAY_EVENING, request_id="daily-1"
    )
    assert bet["kind"] == "daily"
    assert bet["stake"] == 20
    assert bet["target_margin"] == 50
    assert bet["odds"] == 1.5
    assert store.get_diamond_balance("h1", now=MONDAY_EVENING) == 980

    with pytest.raises(BetRejected):
        store.place_bet(
            "h3", "daily", None, 100, now=MONDAY, request_id="daily-bad-target"
        )
    with pytest.raises(BetRejected):
        store.place_bet(
            "h3", "daily", 40, 50, now=MONDAY, request_id="daily-bad-stake"
        )
    with pytest.raises(BetWindowClosed):
        store.place_bet(
            "h3",
            "daily",
            None,
            50,
            now=datetime(2026, 11, 2, 20, 0, 0, tzinfo=TZ),
            request_id="daily-late",
        )
    assert store.get_diamond_balance("h3", now=MONDAY) == 1000


def test_daily_settlement_waits_for_22_and_uses_2200_xp(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "h1", "h2")
    add_activity(
        store,
        "h1",
        event_id="h1-early",
        seconds=1200,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    add_activity(
        store,
        "h2",
        event_id="h2-early",
        seconds=600,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    store.place_bet(
        "h1", "daily", None, 50, now=MONDAY, request_id="daily-win"
    )

    early = store.settle_daily_bets(
        "2026-11-02", now=datetime(2026, 11, 2, 21, 59, 0, tzinfo=TZ)
    )
    assert early["status"] == "skipped"
    assert store.bets_for("h1", now=MONDAY)["daily"]["status"] == "placed"

    settled = store.settle_daily_bets(
        "2026-11-02", now=datetime(2026, 11, 2, 22, 0, 0, tzinfo=TZ)
    )
    assert settled["settled"] == 1
    assert settled["results"][0]["status"] == "won"
    assert settled["results"][0]["payout"] == 30
    assert settled["results"][0]["result_diff"] == 100
    assert (
        store.get_diamond_balance(
            "h1", now=datetime(2026, 11, 2, 22, 0, 0, tzinfo=TZ)
        )
        == 1010
    )

    again = store.settle_daily_bets(
        "2026-11-02", now=datetime(2026, 11, 2, 22, 5, 0, tzinfo=TZ)
    )
    assert again["settled"] == 0
    assert (
        store.get_diamond_balance(
            "h1", now=datetime(2026, 11, 2, 22, 5, 0, tzinfo=TZ)
        )
        == 1010
    )


def test_daily_settlement_ignores_activity_after_2200(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "h1", "h2")
    add_activity(
        store,
        "h1",
        event_id="h1-before",
        seconds=1200,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    add_activity(
        store,
        "h2",
        event_id="h2-before",
        seconds=600,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    store.place_bet(
        "h1", "daily", None, 300, now=MONDAY, request_id="daily-cutoff"
    )

    # A late burst would make the final day XP much higher, but the 22:00
    # snapshot must not see it.
    add_activity(
        store,
        "h1",
        event_id="h1-late",
        seconds=3000,
        occurred_at=datetime(2026, 11, 2, 23, 0, 0, tzinfo=TZ),
        now=datetime(2026, 11, 2, 23, 0, 0, tzinfo=TZ),
    )
    settled = store.settle_daily_bets(
        "2026-11-02", now=datetime(2026, 11, 2, 23, 30, 0, tzinfo=TZ)
    )
    assert settled["results"][0]["status"] == "lost"
    assert settled["results"][0]["result_diff"] == 100
    assert settled["results"][0]["payout"] == 0
    assert (
        store.get_diamond_balance(
            "h1", now=datetime(2026, 11, 2, 23, 30, 0, tzinfo=TZ)
        )
        == 980
    )


def test_daily_loss_and_weekly_draw_refund(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "daily", "daily-rival")
    add_activity(
        store,
        "daily",
        event_id="daily-early",
        seconds=600,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    add_activity(
        store,
        "daily-rival",
        event_id="daily-rival-early",
        seconds=1200,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    store.place_bet(
        "daily", "daily", None, 50, now=MONDAY, request_id="daily-loss"
    )
    store.settle_daily_bets(
        "2026-11-02", now=datetime(2026, 11, 2, 22, 0, 0, tzinfo=TZ)
    )
    assert (
        store.get_diamond_balance(
            "daily", now=datetime(2026, 11, 2, 22, 0, 0, tzinfo=TZ)
        )
        == 980
    )

    make_rival_pair(store, "weekly", "weekly-rival")
    set_week_xp(store, "weekly", 200)
    set_week_xp(store, "weekly-rival", 200)
    store.place_bet(
        "weekly", "weekly", 20, None, now=MONDAY, request_id="weekly-draw"
    )
    settled = store.settle_weekly_bets(WEEK, now=NEXT_MONDAY)
    assert settled["settled"] == 1
    assert settled["results"][0]["status"] == "void"
    assert settled["results"][0]["payout"] == 20
    assert store.get_diamond_balance("weekly", now=NEXT_MONDAY) == 1000


def test_weekly_bet_win_and_loss(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "winner", "winner-rival")
    make_rival_pair(store, "loser", "loser-rival")
    set_week_xp(store, "winner", 300)
    set_week_xp(store, "winner-rival", 100)
    set_week_xp(store, "loser", 50)
    set_week_xp(store, "loser-rival", 100)
    store.place_bet(
        "winner", "weekly", 20, None, now=MONDAY, request_id="weekly-win"
    )
    store.place_bet(
        "loser", "weekly", 40, None, now=MONDAY, request_id="weekly-loss"
    )

    early = store.settle_weekly_bets(WEEK, now=MONDAY)
    assert early["status"] == "skipped"

    settled = store.settle_weekly_bets(WEEK, now=NEXT_MONDAY)
    assert settled["settled"] == 2
    by_rival = {row["rival_id"]: row for row in settled["results"]}
    assert by_rival["winner-rival"]["status"] == "won"
    assert by_rival["winner-rival"]["payout"] == 40
    assert by_rival["loser-rival"]["status"] == "lost"
    assert by_rival["loser-rival"]["payout"] == 0
    assert store.get_diamond_balance("winner", now=NEXT_MONDAY) == 1020
    assert store.get_diamond_balance("loser", now=NEXT_MONDAY) == 960

    again = store.settle_weekly_bets(WEEK, now=NEXT_MONDAY)
    assert again["settled"] == 0
    assert store.get_diamond_balance("winner", now=NEXT_MONDAY) == 1020


def test_settle_week_runs_rivals_and_weekly_bets_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "h1", "h2")
    add_activity(
        store,
        "h1",
        event_id="h1-week",
        seconds=1800,
        occurred_at=datetime(2026, 11, 6, 12, 0, 0, tzinfo=TZ),
    )
    add_activity(
        store,
        "h2",
        event_id="h2-week",
        seconds=600,
        occurred_at=datetime(2026, 11, 6, 12, 0, 0, tzinfo=TZ),
    )
    store.place_bet(
        "h1", "weekly", 20, None, now=MONDAY, request_id="weekly-integration"
    )

    settled = store.settle_week(WEEK, now=NEXT_MONDAY)
    assert settled["already_settled"] is False
    assert settled["rivals"]["results"][0]["outcome"] == "win"
    assert settled["rivals"]["results"][0]["reward_diamonds"] == 120
    assert settled["weekly_bets"]["results"][0]["status"] == "won"
    assert store.get_diamond_balance("h1", now=NEXT_MONDAY) == 1140

    again = store.settle_week(WEEK, now=NEXT_MONDAY)
    assert again["already_settled"] is True
    assert store.get_diamond_balance("h1", now=NEXT_MONDAY) == 1140
    rewards = [
        row
        for row in store.diamond_ledger("h1")
        if row["reason"] in {"rival_reward", "bet_payout"}
    ]
    assert len(rewards) == 2


def test_rival_auto_and_daily_bet_jobs(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "h1", "h2")
    # Remove the manual rival so the auto job has work to do.
    with store.transaction() as conn:
        conn.execute("DELETE FROM rival_assignments")
    early = run_auto_assign_rivals(store.path, at=MONDAY)
    assert early["status"] == "skipped"
    auto = run_auto_assign_rivals(store.path, at=TUESDAY)
    assert auto["status"] == "ok"
    assert auto["assigned"] >= 1
    assert store.rival_state("h1", now=TUESDAY)["rival"] is not None

    daily_store = GameStore(tmp_path / "daily.db", epoch_reason="test")
    make_rival_pair(daily_store, "h1", "h2")
    add_activity(
        daily_store,
        "h1",
        event_id="job-h1",
        seconds=1200,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    add_activity(
        daily_store,
        "h2",
        event_id="job-h2",
        seconds=600,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
    )
    daily_store.place_bet(
        "h1", "daily", None, 50, now=MONDAY, request_id="job-daily"
    )
    result = run_daily_bets(
        daily_store.path, at=datetime(2026, 11, 2, 22, 0, 0, tzinfo=TZ)
    )
    assert result["status"] == "settled"
    assert result["settled"] == 1
