from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ghost_league.game.rival import (
    DAILY_EXPECTED_XP_STEP,
    DAILY_ODDS_AXIS,
    DAILY_POWER_SIGMA_FLOOR,
    DAILY_POWER_SIGMA_RATIO,
    RivalNotFound,
    RivalSelectionRejected,
    RivalWindowClosed,
    daily_margin_for_odds,
    daily_power_distribution,
    daily_target_margins,
    daily_target_options,
    round_to_step,
)
from ghost_league.game.store import GameStore
from ghost_league.schedule import TZ

WEEK = "2026-11-02"
PREVIOUS_WEEK = "2026-10-26"
MONDAY = datetime(2026, 11, 2, 12, 0, 0, tzinfo=TZ)
TUESDAY = datetime(2026, 11, 3, 0, 0, 0, tzinfo=TZ)
NEXT_MONDAY = datetime(2026, 11, 9, 0, 5, 0, tzinfo=TZ)


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def add_player(
    store: GameStore,
    player_id: str,
    *,
    kind: str = "human",
    power: int | None = None,
    week: str = WEEK,
) -> str:
    store.create_player(
        player_id,
        kind=kind,
        display_name=player_id,
        joined_week=week,
        now=MONDAY,
    )
    if power is not None:
        set_power(store, player_id, power)
    return player_id


def set_power(store: GameStore, player_id: str, power: int) -> None:
    with store.transaction() as conn:
        conn.execute(
            "UPDATE players SET power = ? WHERE id = ?", (power, player_id)
        )


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


def seed_assignment(
    store: GameStore,
    player_id: str,
    rival_id: str,
    *,
    week: str,
    mode: str = "manual",
    locked: bool = False,
) -> None:
    stamp = f"{week}T12:00:00+08:00"
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO rival_assignments "
            "(week_start, player_id, rival_id, selection_mode, selected_at, "
            "locked_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                week,
                player_id,
                rival_id,
                mode,
                stamp,
                stamp if locked else None,
                stamp,
                stamp,
            ),
        )


def test_monday_candidates_and_manual_change(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "h2", power=600)
    add_player(store, "h3", power=900)
    add_player(store, "ai-close", kind="ai", power=700)
    store.create_group(
        WEEK, tier="Bronze", player_ids=["h1", "ai-close"], now=MONDAY
    )
    store.create_group(WEEK, tier="Bronze", player_ids=["h2", "h3"], now=MONDAY)
    for player_id in ("h1", "h2", "h3", "ai-close"):
        set_week_xp(store, player_id, 100)

    candidates = store.rival_candidates("h1", now=MONDAY)
    assert [row["user_id"] for row in candidates] == ["h2", "h3"]
    assert set(candidates[0]) == {
        "user_id",
        "display_name",
        "group_no",
        "tier",
        "power",
        "week_xp",
        "today_xp",
    }

    state = store.rival_state("h1", now=MONDAY)
    assert state["selection"]["open"] is True
    assert state["selection"]["mode"] is None
    assert state["rival"] is None
    assert state["me"]["power"] == 500
    assert state["me"]["week_xp"] == 100

    first = store.select_rival(
        "h1", "h2", now=MONDAY, request_id="select-1"
    )
    assert first["assignment"]["selection_mode"] == "manual"
    state = store.rival_state("h1", now=MONDAY)
    assert state["selection"]["open"] is True
    assert state["selection"]["mode"] == "manual"
    assert state["rival"]["user_id"] == "h2"

    store.select_rival("h1", "h3", now=MONDAY, request_id="select-2")
    state = store.rival_state("h1", now=MONDAY)
    assert state["rival"]["user_id"] == "h3"

    with pytest.raises(RivalWindowClosed):
        store.select_rival("h1", "h2", now=TUESDAY, request_id="select-3")

    locked_state = store.rival_state("h1", now=TUESDAY)
    assert locked_state["selection"]["open"] is False
    assert locked_state["selection"]["mode"] == "manual"
    assert locked_state["selection"]["locks_at"] == (
        "2026-11-02T23:59:59+08:00"
    )
    assert locked_state["selection"]["auto_select_at"] == (
        "2026-11-03T00:00:00+08:00"
    )


def test_selection_rejects_self_same_group_and_unknown(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "same", power=600)
    add_player(store, "other", power=700)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1", "same"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["other"], now=MONDAY)
    for player_id in ("h1", "same", "other"):
        set_week_xp(store, player_id, 100)

    with pytest.raises(RivalSelectionRejected):
        store.select_rival("h1", "h1", now=MONDAY, request_id="self")
    with pytest.raises(RivalNotFound):
        store.select_rival("h1", "same", now=MONDAY, request_id="same-group")
    with pytest.raises(RivalNotFound):
        store.select_rival("h1", "missing", now=MONDAY, request_id="missing")
    assert store.rival_state("h1", now=MONDAY)["rival"] is None


