"""Composition root for the in-process scheduler jobs.

The scheduler registers only generic game jobs.  Source/Channel cache refresh is
a Channel or operator concern: it is deliberately not registered here, and this
module does not import a Channel or provider client.  Every runner is safe to
invoke repeatedly; the scheduler's ``job_runs`` lease adds cross-worker
at-most-once coordination per period.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
from pathlib import Path
from typing import Any, Final

from .game.jobs import (
    run_auto_assign_rivals,
    run_daily_bets,
    run_diamond_decay,
    run_power_refresh,
    run_weekly_settlement,
)
from .game.rival import DAILY_BET_SETTLE_TIME
from .game.scheduler import (
    JobSlot,
    Runner,
    ScheduledTask,
    daily_slots,
    hourly_slots,
    weekly_slots,
)
from .game.store import GameStore

JOB_POWER: Final = "power"
JOB_DIAMOND_DECAY: Final = "diamond-decay"
JOB_WEEKLY_SETTLE: Final = "weekly-settle"
JOB_RIVAL_AUTO: Final = "rival-auto"
JOB_DAILY_BETS: Final = "daily-bets"

DAILY_CATCHUP_DAYS: Final = 7


def build_scheduled_tasks(
    store: GameStore,
    *,
    cache_path: str | Path | None = None,
    source_country: str | None = None,
    runners: Mapping[str, Runner] | None = None,
) -> list[ScheduledTask]:
    """Build every Ghost background job with its local-time schedule.

    ``runners`` lets tests replace a job while keeping the real due-time rules
    and database lease.  ``cache_path`` / ``source_country`` remain accepted for
    older callers but are unused: no source or Channel job is registered here.
    """

    del cache_path, source_country
    overrides = runners or {}

    def run_power(now: Any, _: JobSlot) -> dict[str, Any]:
        return run_power_refresh(store.path, at=now)

    def run_decay(now: Any, _: JobSlot) -> dict[str, Any]:
        return run_diamond_decay(store.path, at=now)

    def run_settle(now: Any, _: JobSlot) -> dict[str, Any]:
        return run_weekly_settlement(store.path, at=now)

    def run_rival_auto(now: Any, _: JobSlot) -> dict[str, Any]:
        return run_auto_assign_rivals(store.path, at=now)

    def run_daily(now: Any, slot: JobSlot) -> dict[str, Any]:
        return run_daily_bets(store.path, day=slot.period_key, at=now)

    defaults: dict[str, Runner] = {
        JOB_POWER: run_power,
        JOB_DIAMOND_DECAY: run_decay,
        JOB_WEEKLY_SETTLE: run_settle,
        JOB_RIVAL_AUTO: run_rival_auto,
        JOB_DAILY_BETS: run_daily,
    }

    def runner(name: str) -> Runner:
        return overrides.get(name) or defaults[name]

    return [
        ScheduledTask(
            name=JOB_WEEKLY_SETTLE,
            order=40,
            slots=weekly_slots(0, time(0, 5)),
            run=runner(JOB_WEEKLY_SETTLE),
        ),
        ScheduledTask(
            name=JOB_RIVAL_AUTO,
            order=50,
            slots=weekly_slots(1, time(0, 0)),
            run=runner(JOB_RIVAL_AUTO),
        ),
        ScheduledTask(
            name=JOB_DAILY_BETS,
            order=60,
            slots=daily_slots(
                DAILY_BET_SETTLE_TIME,
                lookback_days=DAILY_CATCHUP_DAYS,
                include_past_day=store.has_unsettled_daily_bets,
            ),
            run=runner(JOB_DAILY_BETS),
        ),
        ScheduledTask(
            name=JOB_POWER,
            order=70,
            slots=hourly_slots(5),
            run=runner(JOB_POWER),
        ),
        ScheduledTask(
            name=JOB_DIAMOND_DECAY,
            order=80,
            slots=hourly_slots(10),
            run=runner(JOB_DIAMOND_DECAY),
        ),
    ]


__all__ = [
    "DAILY_CATCHUP_DAYS",
    "JOB_DAILY_BETS",
    "JOB_DIAMOND_DECAY",
    "JOB_POWER",
    "JOB_RIVAL_AUTO",
    "JOB_WEEKLY_SETTLE",
    "build_scheduled_tasks",
]
