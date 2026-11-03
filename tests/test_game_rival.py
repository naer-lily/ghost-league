from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ghost_league.game.rival import (
    DAILY_PRIOR_MEAN_XP,
    DAILY_PRIOR_SD_XP,
    DAILY_TARGET_STEP,
    RivalNotFound,
    RivalSelectionRejected,
    RivalWindowClosed,
    band_distribution,
    daily_bet_odds,
    daily_target_margins,
    daily_target_options,
    power_band,
    round_to_step,
    sample_mean_sd,
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


def add_checkin_history(
    store: GameStore,
    player_id: str,
    xps: list[int],
    *,
    end_day: date = date(2026, 10, 31),
) -> None:
    with store.transaction() as conn:
        for offset, xp in enumerate(xps):
            day = end_day - timedelta(days=len(xps) - 1 - offset)
            stamp = f"{day.isoformat()}T12:00:00+08:00"
            conn.execute(
                "INSERT OR REPLACE INTO checkins "
                "(player_id, date, source, seconds, xp, checked_at, "
                "repaired_at, repair_cost, status, created_at) "
                "VALUES (?, ?, 'verified', ?, ?, ?, NULL, 0, 'verified', ?)",
                (
                    player_id,
                    day.isoformat(),
                    xp * 6,
                    xp,
                    stamp,
                    int(datetime.fromisoformat(stamp).timestamp()),
                ),
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


def test_projection_uses_settled_week_and_daily_distribution(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "rival", power=1000)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["rival"], now=MONDAY)
    set_week_xp(store, "h1", 100)
    set_week_xp(store, "rival", 100)
    add_checkin_history(store, "h1", [100, 200, 300])
    add_checkin_history(store, "rival", [400, 500, 600])
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
    # The two players are the only samples, so both fall back to the same
    # global mean/sample-std until each band has 20 players.
    assert projection["daily_mu_me"] == 350.0
    assert projection["daily_sd_me"] == 212.13
    assert projection["daily_mu_rival"] == 350.0
    assert projection["daily_sd_rival"] == 212.13
    assert projection["daily_mu_diff"] == 0.0
    assert projection["daily_sigma_diff"] == 300.0
    assert projection["daily_target_margins"] == [1, 150, 300, 450]

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
    assert daily_options["min_target_margin"] == 1
    assert daily_options["max_target_margin"] == 450
    assert [
        entry["margin"] for entry in daily_options["target_options"]
    ] == projection["daily_target_margins"]
    assert [entry["odds"] for entry in daily_options["target_options"]] == [
        daily_bet_odds(1, 0.0, 300.0),
        daily_bet_odds(150, 0.0, 300.0),
        daily_bet_odds(300, 0.0, 300.0),
        daily_bet_odds(450, 0.0, 300.0),
    ]
    assert [
        entry["expected_xp"] for entry in daily_options["target_options"]
    ] == [
        round_to_step(projection["daily_mu_rival"] + margin, 10)
        for margin in projection["daily_target_margins"]
    ]
    assert [
        entry["expected_xp"] for entry in daily_options["target_options"]
    ] == [350, 500, 650, 800]


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
    assert projection["daily_mu_me"] == DAILY_PRIOR_MEAN_XP
    assert projection["daily_sd_me"] == DAILY_PRIOR_SD_XP
    assert projection["daily_mu_rival"] == DAILY_PRIOR_MEAN_XP
    assert projection["daily_sd_rival"] == DAILY_PRIOR_SD_XP
    assert projection["daily_mu_diff"] == 0.0
    assert projection["daily_sigma_diff"] == 212.13
    assert projection["daily_target_margins"] == [1, 150, 300, 450]


def test_daily_history_ignores_today_and_short_players(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_player(store, "h1", power=500)
    add_player(store, "rival", power=1000)
    store.create_group(WEEK, tier="Bronze", player_ids=["h1"], now=MONDAY)
    store.create_group(WEEK, tier="Bronze", player_ids=["rival"], now=MONDAY)
    set_week_xp(store, "h1", 100)
    set_week_xp(store, "rival", 100)
    # h1 qualifies with three completed days; today's huge value is ignored.
    add_checkin_history(store, "h1", [100, 200, 300])
    add_checkin_history(
        store, "h1", [9999], end_day=MONDAY.date()
    )
    # A day older than the 28-day window is ignored too.
    add_checkin_history(
        store, "h1", [9999], end_day=date(2026, 9, 20)
    )
    # This rival has only two recorded days, so it is not a sample at all.
    add_checkin_history(store, "rival", [1000, 2000])
    store.select_rival("h1", "rival", now=MONDAY, request_id="history")

    projection = store.rival_state("h1", now=MONDAY)["projection"]
    assert projection["daily_mu_me"] == 200.0
    assert projection["daily_sd_me"] == 0.0
    assert projection["daily_mu_rival"] == 200.0
    assert projection["daily_sd_rival"] == 0.0
    assert projection["daily_sigma_diff"] == 0.0
    assert projection["daily_target_margins"] == [1, 150, 300]


def test_power_band_uses_250_width() -> None:
    assert power_band(0) == 0
    assert power_band(249) == 0
    assert power_band(250) == 1
    assert power_band(499) == 1
    assert power_band(500) == 2
    assert power_band(749) == 2
    assert power_band(750) == 3


def test_band_distribution_uses_its_band_then_neighbours_then_all() -> None:
    same_band = [(100, 100.0), (120, 200.0), (140, 300.0)]
    assert band_distribution(
        same_band, 500, min_samples=3
    ) == sample_mean_sd([100.0, 200.0, 300.0])

    split = [
        (500, 100.0),
        (520, 200.0),
        (800, 1000.0),
        (820, 1100.0),
    ]
    low = band_distribution(split, 500, min_samples=2)
    high = band_distribution(split, 800, min_samples=2)
    assert low == sample_mean_sd([100.0, 200.0])
    assert high == sample_mean_sd([1000.0, 1100.0])
    assert low != high

    exact = [(500, 10.0)]
    adjacent = [(300, 20.0), (750, 30.0)]
    assert band_distribution(
        exact + adjacent, 500, min_samples=3
    ) == sample_mean_sd([10.0, 20.0, 30.0])

    far = [(500, 10.0), (2000, 99.0)]
    assert band_distribution(
        far, 500, min_samples=3
    ) == sample_mean_sd([10.0, 99.0])


def test_band_distribution_prior_without_any_history() -> None:
    assert band_distribution([], 500) == (
        DAILY_PRIOR_MEAN_XP,
        DAILY_PRIOR_SD_XP,
    )


def test_daily_targets_are_positive_stepped_and_at_least_three() -> None:
    cases = [
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 150.0, 0.0, 150.0),
        (850.0, 100.0, 500.0, 100.0),
        (0.0, 100.0, 400.0, 100.0),
        (5000.0, 600.0, 100.0, 50.0),
    ]
    for mu_me, sd_me, mu_rival, sd_rival in cases:
        margins = daily_target_margins(
            mu_me, sd_me, mu_rival, sd_rival
        )
        assert 3 <= len(margins) <= 6
        assert margins == sorted(set(margins))
        assert all(margin > 0 for margin in margins)
        assert margins[0] == 1
        assert all(
            margin == 1 or margin % DAILY_TARGET_STEP == 0
            for margin in margins
        )

    # A 350-point expected lead fills every 15-minute tier up to the
    # quantile ceiling, plus the narrow-win 1 XP tier.
    assert daily_target_margins(850, 100, 500, 100) == [
        1,
        150,
        300,
        450,
        600,
        750,
    ]

    # When the quantile ceiling lies above the canonical 15-minute steps, the
    # ladder keeps the canonical low tiers and the quantile ceiling itself.
    strong = daily_target_margins(5000, 600, 100, 50)
    assert strong[:5] == [1, 150, 300, 450, 600]
    assert strong[-1] > 750
    assert strong[-1] % DAILY_TARGET_STEP == 0


def test_daily_target_options_match_odds_and_stay_monotonic() -> None:
    options = daily_target_options(850, 100, 500, 100)
    assert [entry["margin"] for entry in options] == [
        1,
        150,
        300,
        450,
        600,
        750,
    ]
    assert [entry["odds"] for entry in options] == [
        daily_bet_odds(1, 350, 141.42),
        daily_bet_odds(150, 350, 141.42),
        daily_bet_odds(300, 350, 141.42),
        daily_bet_odds(450, 350, 141.42),
        daily_bet_odds(600, 350, 141.42),
        daily_bet_odds(750, 350, 141.42),
    ]
    # Expected XP is the rival's daily mean plus the target gap, not my XP.
    assert [entry["expected_xp"] for entry in options] == [
        round_to_step(500 + margin, 10)
        for margin in (1, 150, 300, 450, 600, 750)
    ]
    assert [entry["expected_xp"] for entry in options] == [
        500,
        650,
        800,
        950,
        1100,
        1250,
    ]
    odds = [entry["odds"] for entry in options]
    assert odds == sorted(odds)
    assert odds[0] >= 1.2
    assert odds[-1] <= 15.0
    assert daily_bet_odds(350, 350, 100) == 2.0


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