def test_auto_select_prefers_power_band_and_is_deterministic(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "below", power=550)
    add_player(store, "band", power=600)
    add_player(store, "far", power=900)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(
        WEEK, tier="Bronze", player_ids=["below", "band", "far"], now=MONDAY
    )
    for player_id in ("h1", "below", "band", "far"):
        set_week_xp(store, player_id, 100)

    early = store.auto_assign_rivals(WEEK, now=MONDAY)
    assert early["status"] == "skipped"
    assert store.rival_state("h1", now=MONDAY)["rival"] is None

    first = store.auto_assign_rivals(WEEK, now=TUESDAY)
    assert first["assigned"] >= 1
    assignment = store.rival_state("h1", now=TUESDAY)
    assert assignment["rival"]["user_id"] == "band"
    assert assignment["selection"]["mode"] == "auto"
    assert assignment["selection"]["open"] is False

    second = store.auto_assign_rivals(WEEK, now=TUESDAY)
    assert second["assigned"] == 0
    assert second["already"] >= 1
    assert store.rival_state("h1", now=TUESDAY)["rival"]["user_id"] == "band"


def test_auto_select_avoids_previous_rival_when_possible(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "previous", power=600)
    add_player(store, "fresh", power=700)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(
        WEEK, tier="Bronze", player_ids=["previous", "fresh"], now=MONDAY
    )
    for player_id in ("h1", "previous", "fresh"):
        set_week_xp(store, player_id, 100)
    seed_assignment(
        store,
        "h1",
        "previous",
        week=PREVIOUS_WEEK,
        mode="manual",
        locked=True,
    )

    result = store.auto_assign_rivals(WEEK, now=TUESDAY)
    assert result["assigned"] >= 1
    assert store.rival_state("h1", now=TUESDAY)["rival"]["user_id"] == "fresh"


def test_auto_select_fallback_when_no_band_candidate(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "higher", power=900)
    add_player(store, "lower", power=100)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(
        WEEK, tier="Bronze", player_ids=["higher", "lower"], now=MONDAY
    )
    for player_id in ("h1", "higher", "lower"):
        set_week_xp(store, player_id, 100)

    result = store.auto_assign_rivals(WEEK, now=TUESDAY)
    assert result["assigned"] >= 1
    assert store.rival_state("h1", now=TUESDAY)["rival"]["user_id"] == "higher"


def test_auto_select_leaves_player_without_candidate(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "solo", power=500)
    store.create_group(WEEK, tier="Bronze", player_ids=["solo"], now=MONDAY)
    set_week_xp(store, "solo", 100)

    result = store.auto_assign_rivals(WEEK, now=TUESDAY)
    assert result["assigned"] == 0
    assert result["no_candidate"] == 1
    no_rival = store.rival_state("solo", now=TUESDAY)
    assert no_rival["rival"] is None
    assert no_rival["selection"]["open"] is False


def test_auto_select_falls_back_to_any_candidate(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "lower", power=100)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["lower"], now=MONDAY)
    for player_id in ("h1", "lower"):
        set_week_xp(store, player_id, 100)

    store.auto_assign_rivals(WEEK, now=TUESDAY)
    assert store.rival_state("h1", now=TUESDAY)["rival"]["user_id"] == "lower"


