"""The single daily-activity resolver shared by every read path.

Raw activity lives in two places: ``activity_events`` (local increments) and
``channel_events`` (Channel pushes).  A ``checkins`` row materialises one day
and is authoritative once it exists.  This module is the only place that
combines those sources; API and page code must call it instead of rebuilding
the fallback with its own SQL.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from .. import calendar as cal
from ..rules import xp_for_seconds


class DailyActivityMixin:
    """Read one day or a range as the same daily activity result."""

    def _daily_activity_on_day_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        day: date | datetime | str,
    ) -> dict[str, Any]:
        """Resolve one local day ahead of any API/page projection.

        A check-in wins even when its XP is zero.  Otherwise the day's raw
        seconds are ``max(activity_events, channel_events)`` so the two feeds
        are never double counted.
        """

        day_date = cal.parse_date(day)
        checkin = conn.execute(
            "SELECT source, seconds, xp FROM checkins "
            "WHERE player_id = ? AND date = ?",
            (player_id, day_date.isoformat()),
        ).fetchone()
        if checkin is not None:
            return {
                "checkin_source": str(checkin["source"]),
                "seconds": int(checkin["seconds"]),
                "xp": int(checkin["xp"]),
            }
        activity_seconds = self._day_seconds(  # type: ignore[attr-defined]
            conn, player_id, day_date
        )
        channel_seconds = self._channel_seconds_on_day_with(  # type: ignore[attr-defined]
            conn, player_id, day_date
        )
        seconds = max(activity_seconds, channel_seconds)
        return {
            "checkin_source": None,
            "seconds": seconds,
            "xp": xp_for_seconds(seconds),
        }

    def daily_activity_on_day(
        self,
        player_id: str,
        day: date | datetime | str,
    ) -> dict[str, Any]:
        """Return the resolved activity for one local day."""

        with self._reader() as conn:  # type: ignore[attr-defined]
            return self._daily_activity_on_day_with(conn, player_id, day)

    def daily_xp_between(
        self,
        player_id: str,
        start: date | str,
        end_exclusive: date | str,
    ) -> dict[str, int]:
        """Return ``{date: xp}`` for every local day in the half-open range."""

        start_day = cal.parse_date(start)
        end_day = cal.parse_date(end_exclusive)
        if end_day <= start_day:
            return {}
        xp_by_day: dict[str, int] = {}
        with self._reader() as conn:  # type: ignore[attr-defined]
            day = start_day
            while day < end_day:
                xp_by_day[day.isoformat()] = int(
                    self._daily_activity_on_day_with(
                        conn, player_id, day
                    )["xp"]
                )
                day += timedelta(days=1)
        return xp_by_day


__all__ = ["DailyActivityMixin"]
