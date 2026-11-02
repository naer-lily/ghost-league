from __future__ import annotations

import sqlite3
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


def test_weekly_bet_uses_free_stake_and_closes_after_monday(
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
    assert bet["free_stake"] == 20
    assert bet["paid_stake"] == 0
    assert bet["odds"] == 2.0
    assert bet["status"] == "placed"
    assert store.get_diamond_balance("h1", now=MONDAY) == 1000

    repeat = store.place_bet(
        "h1", "weekly", 20, None, now=MONDAY, request_id="weekly-1"
    )
    assert repeat["id"] == bet["id"]
    assert store.get_diamond_balance("h1", now=MONDAY) == 1000

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
    assert store.get_diamond_balance("h1", now=MONDAY) == 1000


def test_free_stake_debits_only_paid_portion(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    expected = {
        "free-20": (20, 20, 0, 1000),
        "paid-40": (40, 20, 20, 980),
        "paid-60": (60, 20, 40, 960),
    }
    for player_id, (stake, _, _, _) in expected.items():
        make_rival_pair(store, player_id, f"{player_id}-rival")

    for player_id, (stake, free_stake, paid_stake, balance) in expected.items():
        bet = store.place_bet(
            player_id,
            "weekly",
            stake,
            None,
            now=MONDAY,
            request_id=f"{player_id}-bet",
        )
        assert bet["stake"] == stake
        assert bet["free_stake"] == free_stake
        assert bet["paid_stake"] == paid_stake
        assert store.get_diamond_balance(player_id, now=MONDAY) == balance


def test_free_stake_allows_zero_balance_and_checks_paid_only(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "broke", "broke-rival")
    with store.transaction() as conn:
        conn.execute(
            "UPDATE diamond_balance SET balance = 0 WHERE player_id = ?",
            ("broke",),
        )
    free = store.place_bet(
        "broke", "weekly", 20, None, now=MONDAY, request_id="free"
    )
    assert free["paid_stake"] == 0
    assert store.get_diamond_balance("broke", now=MONDAY) == 0

    make_rival_pair(store, "thin", "thin-rival")
    with store.transaction() as conn:
        conn.execute(
            "UPDATE diamond_balance SET balance = 19 WHERE player_id = ?",
            ("thin",),
        )
    with pytest.raises(InsufficientDiamonds):
        store.place_bet(
            "thin", "weekly", 40, None, now=MONDAY, request_id="thin"
        )
    assert store.get_diamond_balance("thin", now=MONDAY) == 19


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
    assert bet["free_stake"] == 20
    assert bet["paid_stake"] == 0
    assert store.get_diamond_balance("h1", now=MONDAY_EVENING) == 1000

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
        == 1030
    )

    again = store.settle_daily_bets(
        "2026-11-02", now=datetime(2026, 11, 2, 22, 5, 0, tzinfo=TZ)
    )
    assert again["settled"] == 0
    assert (
        store.get_diamond_balance(
            "h1", now=datetime(2026, 11, 2, 22, 5, 0, tzinfo=TZ)
        )
        == 1030
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
        == 1000
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
        == 1000
    )

    make_rival_pair(store, "weekly", "weekly-rival")
    set_week_xp(store, "weekly", 200)
    set_week_xp(store, "weekly-rival", 200)
    store.place_bet(
        "weekly", "weekly", 40, None, now=MONDAY, request_id="weekly-draw"
    )
    settled = store.settle_weekly_bets(WEEK, now=NEXT_MONDAY)
    assert settled["settled"] == 1
    assert settled["results"][0]["status"] == "void"
    assert settled["results"][0]["free_stake"] == 20
    assert settled["results"][0]["paid_stake"] == 20
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
        "winner", "weekly", 40, None, now=MONDAY, request_id="weekly-win"
    )
    store.place_bet(
        "loser", "weekly", 60, None, now=MONDAY, request_id="weekly-loss"
    )

    early = store.settle_weekly_bets(WEEK, now=MONDAY)
    assert early["status"] == "skipped"

    settled = store.settle_weekly_bets(WEEK, now=NEXT_MONDAY)
    assert settled["settled"] == 2
    by_rival = {row["rival_id"]: row for row in settled["results"]}
    assert by_rival["winner-rival"]["status"] == "won"
    assert by_rival["winner-rival"]["payout"] == 80
    assert by_rival["loser-rival"]["status"] == "lost"
    assert by_rival["loser-rival"]["payout"] == 0
    assert store.get_diamond_balance("winner", now=NEXT_MONDAY) == 1060
    assert store.get_diamond_balance("loser", now=NEXT_MONDAY) == 960

    again = store.settle_weekly_bets(WEEK, now=NEXT_MONDAY)
    assert again["settled"] == 0
    assert store.get_diamond_balance("winner", now=NEXT_MONDAY) == 1060


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
    assert settled["group_bets"]["settled"] == 0
    assert store.get_diamond_balance("h1", now=NEXT_MONDAY) == 1160

    again = store.settle_week(WEEK, now=NEXT_MONDAY)
    assert again["already_settled"] is True
    assert store.get_diamond_balance("h1", now=NEXT_MONDAY) == 1160
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