def test_settle_rivals_rewards_once_per_outcome(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    for player_id in ("win", "loss", "draw", "rival-a", "rival-b", "rival-c"):
        add_player(store, player_id)
    store.create_group(
        WEEK, tier="Bronze", player_ids=["win", "loss", "draw"], now=MONDAY
    )
    store.create_group(
        WEEK,
        tier="Bronze",
        player_ids=["rival-a", "rival-b", "rival-c"],
        now=MONDAY,
    )
    seed_assignment(store, "win", "rival-a", week=WEEK, locked=True)
    seed_assignment(store, "loss", "rival-b", week=WEEK, locked=True)
    seed_assignment(store, "draw", "rival-c", week=WEEK, locked=True)
    set_week_xp(store, "win", 500)
    set_week_xp(store, "rival-a", 300)
    set_week_xp(store, "loss", 100)
    set_week_xp(store, "rival-b", 300)
    set_week_xp(store, "draw", 200)
    set_week_xp(store, "rival-c", 200)

    early = store.settle_rivals(WEEK, now=MONDAY)
    assert early["status"] == "skipped"

    settled = store.settle_rivals(WEEK, now=NEXT_MONDAY)
    assert settled["status"] == "settled"
    outcomes = {
        row["rival_id"]: (row["outcome"], row["reward_diamonds"])
        for row in settled["results"]
    }
    assert outcomes == {
        "rival-a": ("win", 120),
        "rival-b": ("loss", 0),
        "rival-c": ("draw", 40),
    }
    assert store.get_diamond_balance("win", now=NEXT_MONDAY) == 1120
    assert store.get_diamond_balance("loss", now=NEXT_MONDAY) == 1000
    assert store.get_diamond_balance("draw", now=NEXT_MONDAY) == 1040

    again = store.settle_rivals(WEEK, now=NEXT_MONDAY)
    assert again["settled"] == 0
    assert store.get_diamond_balance("win", now=NEXT_MONDAY) == 1120
    rewards = [
        row
        for row in store.diamond_ledger("win")
        if row["reason"] == "rival_reward"
    ]
    assert len(rewards) == 1
    state = store.rival_state("win", now=NEXT_MONDAY)
    assert state["result"]["outcome"] == "win"
    assert state["result"]["reward_diamonds"] == 120


def test_projection_uses_settled_week_and_power_daily_distribution(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "rival", power=1000)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["rival"], now=MONDAY)
    set_week_xp(store, "h1", 100)
    set_week_xp(store, "rival", 100)
    store.select_rival("h1", "rival", now=MONDAY, request_id="projection")
    store.ensure_week(PREVIOUS_WEEK, status="settled")
    for index, xp in enumerate((100, 200, 300, 400, 500), start=1):
        set_week_xp(
            store, f"past-{index}", xp, week=PREVIOUS_WEEK
        )

    at = datetime(2026, 11, 2, 22, 30, 0, tzinfo=TZ)
    store.ingest_activity(
        "rival",
        event_id="rival-today",
        seconds=600,
        occurred_at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ),
        source="local_increment",
        now=at,
    )
    state = store.rival_state("h1", now=at)
    assert state["bets"]["group"] is None
    projection = state["projection"]
    assert projection["rival_week_estimate"] == 300
    assert projection["weekly_target_max"] == 600
    assert "rival_today_estimate" not in projection
    assert "daily_target_max" not in projection
    # The daily line is pure power: mu is the player's power and sigma scales
    # from it.  No check-in history is required or read.
    assert projection["daily_mu_me"] == 500.0
    assert projection["daily_sd_me"] == 500.0
    assert projection["daily_mu_rival"] == 1000.0
    assert projection["daily_sd_rival"] == 1000.0
    assert projection["daily_mu_diff"] == -500.0
    assert projection["daily_sigma_diff"] == 1118.03

    weekly_options = state["bet_options"]["weekly"]
    daily_options = state["bet_options"]["daily"]
    assert weekly_options["min_paid_stake"] == 0
    assert weekly_options["max_paid_stake"] == 500
    assert weekly_options["free_stake"] == 20
    assert weekly_options["target_options"][0] == {
        "margin": 0,
        "odds": 1.2,
    }
    assert weekly_options["target_options"][-1]["margin"] == 600
    assert daily_options["max_paid_stake"] == 100
    assert daily_options["min_target_margin"] == 1
    assert daily_options["max_target_margin"] == 441
    assert [entry["odds"] for entry in daily_options["target_options"]] == [
        2.0,
        3.0,
        4.0,
        5.0,
    ]
    assert [
        entry["margin"] for entry in daily_options["target_options"]
    ] == projection["daily_target_margins"] == [1, 2, 255, 441]
    assert [
        entry["expected_xp"] for entry in daily_options["target_options"]
    ] == [
        round_to_step(projection["daily_mu_rival"] + margin, 10)
        for margin in projection["daily_target_margins"]
    ]
    assert [
        entry["expected_xp"] for entry in daily_options["target_options"]
    ] == [1000, 1000, 1260, 1440]


def test_projection_falls_back_without_settled_week(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "rival", power=1500)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["rival"], now=MONDAY)
    set_week_xp(store, "h1", 100)
    set_week_xp(store, "rival", 123)
    store.select_rival("h1", "rival", now=MONDAY, request_id="fallback")

    state = store.rival_state("h1", now=MONDAY)
    projection = state["projection"]
    assert projection["rival_week_estimate"] == 100
    assert projection["weekly_target_max"] == 200
    assert projection["daily_mu_me"] == 500.0
    assert projection["daily_sd_me"] == 500.0
    assert projection["daily_mu_rival"] == 1500.0
    assert projection["daily_sd_rival"] == 1500.0
    assert projection["daily_mu_diff"] == -1000.0
    assert projection["daily_sigma_diff"] == 1581.14
    assert projection["daily_target_margins"] == [1, 2, 67, 331]


