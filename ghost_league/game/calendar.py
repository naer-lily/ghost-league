"""Asia/Shanghai calendar helpers for the game core.

Every persisted timestamp is an aware Asia/Shanghai ISO-8601 string with a
seconds precision.  Weeks start on Monday 00:00 local time.  The helpers in
this module are deliberately pure so business code can be tested with a fixed
clock.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Final

from ..schedule import TZ

SECONDS_PER_DAY: Final = 86_400
SECONDS_PER_WEEK: Final = 7 * SECONDS_PER_DAY


def as_local(value: datetime) -> datetime:
    """Return ``value`` in Asia/Shanghai.

    Naive datetimes are interpreted as Asia/Shanghai because the game domain
    only speaks local wall-clock time.  (``schedule.py`` historically treats
    naive inputs as UTC; callers here always pass aware values downstream.)
    """

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def now_local() -> datetime:
    return datetime.now(tz=TZ)


def parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return as_local(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "timestamp must be ISO-8601, e.g. 2026-10-28T12:00:00+08:00"
            ) from exc
        return as_local(parsed)
    raise TypeError("timestamp must be a datetime or ISO-8601 string")


def parse_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return as_local(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must be ISO-8601, e.g. 2026-10-26") from exc
    raise TypeError("date must be a date, datetime, or ISO date string")


def week_start(value: date | datetime | str) -> date:
    """Return the Monday 00:00 date of the week containing ``value``."""

    day = parse_date(value)
    return day - timedelta(days=day.weekday())


def week_start_at(value: date | datetime | str) -> datetime:
    return datetime.combine(week_start(value), time.min, tzinfo=TZ)


def week_end_at(value: date | datetime | str) -> datetime:
    return week_start_at(value) + timedelta(days=7)


def day_start_at(value: date | datetime | str) -> datetime:
    return datetime.combine(parse_date(value), time.min, tzinfo=TZ)


def day_end_at(value: date | datetime | str) -> datetime:
    return day_start_at(value) + timedelta(days=1)


def iso_ts(value: datetime) -> str:
    return as_local(value).isoformat(timespec="seconds")


def iso_date(value: date | datetime | str) -> str:
    return parse_date(value).isoformat()


def hour_floor(value: datetime) -> datetime:
    local = as_local(value)
    return local.replace(minute=0, second=0, microsecond=0)


def previous_week_start(value: date | datetime | str) -> date:
    return week_start(value) - timedelta(days=7)


def completed_day_dates(
    start: date,
    end_exclusive: date,
) -> list[date]:
    """Return every date in ``[start, end_exclusive)`` in ascending order."""

    if end_exclusive <= start:
        return []
    return [start + timedelta(days=offset) for offset in range((end_exclusive - start).days)]
