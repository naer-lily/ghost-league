from __future__ import annotations

import asyncio
import tempfile
import time as time_module
from datetime import datetime, time, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.game.rival import payout_for_win
from ghost_league.game.scheduler import (
    GhostScheduler,
    JobSlot,
    ScheduledTask,
    daily_slots,
    hourly_slots,
    weekly_slots,
)
from ghost_league.game.store import GameStore
from ghost_league.runtime_jobs import (
    JOB_DAILY_BETS,
    JOB_DIAMOND_DECAY,
    JOB_POWER,
    JOB_RIVAL_AUTO,
    JOB_SOURCE_FETCH,
    JOB_WAKA_ROSTER,
    JOB_WAKA_TICK,
    JOB_WEEKLY_SETTLE,
    build_scheduled_tasks,
)
from ghost_league.schedule import TZ

MONDAY = datetime(2026, 11, 2, 0, 6, 0, tzinfo=TZ)
TUESDAY = datetime(2026, 11, 3, 1, 0, 0, tzinfo=TZ)
WEDNESDAY = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TZ)
WEEK = "2026-11-02"


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def add_player(store: GameStore, player_id: str) -> None:
    store.create_player(
        player_id,
        display_name=player_id,
        joined_week=WEEK,
        now=datetime(2026, 11, 2, 8, 0, 0, tzinfo=TZ),
    )


def add_activity(
    store: GameStore,
    player_id: str,
    *,
    event_id: str,
    seconds: int,
    occurred_at: datetime,
) -> None:
    store.ingest_activity(
        player_id,
        event_id=event_id,
        seconds=seconds,
        occurred_at=occurred_at,
        source="local_increment",
        now=occurred_at,
    )


def make_daily_pair(
    store: GameStore,
    *,
    week: str = WEEK,
    monday: datetime = datetime(2026, 11, 2, 8, 0, 0, tzinfo=TZ),
) -> None:
    add_player(store, "h1")
    add_player(store, "h2")
    store.create_group(week, tier="Bronze", player_ids=["h1"], now=monday)
    store.create_group(week, tier="Bronze", player_ids=["h2"], now=monday)
    with store.transaction() as conn:
        conn.execute("UPDATE players SET power = 500 WHERE id = 'h1'")
        conn.execute("UPDATE players SET power = 700 WHERE id = 'h2'")
    store.select_rival("h1", "h2", now=monday, request_id=f"rival-{week}")


def all_fake_runners(calls: list[tuple[str, str]]) -> dict[str, object]:
    names = (
        JOB_WAKA_TICK,
        JOB_SOURCE_FETCH,
        JOB_WAKA_ROSTER,
        JOB_WEEKLY_SETTLE,
        JOB_RIVAL_AUTO,
        JOB_POWER,
        JOB_DIAMOND_DECAY,
    )
    runners: dict[str, object] = {}
    for name in names:

        def runner(now: datetime, slot: JobSlot, _name: str = name) -> dict:
            calls.append((_name, slot.period_key))
            return {"status": "ok"}

        runners[name] = runner
    return runners


