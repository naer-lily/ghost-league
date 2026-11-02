"""In-process scheduler for Ghost League background jobs.

The API process owns its own timer.  There is no external service, periodic
trigger, or plugin to install: :class:`GhostScheduler` runs one catch-up pass
immediately after startup and then checks due jobs on a fixed tick.

Coordination is persisted in ``league.db`` (``job_runs``).  A ``(name,
period_key)`` pair is claimed atomically with a lease, so several API workers
can run the same scheduler without executing a period twice.  Failed or
crashed runs become eligible again, while successful periods are skipped
forever.  Job runners must still be idempotent; the scheduler is a safety net,
not a replacement for per-job guards.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final

from . import calendar as cal
from .store import GameStore

LOGGER: Final = logging.getLogger(__name__)

DEFAULT_TICK_SECONDS: Final = 20.0
DEFAULT_LEASE_SECONDS: Final = 30.0
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS: Final = 15.0
DEFAULT_STARTUP_GRACE_SECONDS: Final = 0.25

Runner = Callable[[datetime, "JobSlot"], dict[str, Any]]
SlotBuilder = Callable[[datetime], Sequence["JobSlot"]]
PastDayFilter = Callable[[date], bool]


@dataclass(frozen=True, slots=True)
class JobSlot:
    """One scheduled period that is currently due."""

    period_key: str
    due_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    """A named job plus the rule that decides which periods are due."""

    name: str
    order: int
    slots: SlotBuilder
    run: Runner


def hourly_slots(minute: int) -> SlotBuilder:
    """Return the latest due hourly period at ``minute`` past the hour."""

    if not 0 <= minute <= 59:
        raise ValueError("minute must be between 0 and 59")

    def slots(now: datetime) -> list[JobSlot]:
        local_now = cal.as_local(now)
        due_at = local_now.replace(minute=minute, second=0, microsecond=0)
        if due_at > local_now:
            due_at -= timedelta(hours=1)
        return [JobSlot(period_key=cal.iso_ts(due_at), due_at=due_at)]

    return slots


def daily_slots(
    at: time,
    *,
    lookback_days: int = 7,
    include_past_day: PastDayFilter | None = None,
) -> SlotBuilder:
    """Return every due daily period in the last ``lookback_days``.

    Today's slot is always included once its time has passed.  Previous days
    are optional and controlled by ``include_past_day`` so a catch-up pass
    does not create empty run records for days without work.
    """

    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")

    def slots(now: datetime) -> list[JobSlot]:
        local_now = cal.as_local(now)
        today = local_now.date()
        due: list[JobSlot] = []
        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            due_at = cal.day_time_at(day, at)
            if due_at > local_now:
                continue
            if (
                offset > 0
                and include_past_day is not None
                and not include_past_day(day)
            ):
                continue
            due.append(JobSlot(period_key=cal.iso_date(day), due_at=due_at))
        due.sort(key=lambda slot: slot.due_at)
        return due

    return slots


def weekly_slots(
    weekday: int,
    at: time,
    *,
    same_day_only: bool = False,
) -> SlotBuilder:
    """Return the current week's ``weekday`` period once it is due.

    ``same_day_only`` limits catch-up to the scheduled local date (Monday for
    the weekly fetch/roster jobs).  Without it the period remains due for the
    rest of the week, which is what settlement and rival auto-selection need.
    """

    if not 0 <= weekday <= 6:
        raise ValueError("weekday must be between 0 and 6")

    def slots(now: datetime) -> list[JobSlot]:
        local_now = cal.as_local(now)
        week_start = cal.week_start(local_now)
        day = week_start + timedelta(days=weekday)
        due_at = cal.day_time_at(day, at)
        if due_at > local_now:
            return []
        if same_day_only and local_now.date() != day:
            return []
        return [JobSlot(period_key=cal.iso_date(week_start), due_at=due_at)]

    return slots


class GhostScheduler:
    """Run :class:`ScheduledTask` objects on a fixed in-process tick."""

    def __init__(
        self,
        store: GameStore,
        tasks: Sequence[ScheduledTask],
        *,
        now_fn: Callable[[], datetime] = cal.now_local,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        shutdown_timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
        startup_grace_seconds: float = DEFAULT_STARTUP_GRACE_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        if tick_seconds <= 0:
            raise ValueError("tick_seconds must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("shutdown_timeout_seconds must be positive")
        if startup_grace_seconds < 0:
            raise ValueError("startup_grace_seconds must be non-negative")
        self.store = store
        self.tasks = tuple(sorted(tasks, key=lambda task: (task.order, task.name)))
        self._now_fn = now_fn
        self.tick_seconds = float(tick_seconds)
        self.lease_seconds = float(lease_seconds)
        self.shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self.startup_grace_seconds = float(startup_grace_seconds)
        self._logger = logger or LOGGER
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def task(self) -> asyncio.Task[None] | None:
        """Expose the loop task for lifecycle tests and diagnostics."""

        return self._task

    def start(self) -> None:
        """Start the background loop without blocking API startup."""

        if self.running:
            return
        if self._stop_event.is_set():
            self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="ghost-scheduler")

    async def stop(self) -> None:
        """Stop the loop and give the current job a bounded grace period."""

        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(task), timeout=self.shutdown_timeout_seconds
            )
        except asyncio.TimeoutError:
            self._logger.warning(
                "scheduler shutdown timed out after %.1fs; cancelling loop",
                self.shutdown_timeout_seconds,
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            raise

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        catchup: bool = False,
    ) -> list[str]:
        """Run every due period once and return the claimed task names.

        The method is public so tests and operators can force a deterministic
        pass with an explicit clock instead of waiting for the loop tick.
        """

        local_now = cal.parse_datetime(now) if now is not None else self._now_fn()
        local_now = cal.as_local(local_now)
        executed: list[str] = []
        for task in self.tasks:
            try:
                slots = sorted(task.slots(local_now), key=lambda slot: slot.due_at)
            except Exception:
                self._logger.exception(
                    "scheduler could not compute due slots name=%s", task.name
                )
                continue
            for slot in slots:
                if slot.due_at > local_now:
                    continue
                run_id = await asyncio.to_thread(
                    self.store.claim_job_run,
                    task.name,
                    slot.period_key,
                    now=local_now,
                    lease_seconds=self.lease_seconds,
                )
                if run_id is None:
                    continue
                executed.append(task.name)
                self._logger.info(
                    "scheduler job started name=%s period=%s catchup=%s",
                    task.name,
                    slot.period_key,
                    catchup,
                )
                heartbeat = asyncio.create_task(
                    self._keep_lease(task.name, slot.period_key, run_id)
                )
                try:
                    await asyncio.to_thread(task.run, local_now, slot)
                except Exception as exc:
                    self._logger.exception(
                        "scheduler job failed name=%s period=%s",
                        task.name,
                        slot.period_key,
                    )
                    try:
                        await asyncio.to_thread(
                            self.store.fail_job_run,
                            task.name,
                            slot.period_key,
                            run_id,
                            error=f"{type(exc).__name__}: {exc}",
                            now=local_now,
                        )
                    except Exception:
                        self._logger.exception(
                            "scheduler could not record failure name=%s period=%s",
                            task.name,
                            slot.period_key,
                        )
                else:
                    try:
                        finished = await asyncio.to_thread(
                            self.store.finish_job_run,
                            task.name,
                            slot.period_key,
                            run_id,
                            now=local_now,
                        )
                    except Exception:
                        self._logger.exception(
                            "scheduler could not record success name=%s period=%s",
                            task.name,
                            slot.period_key,
                        )
                    else:
                        if finished:
                            self._logger.info(
                                "scheduler job finished name=%s period=%s",
                                task.name,
                                slot.period_key,
                            )
                        else:
                            self._logger.warning(
                                "scheduler lost lease before finishing "
                                "name=%s period=%s",
                                task.name,
                                slot.period_key,
                            )
                finally:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
        return executed

    async def _keep_lease(
        self,
        name: str,
        period_key: str,
        run_id: str,
    ) -> None:
        """Renew a running claim so a slow job keeps its period."""

        interval = max(1.0, self.lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await asyncio.to_thread(
                    self.store.renew_job_run,
                    name,
                    period_key,
                    run_id,
                    now=self._now_fn(),
                    lease_seconds=self.lease_seconds,
                )
            except Exception:
                self._logger.exception(
                    "scheduler could not renew lease name=%s period=%s",
                    name,
                    period_key,
                )
                return
            if not renewed:
                self._logger.warning(
                    "scheduler lost lease name=%s period=%s", name, period_key
                )
                return

    async def _loop(self) -> None:
        try:
            if self.startup_grace_seconds:
                await asyncio.sleep(self.startup_grace_seconds)
            first_pass = True
            while not self._stop_event.is_set():
                try:
                    await self.run_once(catchup=first_pass)
                except Exception:
                    self._logger.exception("scheduler tick failed")
                first_pass = False
                if self._stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.tick_seconds
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        finally:
            self._logger.info("scheduler loop stopped")


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_SHUTDOWN_TIMEOUT_SECONDS",
    "DEFAULT_STARTUP_GRACE_SECONDS",
    "DEFAULT_TICK_SECONDS",
    "GhostScheduler",
    "JobSlot",
    "ScheduledTask",
    "daily_slots",
    "hourly_slots",
    "weekly_slots",
]
