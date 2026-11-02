"""Composition root for the in-process scheduler jobs.

The game core stays free of Channel and Source imports.  This module is the
runtime adapter that wires those deployable units into the scheduler owned by
the API process.  Every runner is safe to invoke repeatedly; the scheduler's
``job_runs`` lease adds cross-worker at-most-once coordination per period.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import time
from pathlib import Path
from typing import Any, Final

from waka_channel.cli import DEFAULT_STATE as DEFAULT_WAKA_STATE
from waka_channel.cli import sync_roster, tick
from waka_channel.client import DEFAULT_BASE_URL, ChannelClient

from .fetch import fetch_to_cache
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

JOB_WAKA_TICK: Final = "waka-tick"
JOB_POWER: Final = "power"
JOB_DIAMOND_DECAY: Final = "diamond-decay"
JOB_SOURCE_FETCH: Final = "source-fetch"
JOB_WAKA_ROSTER: Final = "waka-roster"
JOB_WEEKLY_SETTLE: Final = "weekly-settle"
JOB_RIVAL_AUTO: Final = "rival-auto"
JOB_DAILY_BETS: Final = "daily-bets"

DEFAULT_SOURCE_COUNTRY: Final = "CN"
DAILY_CATCHUP_DAYS: Final = 7


def _make_channel_client() -> ChannelClient:
    base_url = os.environ.get("GHOST_LEAGUE_BASE_URL") or DEFAULT_BASE_URL
    return ChannelClient(base_url)


def build_scheduled_tasks(
    store: GameStore,
    *,
    cache_path: str | Path,
    source_country: str | None = None,
    runners: Mapping[str, Runner] | None = None,
) -> list[ScheduledTask]:
    """Build every Ghost background job with its local-time schedule.

    ``runners`` lets tests replace network-backed jobs (source fetch, Waka
    roster/tick) while keeping the real due-time rules and database lease.
    """

    cache = Path(cache_path)
    state_path = os.environ.get("WAKA_CHANNEL_STATE", str(DEFAULT_WAKA_STATE))
    country = (
        source_country
        if source_country is not None
        else os.environ.get("GHOST_LEAGUE_SOURCE_COUNTRY", DEFAULT_SOURCE_COUNTRY)
    )
    overrides = runners or {}

    def run_source_fetch(now: Any, _: JobSlot) -> dict[str, Any]:
        data = fetch_to_cache(cache, country=country or None, now=now)
        return {
            "status": "fetched",
            "row_count": data.get("row_count"),
            "pages": data.get("pages"),
            "source_week_start": data.get("source_week_start"),
            "fetched_at": data.get("fetched_at"),
        }

    def run_waka_tick(now: Any, _: JobSlot) -> dict[str, Any]:
        return tick(
            _make_channel_client(),
            at=now,
            cache=cache,
            state_path=state_path,
        )

    def run_waka_roster(now: Any, _: JobSlot) -> dict[str, Any]:
        return sync_roster(_make_channel_client(), cache=cache)

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
        JOB_SOURCE_FETCH: run_source_fetch,
        JOB_WAKA_ROSTER: run_waka_roster,
        JOB_WAKA_TICK: run_waka_tick,
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
            name=JOB_WAKA_TICK,
            order=10,
            slots=hourly_slots(1),
            run=runner(JOB_WAKA_TICK),
        ),
        ScheduledTask(
            name=JOB_SOURCE_FETCH,
            order=20,
            slots=weekly_slots(0, time(0, 2), same_day_only=True),
            run=runner(JOB_SOURCE_FETCH),
        ),
        ScheduledTask(
            name=JOB_WAKA_ROSTER,
            order=30,
            slots=weekly_slots(0, time(0, 3), same_day_only=True),
            run=runner(JOB_WAKA_ROSTER),
        ),
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
    "DEFAULT_SOURCE_COUNTRY",
    "JOB_DAILY_BETS",
    "JOB_DIAMOND_DECAY",
    "JOB_POWER",
    "JOB_RIVAL_AUTO",
    "JOB_SOURCE_FETCH",
    "JOB_WAKA_ROSTER",
    "JOB_WAKA_TICK",
    "JOB_WEEKLY_SETTLE",
    "build_scheduled_tasks",
]