def test_daily_pricing_is_pure_power_without_checkins(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=800)
    add_player(store, "rival", power=600)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["rival"], now=MONDAY)
    set_week_xp(store, "h1", 100)
    set_week_xp(store, "rival", 100)
    store.select_rival("h1", "rival", now=MONDAY, request_id="pure-power")

    state = store.rival_state("h1", now=MONDAY)
    projection = state["projection"]
    assert projection["daily_mu_me"] == 800.0
    assert projection["daily_mu_rival"] == 600.0
    assert projection["daily_mu_diff"] == 200.0
    assert projection["daily_sd_me"] == 800.0
    assert projection["daily_sd_rival"] == 600.0
    assert projection["daily_sigma_diff"] == 1000.0

    options = state["bet_options"]["daily"]["target_options"]
    assert [entry["odds"] for entry in options] == list(DAILY_ODDS_AXIS)
    assert [entry["odds"] for entry in options] == [2.0, 3.0, 4.0, 5.0]
    margins = [entry["margin"] for entry in options]
    assert margins == projection["daily_target_margins"] == [200, 631, 875, 1042]
    assert margins == sorted(set(margins))
    assert all(margin > 0 for margin in margins)
    assert [entry["expected_xp"] for entry in options] == [
        round_to_step(projection["daily_mu_rival"] + margin, 10)
        for margin in margins
    ]


def test_daily_power_sigma_uses_the_configured_ratio_and_floor() -> None:
    assert DAILY_POWER_SIGMA_RATIO == 1.0
    assert DAILY_POWER_SIGMA_FLOOR == 120
    assert daily_power_distribution(-10, 0) == (0.0, 120.0, 0.0, 120.0)
    assert daily_power_distribution(80, 200) == (80.0, 120.0, 200.0, 200.0)
    assert daily_power_distribution(800, 600) == (800.0, 800.0, 600.0, 600.0)


def test_daily_odds_axis_inverts_margins_and_previews_total_xp() -> None:
    mu_me, sd_me, mu_rival, sd_rival = 850.0, 100.0, 500.0, 100.0
    options = daily_target_options(mu_me, sd_me, mu_rival, sd_rival)
    assert [entry["odds"] for entry in options] == list(DAILY_ODDS_AXIS)
    assert [entry["odds"] for entry in options] == [2.0, 3.0, 4.0, 5.0]

    mu_diff, sigma_diff = 350.0, (100.0**2 + 100.0**2) ** 0.5
    assert [entry["margin"] for entry in options] == [
        daily_margin_for_odds(odds, mu_diff, sigma_diff)
        for odds in DAILY_ODDS_AXIS
    ]
    assert [entry["margin"] for entry in options] == [350, 411, 446, 470]
    margins = [entry["margin"] for entry in options]
    assert margins == sorted(set(margins))
    assert all(margin > 0 for margin in margins)
    assert [entry["expected_xp"] for entry in options] == [
        round_to_step(mu_rival + margin, DAILY_EXPECTED_XP_STEP)
        for margin in margins
    ]
    assert daily_target_margins(
        mu_me, sd_me, mu_rival, sd_rival
    ) == margins


def test_daily_odds_axis_stays_unique_for_a_degenerate_spread() -> None:
    options = daily_target_options(100, 0, 100, 0)
    assert [entry["odds"] for entry in options] == [2.0, 3.0, 4.0, 5.0]
    # The exact formula maps every price to 1 XP here; the display guard bumps
    # duplicates so each price remains selectable and ordered.
    assert [entry["margin"] for entry in options] == [1, 2, 3, 4]


def test_daily_lines_do_not_drift_with_live_xp(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "rival", power=1000)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["rival"], now=MONDAY)
    set_week_xp(store, "h1", 100)
    set_week_xp(store, "rival", 100)
    store.select_rival("h1", "rival", now=MONDAY, request_id="stable-daily")
    store.ensure_week(PREVIOUS_WEEK, status="settled")
    for index, xp in enumerate((100, 200, 300, 400, 500), start=1):
        set_week_xp(store, f"past-{index}", xp, week=PREVIOUS_WEEK)

    morning = datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ)
    evening = datetime(2026, 11, 2, 21, 0, 0, tzinfo=TZ)
    store.ingest_activity(
        "rival",
        event_id="rival-morning",
        seconds=600,
        occurred_at=morning,
        source="local_increment",
        now=morning,
    )
    morning_state = store.rival_state("h1", now=morning)
    store.ingest_activity(
        "rival",
        event_id="rival-evening",
        seconds=1800,
        occurred_at=evening,
        source="local_increment",
        now=evening,
    )
    evening_state = store.rival_state("h1", now=evening)

    assert evening_state["rival"]["today_xp"] > morning_state["rival"]["today_xp"]
    assert evening_state["projection"] == morning_state["projection"]
    morning_daily = morning_state["bet_options"]["daily"]
    evening_daily = evening_state["bet_options"]["daily"]
    assert evening_daily == morning_daily
    assert [
        (entry["margin"], entry["odds"])
        for entry in evening_daily["target_options"]
    ] == [
        (entry["margin"], entry["odds"])
        for entry in morning_daily["target_options"]
    ]