def test_bets_migration_backfills_legacy_rows(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            period_key TEXT NOT NULL,
            rival_id TEXT NOT NULL,
            stake INTEGER NOT NULL,
            target_margin INTEGER NOT NULL DEFAULT 0,
            odds REAL NOT NULL,
            status TEXT NOT NULL,
            placed_at TEXT NOT NULL,
            locked_at TEXT,
            settled_at TEXT,
            payout INTEGER NOT NULL DEFAULT 0,
            result_diff INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE,
            UNIQUE (player_id, kind, period_key)
        );
        """
    )
    conn.execute(
        "INSERT INTO bets "
        "(player_id, kind, period_key, rival_id, stake, odds, status, "
        "placed_at, idempotency_key) "
        "VALUES ('legacy', 'weekly', '2026-10-26', 'rival', 40, 2.0, "
        "'placed', '2026-10-26T12:00:00+08:00', 'legacy-key')"
    )
    conn.commit()
    conn.close()

    store = GameStore(path, epoch_reason="test")
    with store.transaction() as tx:
        row = tx.execute("SELECT * FROM bets WHERE player_id = 'legacy'").fetchone()
    assert int(row["free_stake"]) == 0
    assert int(row["paid_stake"]) == 40
    assert store.table_counts()["group_bets"] == 0


def test_group_bet_places_once_with_free_stake(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1")
    add_player(store, "h2")
    add_player(store, "grouped")
    add_player(store, "late")
    add_player(store, "solo")
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["h2"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["grouped"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["late"], now=MONDAY)

    with pytest.raises(BetRejected):
        store.place_bet(
            "h1", "group", None, None, now=MONDAY, request_id="missing-stake"
        )
    with pytest.raises(BetRejected):
        store.place_bet(
            "h1", "group", 30, None, now=MONDAY, request_id="bad-stake"
        )
    with pytest.raises(BetRejected):
        store.place_bet(
            "h1",
            "group",
            20,
            50,
            now=MONDAY,
            request_id="bad-target",
        )

    bet = store.place_bet(
        "grouped", "group", 40, None, now=MONDAY, request_id="group-1"
    )
    assert bet["kind"] == "group"
    assert bet["stake"] == 40
    assert bet["free_stake"] == 20
    assert bet["paid_stake"] == 20
    assert bet["odds"] == 2.0
    assert bet["status"] == "placed"
    assert bet["group_id"] == store.group_for_player("grouped", WEEK)["id"]
    assert store.get_diamond_balance("grouped", now=MONDAY) == 980

    repeat = store.place_bet(
        "grouped", "group", 40, None, now=MONDAY, request_id="group-1"
    )
    assert repeat["id"] == bet["id"]
    assert store.get_diamond_balance("grouped", now=MONDAY) == 980
    with pytest.raises(BetAlreadyPlaced):
        store.place_bet(
            "grouped", "group", 20, None, now=MONDAY, request_id="group-2"
        )

    with pytest.raises(BetRejected) as no_group:
        store.place_bet(
            "solo", "group", 20, None, now=MONDAY, request_id="no-group"
        )
    assert no_group.value.code == "no_group"

    with pytest.raises(BetWindowClosed):
        store.place_bet(
            "late", "group", 20, None, now=TUESDAY, request_id="group-late"
        )
    assert store.get_diamond_balance("late", now=TUESDAY) == 1000


def test_group_bet_ranks_top_three_with_deterministic_ties(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    for player_id in ("g1a", "g1b", "g2", "g3", "g4"):
        add_player(store, player_id)
    group1 = store.create_group(
        WEEK, tier="Bronze", player_ids=["g1a", "g1b"], now=MONDAY
    )
    group2 = store.create_group(
        WEEK, tier="Bronze", player_ids=["g2"], now=MONDAY
    )
    group3 = store.create_group(
        WEEK, tier="Bronze", player_ids=["g3"], now=MONDAY
    )
    group4 = store.create_group(
        WEEK, tier="Bronze", player_ids=["g4"], now=MONDAY
    )
    set_week_xp(store, "g1a", 300)
    set_week_xp(store, "g1b", 100)
    set_week_xp(store, "g2", 300)
    set_week_xp(store, "g3", 300)
    set_week_xp(store, "g4", 100)

    store.place_bet(
        "g1a", "group", 20, None, now=MONDAY, request_id="g1"
    )
    store.place_bet(
        "g2", "group", 40, None, now=MONDAY, request_id="g2"
    )
    store.place_bet(
        "g3", "group", 60, None, now=MONDAY, request_id="g3"
    )
    store.place_bet(
        "g4", "group", 20, None, now=MONDAY, request_id="g4"
    )

    settled = store.settle_group_bets(WEEK, now=NEXT_MONDAY)
    assert settled["settled"] == 4
    by_group = {
        row["group_id"]: row for row in settled["results"]
    }
    assert by_group[group1["id"]]["group_rank"] == 1
    assert by_group[group2["id"]]["group_rank"] == 2
    assert by_group[group3["id"]]["group_rank"] == 3
    assert by_group[group4["id"]]["group_rank"] == 4
    assert by_group[group1["id"]]["status"] == "won"
    assert by_group[group2["id"]]["status"] == "won"
    assert by_group[group3["id"]]["status"] == "won"
    assert by_group[group4["id"]]["status"] == "lost"
    assert by_group[group1["id"]]["payout"] == 40
    assert by_group[group2["id"]]["payout"] == 80
    assert by_group[group3["id"]]["payout"] == 120
    assert store.get_diamond_balance("g1a", now=NEXT_MONDAY) == 1040
    assert store.get_diamond_balance("g2", now=NEXT_MONDAY) == 1060
    assert store.get_diamond_balance("g3", now=NEXT_MONDAY) == 1080
    assert store.get_diamond_balance("g4", now=NEXT_MONDAY) == 1000

    again = store.settle_group_bets(WEEK, now=NEXT_MONDAY)
    assert again["settled"] == 0
    assert store.get_diamond_balance("g3", now=NEXT_MONDAY) == 1080
    rewards = [
        row
        for row in store.diamond_ledger("g3")
        if row["reason"] == "group_bet_payout"
    ]
    assert len(rewards) == 1


def test_group_bet_waits_for_0005_and_voids_missing_group(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    add_player(store, "void")
    group = store.create_group(
        WEEK, tier="Bronze", player_ids=["void"], now=MONDAY
    )
    store.place_bet(
        "void", "group", 40, None, now=MONDAY, request_id="void"
    )
    assert store.get_diamond_balance("void", now=MONDAY) == 980

    early = store.settle_group_bets(
        WEEK, now=datetime(2026, 11, 9, 0, 4, 59, tzinfo=TZ)
    )
    assert early["status"] == "skipped"

    with store.transaction() as conn:
        conn.execute("DELETE FROM groups WHERE id = ?", (group["id"],))
    settled = store.settle_group_bets(WEEK, now=NEXT_MONDAY)
    assert settled["settled"] == 1
    row = settled["results"][0]
    assert row["status"] == "void"
    assert row["group_rank"] is None
    assert row["payout"] == 20
    assert store.get_diamond_balance("void", now=NEXT_MONDAY) == 1000

    again = store.settle_group_bets(WEEK, now=NEXT_MONDAY)
    assert again["settled"] == 0
    assert store.get_diamond_balance("void", now=NEXT_MONDAY) == 1000


def test_settle_week_settles_group_bets_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_rival_pair(store, "h1", "h2")
    add_activity(
        store,
        "h1",
        event_id="h1-group-week",
        seconds=1800,
        occurred_at=datetime(2026, 11, 6, 12, 0, 0, tzinfo=TZ),
    )
    add_activity(
        store,
        "h2",
        event_id="h2-group-week",
        seconds=600,
        occurred_at=datetime(2026, 11, 6, 12, 0, 0, tzinfo=TZ),
    )
    store.place_bet(
        "h1", "group", 40, None, now=MONDAY, request_id="group-integration"
    )
    assert store.get_diamond_balance("h1", now=MONDAY) == 980

    settled = store.settle_week(WEEK, now=NEXT_MONDAY)
    assert settled["group_bets"]["settled"] == 1
    assert settled["group_bets"]["results"][0]["status"] == "won"
    assert settled["group_bets"]["results"][0]["payout"] == 80
    assert store.get_diamond_balance("h1", now=NEXT_MONDAY) == 1180

    again = store.settle_week(WEEK, now=NEXT_MONDAY)
    assert again["group_bets"]["settled"] == 0
    assert store.get_diamond_balance("h1", now=NEXT_MONDAY) == 1180
