"""Weekly target to hourly increments using Ghost's existing pure math.

The Channel deliberately reuses ``ghost_league.schedule.projected_seconds``:
the weekly effective target is allocated over 168 capped hours, and a tick only
materializes hours whose end is already at or before the current hour boundary.
No provider fields or raw weekly totals leave this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from ghost_league.schedule import TZ, projected_seconds

from .roster import SourceRow

HOURS_PER_WEEK = 168
SECONDS_PER_HOUR = 3600


@dataclass(frozen=True, slots=True)
class HourlyIncrement:
    """One completed hour of activity for a single anonymous player."""

    player_ref: str
    week_start: date
    hour_start: datetime
    seconds: int
    event_id: str
    occurred_at: datetime

    def as_payload(self) -> dict[str, Any]:
        """Return exactly the four fields accepted by Ghost increments."""

        return {
            "player_ref": self.player_ref,
            "event_id": self.event_id,
            "seconds": int(self.seconds),
            "occurred_at": self.occurred_at.isoformat(timespec="seconds"),
        }


@dataclass(frozen=True, slots=True)
class TickPlan:
    """Pure result of one tick, before any HTTP side effects."""

    at: datetime
    week_start: date
    boundary: datetime
    events: tuple[HourlyIncrement, ...] = ()
    next_hours: Mapping[str, str] = field(default_factory=dict)

    @property
    def total_seconds(self) -> int:
        return sum(event.seconds for event in self.events)

    @property
    def players(self) -> int:
        return len({event.player_ref for event in self.events})


def parse_week_start(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        local = parse_at(value)
        return local.date() - timedelta(days=local.weekday())
    if isinstance(value, date):
        return value - timedelta(days=value.weekday())
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "week_start must be an ISO date such as 2026-10-26"
            ) from exc
        return parsed - timedelta(days=parsed.weekday())
    raise TypeError("week_start must be a date, datetime, or ISO date string")


def parse_at(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "at must be ISO-8601, e.g. 2026-10-28T12:00:00+08:00"
            ) from exc
    else:
        raise TypeError("at must be a datetime or ISO-8601 string")
    if moment.tzinfo is None:
        # Channel wall-clock times are Asia/Shanghai, like the game calendar.
        moment = moment.replace(tzinfo=TZ)
    return moment.astimezone(TZ)


def hour_floor(value: datetime) -> datetime:
    local = parse_at(value)
    return local.replace(minute=0, second=0, microsecond=0)


def week_start_at(week_start: date | datetime | str) -> datetime:
    week = parse_week_start(week_start)
    return datetime.combine(week, time.min, tzinfo=TZ)


def week_end_at(week_start: date | datetime | str) -> datetime:
    return week_start_at(week_start) + timedelta(days=7)


def hour_iso(value: datetime) -> str:
    return parse_at(value).isoformat(timespec="seconds")


def make_event_id(
    player_ref: str, week_start: date | datetime | str, hour: datetime
) -> str:
    """Stable id: ``waka:{player_ref}:{week_start}:{hour_iso}``."""

    return (
        f"waka:{player_ref}:{parse_week_start(week_start).isoformat()}:"
        f"{hour_iso(hour)}"
    )


def hourly_increments(
    player_ref: str,
    week_start: date | datetime | str,
    total_seconds: int,
    *,
    include_zero: bool = True,
) -> list[HourlyIncrement]:
    """Return all 168 hourly increments for a weekly effective target.

    With ``include_zero=True`` (the default) the result always has 168 rows, so
    callers can inspect the full schedule and sum it.  HTTP senders filter to
    positive seconds because Ghost rejects zero-second increments.
    """

    week = parse_week_start(week_start)
    start_dt = week_start_at(week)
    increments: list[HourlyIncrement] = []
    for index in range(HOURS_PER_WEEK):
        start = start_dt + timedelta(hours=index)
        end = start + timedelta(hours=1)
        before = projected_seconds(player_ref, week, total_seconds, start)
        after = projected_seconds(player_ref, week, total_seconds, end)
        seconds = after - before
        if seconds < 0:
            raise RuntimeError("projection produced a negative hourly increment")
        if seconds or include_zero:
            increments.append(
                HourlyIncrement(
                    player_ref=player_ref,
                    week_start=week,
                    hour_start=start,
                    seconds=seconds,
                    event_id=make_event_id(player_ref, week, start),
                    occurred_at=end,
                )
            )
    return increments


def increments_between(
    player_ref: str,
    week_start: date | datetime | str,
    total_seconds: int,
    start: datetime | str,
    end: datetime | str,
    *,
    include_zero: bool = False,
) -> list[HourlyIncrement]:
    """Return increments for completed hours in ``[start, end)``.

    Partial hours are not materialized: both ends are floored to the hour.  By
    default only positive increments are returned.
    """

    week = parse_week_start(week_start)
    window_start = hour_floor(parse_at(start))
    window_end = hour_floor(parse_at(end))
    if window_end <= window_start:
        return []
    increments: list[HourlyIncrement] = []
    cursor = window_start
    while cursor < window_end:
        next_hour = cursor + timedelta(hours=1)
        before = projected_seconds(player_ref, week, total_seconds, cursor)
        after = projected_seconds(player_ref, week, total_seconds, next_hour)
        seconds = after - before
        if seconds < 0:
            raise RuntimeError("projection produced a negative hourly increment")
        if seconds or include_zero:
            increments.append(
                HourlyIncrement(
                    player_ref=player_ref,
                    week_start=week,
                    hour_start=cursor,
                    seconds=seconds,
                    event_id=make_event_id(player_ref, week, cursor),
                    occurred_at=next_hour,
                )
            )
        cursor = next_hour
    return increments


def _row_player_ref(row: Any) -> str:
    if isinstance(row, Mapping):
        value = row.get("player_ref")
    else:
        value = getattr(row, "player_ref", None)
    if not isinstance(value, str) or not value:
        raise ValueError("row must contain a non-empty player_ref")
    return value


def _row_target(row: Any) -> int:
    if isinstance(row, Mapping):
        value = row.get("effective_seconds", row.get("target_seconds"))
    else:
        value = getattr(
            row, "effective_seconds", getattr(row, "target_seconds", None)
        )
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("row must contain a non-negative integer target")
    return value


def tick_increments(
    rows: Iterable[SourceRow | Mapping[str, Any]],
    at: datetime | str,
    *,
    week_start: date | datetime | str | None = None,
    cursors: Mapping[str, str | datetime | None] | None = None,
) -> TickPlan:
    """Plan one idempotent tick for all current roster rows.

    ``cursors`` maps ``player_ref`` to the last hour *start* already processed
    for that week.  Only hours ending at or before ``hour_floor(at)`` are
    emitted.  Rows whose cursor is already current produce no events; rows new
    to the roster backfill their completed hours from the week start.
    """

    local_at = parse_at(at)
    week = parse_week_start(week_start) if week_start is not None else parse_week_start(local_at)
    boundary = hour_floor(local_at)
    end = min(boundary, week_end_at(week))
    begin = week_start_at(week)
    cursor_map = cursors or {}
    events: list[HourlyIncrement] = []
    next_hours: dict[str, str] = {}

    for row in rows:
        ref = _row_player_ref(row)
        target = _row_target(row)
        raw_cursor = cursor_map.get(ref)
        if raw_cursor is not None:
            cursor = hour_floor(parse_at(raw_cursor))
            start = max(begin, cursor + timedelta(hours=1))
        else:
            start = begin
        if start >= end:
            continue
        events.extend(
            increments_between(ref, week, target, start, end, include_zero=False)
        )
        next_hours[ref] = (end - timedelta(hours=1)).isoformat(timespec="seconds")

    return TickPlan(
        at=local_at,
        week_start=week,
        boundary=boundary,
        events=tuple(events),
        next_hours=next_hours,
    )


__all__ = [
    "HOURS_PER_WEEK",
    "SECONDS_PER_HOUR",
    "HourlyIncrement",
    "TickPlan",
    "hour_floor",
    "hour_iso",
    "hourly_increments",
    "increments_between",
    "make_event_id",
    "parse_at",
    "parse_week_start",
    "tick_increments",
    "week_end_at",
    "week_start_at",
]