def runtime_tasks(
    store: GameStore,
    tmp_path: Path,
    *,
    calls: list[tuple[str, str]] | None = None,
    keep_daily_real: bool = False,
) -> list[ScheduledTask]:
    runners = all_fake_runners(calls if calls is not None else [])
    if not keep_daily_real:
        runners[JOB_DAILY_BETS] = lambda now, slot: {"status": "ok"}
    return build_scheduled_tasks(
        store,
        cache_path=tmp_path / "cache.json",
        runners=runners,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Due-time rules
# ---------------------------------------------------------------------------
def test_hourly_slots_pick_only_the_latest_due_period() -> None:
    slots = hourly_slots(1)
    previous = slots(datetime(2026, 11, 2, 10, 0, 30, tzinfo=TZ))
    assert [slot.period_key for slot in previous] == [
        "2026-11-02T09:01:00+08:00"
    ]

    current = slots(datetime(2026, 11, 2, 10, 1, 0, tzinfo=TZ))
    assert [slot.period_key for slot in current] == [
        "2026-11-02T10:01:00+08:00"
    ]


def test_daily_slots_do_not_fire_before_1030() -> None:
    slots = daily_slots(time(10, 30), lookback_days=1)
    assert slots(datetime(2026, 11, 2, 10, 29, 59, tzinfo=TZ)) == []
    due = slots(datetime(2026, 11, 2, 10, 30, 0, tzinfo=TZ))
    assert [(slot.period_key, slot.due_at) for slot in due] == [
        (
            "2026-11-02",
            datetime(2026, 11, 2, 10, 30, 0, tzinfo=TZ),
        )
    ]


def test_weekly_slots_respect_the_catchup_window() -> None:
    source = weekly_slots(0, time(0, 2), same_day_only=True)
    assert source(datetime(2026, 11, 2, 0, 1, tzinfo=TZ)) == []
    assert source(datetime(2026, 11, 2, 0, 2, tzinfo=TZ))[0].period_key == WEEK
    assert source(datetime(2026, 11, 4, 12, 0, tzinfo=TZ)) == []

    settle = weekly_slots(0, time(0, 5))
    assert settle(datetime(2026, 11, 2, 0, 4, tzinfo=TZ)) == []
    assert settle(datetime(2026, 11, 2, 0, 5, tzinfo=TZ))[0].period_key == WEEK
    assert settle(WEDNESDAY)[0].period_key == WEEK

    rival = weekly_slots(1, time(0, 0))
    assert rival(MONDAY) == []
    assert rival(TUESDAY)[0].period_key == WEEK


# ---------------------------------------------------------------------------
# Claim / idempotency / retry
# ---------------------------------------------------------------------------
def test_scheduler_runs_each_period_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    calls: list[str] = []

    def run(now: datetime, slot: JobSlot) -> dict:
        calls.append(slot.period_key)
        return {"status": "ok"}

    scheduler = GhostScheduler(
        store,
        [
            ScheduledTask(
                name="hourly",
                order=1,
                slots=hourly_slots(1),
                run=run,
            )
        ],
        tick_seconds=0.01,
        startup_grace_seconds=0,
    )
    now = datetime(2026, 11, 2, 10, 30, tzinfo=TZ)

    assert asyncio.run(scheduler.run_once(now=now)) == ["hourly"]
    assert asyncio.run(scheduler.run_once(now=now)) == []
    assert calls == ["2026-11-02T10:01:00+08:00"]
    record = store.get_job_run("hourly", "2026-11-02T10:01:00+08:00")
    assert record is not None
    assert record["status"] == "succeeded"
    assert record["attempts"] == 1


def test_failed_job_is_retried_on_the_next_tick(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    attempts: list[int] = []

    def run(now: datetime, slot: JobSlot) -> dict:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return {"status": "ok"}

    scheduler = GhostScheduler(
        store,
        [
            ScheduledTask(
                name="flaky",
                order=1,
                slots=hourly_slots(1),
                run=run,
            )
        ],
        tick_seconds=0.01,
        startup_grace_seconds=0,
    )
    now = datetime(2026, 11, 2, 10, 30, tzinfo=TZ)

    assert asyncio.run(scheduler.run_once(now=now)) == ["flaky"]
    failed = store.get_job_run("flaky", "2026-11-02T10:01:00+08:00")
    assert failed is not None
    assert failed["status"] == "failed"

    assert asyncio.run(scheduler.run_once(now=now)) == ["flaky"]
    succeeded = store.get_job_run("flaky", "2026-11-02T10:01:00+08:00")
    assert succeeded is not None
    assert succeeded["status"] == "succeeded"
    assert succeeded["attempts"] == 2


def test_claim_uses_a_lease_and_expires_for_another_worker(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    now = datetime(2026, 11, 2, 10, 30, tzinfo=TZ)

    first = store.claim_job_run("job", "period", now=now, lease_seconds=60)
    assert first is not None
    assert store.claim_job_run("job", "period", now=now, lease_seconds=60) is None

    later = now + timedelta(seconds=61)
    second = store.claim_job_run("job", "period", now=later, lease_seconds=60)
    assert second is not None
    assert second != first

    # A stale claim can no longer mark the period as succeeded.
    assert store.finish_job_run("job", "period", first, now=later) is False
    assert store.finish_job_run("job", "period", second, now=later) is True
    assert store.claim_job_run("job", "period", now=later) is None


# ---------------------------------------------------------------------------
# Startup catch-up
# ---------------------------------------------------------------------------
def test_monday_startup_catches_up_weekly_jobs_in_order(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    calls: list[tuple[str, str]] = []
    scheduler = GhostScheduler(
        store,
        runtime_tasks(store, tmp_path, calls=calls),
        tick_seconds=0.01,
        startup_grace_seconds=0,
    )

    executed = asyncio.run(scheduler.run_once(now=MONDAY, catchup=True))
    names = [name for name, _ in calls]
    assert names == [
        JOB_WAKA_TICK,
        JOB_SOURCE_FETCH,
        JOB_WAKA_ROSTER,
        JOB_WEEKLY_SETTLE,
        JOB_POWER,
        JOB_DIAMOND_DECAY,
    ]
    assert executed == names
    assert all(period == WEEK for _, period in calls[1:4])


def test_tuesday_startup_catches_up_rival_auto(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    calls: list[tuple[str, str]] = []
    scheduler = GhostScheduler(
        store,
        runtime_tasks(store, tmp_path, calls=calls),
        tick_seconds=0.01,
        startup_grace_seconds=0,
    )

    asyncio.run(scheduler.run_once(now=TUESDAY, catchup=True))
    names = [name for name, _ in calls]
    assert JOB_RIVAL_AUTO in names


def test_wednesday_skips_expired_source_and_roster_but_keeps_settle(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    calls: list[tuple[str, str]] = []
    scheduler = GhostScheduler(
        store,
        runtime_tasks(store, tmp_path, calls=calls),
        tick_seconds=0.01,
        startup_grace_seconds=0,
    )

    asyncio.run(scheduler.run_once(now=WEDNESDAY, catchup=True))
    names = [name for name, _ in calls]
    assert JOB_SOURCE_FETCH not in names
    assert JOB_WAKA_ROSTER not in names
    assert JOB_WEEKLY_SETTLE in names


def test_2130_does_not_settle_todays_daily_bet_but_2231_does(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    make_daily_pair(store)
    add_activity(
        store,
        "h1",
        event_id="h1-morning",
        seconds=1800,
        occurred_at=datetime(2026, 11, 2, 8, 30, tzinfo=TZ),
    )
    add_activity(
        store,
        "h2",
        event_id="h2-morning",
        seconds=600,
        occurred_at=datetime(2026, 11, 2, 8, 30, tzinfo=TZ),
    )
    daily_target = store.rival_state(
        "h1", now=datetime(2026, 11, 2, 8, 45, tzinfo=TZ)
    )["bet_options"]["daily"]["target_options"][0]["margin"]
    bet = store.place_bet(
        "h1",
        "daily",
        paid_stake=0,
        target_margin=daily_target,
        now=datetime(2026, 11, 2, 8, 45, tzinfo=TZ),
        request_id="daily-1",
    )
    expected_payout = payout_for_win(bet["stake"], bet["odds"])

    scheduler = GhostScheduler(
        store,
        runtime_tasks(store, tmp_path, keep_daily_real=True),
        tick_seconds=0.01,
        startup_grace_seconds=0,
    )

    asyncio.run(
        scheduler.run_once(
            now=datetime(2026, 11, 2, 21, 30, tzinfo=TZ),
            catchup=True,
        )
    )
    assert store.bets_for("h1", now=MONDAY)["daily"]["status"] == "placed"
    assert store.get_job_run(JOB_DAILY_BETS, "2026-11-02") is None

    asyncio.run(
        scheduler.run_once(
            now=datetime(2026, 11, 2, 22, 31, tzinfo=TZ),
            catchup=True,
        )
    )
    settled = store.bets_for(
        "h1", now=datetime(2026, 11, 2, 22, 31, tzinfo=TZ)
    )["daily"]
    assert settled is not None
    assert settled["status"] == "won"
    assert settled["payout"] == expected_payout


def test_daily_catchup_only_scans_past_days_with_pending_bets(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    previous_week = "2026-10-26"
    previous_monday = datetime(2026, 10, 26, 8, 0, 0, tzinfo=TZ)
    make_daily_pair(
        store, week=previous_week, monday=previous_monday
    )
    add_activity(
        store,
        "h1",
        event_id="h1-yesterday",
        seconds=1800,
        occurred_at=datetime(2026, 11, 1, 8, 30, tzinfo=TZ),
    )
    add_activity(
        store,
        "h2",
        event_id="h2-yesterday",
        seconds=600,
        occurred_at=datetime(2026, 11, 1, 8, 30, tzinfo=TZ),
    )
    daily_target = store.rival_state(
        "h1", now=datetime(2026, 11, 1, 8, 45, tzinfo=TZ)
    )["bet_options"]["daily"]["target_options"][0]["margin"]
    store.place_bet(
        "h1",
        "daily",
        paid_stake=0,
        target_margin=daily_target,
        now=datetime(2026, 11, 1, 8, 45, tzinfo=TZ),
        request_id="daily-yesterday",
    )

    scheduler = GhostScheduler(
        store,
        runtime_tasks(store, tmp_path, keep_daily_real=True),
        tick_seconds=0.01,
        startup_grace_seconds=0,
    )
    asyncio.run(
        scheduler.run_once(
            now=datetime(2026, 11, 2, 21, 30, tzinfo=TZ),
            catchup=True,
        )
    )
    settled = store.bets_for(
        "h1", now=datetime(2026, 11, 1, 12, 0, tzinfo=TZ)
    )["daily"]
    assert settled is not None
    assert settled["status"] == "won"
    # Today is not due at 21:30, so only the overdue day gets a run record.
    assert store.get_job_run(JOB_DAILY_BETS, "2026-11-02") is None
    assert store.get_job_run(JOB_DAILY_BETS, "2026-11-01") is not None


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------
def test_api_lifespan_starts_and_stops_scheduler() -> None:
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        api_dir = base / "api"
        api_dir.mkdir(parents=True)
        accounts = AccountsStore(api_dir / "accounts.db")
        accounts.initialize()
        accounts.create("owner", "You", token="scheduler-token")

        def factory(store: GameStore) -> list[ScheduledTask]:
            return [
                ScheduledTask(
                    name="idle",
                    order=1,
                    slots=lambda now: [],
                    run=lambda now, slot: {"status": "ok"},
                )
            ]

        app = create_app(
            game_db_path=api_dir / "league.db",
            cache_path=base / "cache.json",
            avatars_path=api_dir / "avatars.json",
            api_dir=api_dir,
            accounts_db=api_dir / "accounts.db",
            social_db=api_dir / "social.db",
            webhooks_db=api_dir / "webhooks.db",
            start_webhook_worker=False,
            token="scheduler-token",
            secret_path=api_dir / "secret",
            start_scheduler=True,
            scheduler_task_factory=factory,
            scheduler_tick_seconds=0.01,
            scheduler_startup_grace_seconds=0,
        )
        with TestClient(app) as client:
            scheduler = client.app.state.scheduler
            assert isinstance(scheduler, GhostScheduler)
            time_module.sleep(0.05)
            assert scheduler.running
            loop_task = scheduler.task
        assert loop_task is not None
        assert loop_task.done()
