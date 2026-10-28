"""Activity events, weekly scores, and ingest."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from .. import calendar as cal
from ..rules import DuplicateIdempotencyKey, WeekLocked, xp_for_seconds
from .core import _row_to_dict

class ActivityMixin:
    """Idempotent activity ingest and weekly score queries."""

    def get_week_score(
        self, player_id: str, week: date | datetime | str
    ) -> dict[str, Any] | None:
        week_iso = cal.iso_date(cal.week_start(week))
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM weekly_scores WHERE week_start = ? AND player_id = ?",
                (week_iso, player_id),
            ).fetchone()
            return _row_to_dict(row)

    def last_event_occurred_at(
        self, player_id: str, week: date | datetime | str
    ) -> str | None:
        week_iso = cal.iso_date(cal.week_start(week))
        with self._reader() as conn:
            row = conn.execute(
                "SELECT MAX(occurred_at) AS occurred_at FROM activity_events "
                "WHERE player_id = ? AND week_start = ?",
                (player_id, week_iso),
            ).fetchone()
            return None if row is None else row["occurred_at"]

    def ingest_activity(
        self,
        player_id: str,
        *,
        event_id: str,
        seconds: int,
        occurred_at: datetime | str,
        source: str,
        week_start: date | datetime | str | None = None,
        now: datetime | None = None,
        channel_id: str | None = None,
        player_ref: str | None = None,
    ) -> dict[str, Any]:
        if not event_id:
            raise ValueError("event_id must be non-empty")
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise TypeError("seconds must be an integer")
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        local_occurred = cal.parse_datetime(occurred_at)
        week_date = (
            cal.week_start(week_start)
            if week_start is not None
            else cal.week_start(local_occurred)
        )
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()

        with self.transaction() as conn:
            week = self._ensure_week_with(conn, week_iso, "active")
            if week["status"] == "settled":
                raise WeekLocked(f"week {week_iso} is already settled")
            player = self._get_player_with(conn, player_id)
            if channel_id is not None:
                if not player_ref:
                    raise ValueError("player_ref is required for channel ingest")
                linked = conn.execute(
                    "SELECT * FROM channel_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if linked is not None and str(linked["player_id"]) != player_id:
                    raise DuplicateIdempotencyKey(
                        f"event_id {event_id} already belongs to another player"
                    )
                if linked is None:
                    conn.execute(
                        "INSERT INTO channel_events "
                        "(event_id, channel_id, player_ref, player_id, seconds, "
                        "occurred_at, week_start, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            event_id,
                            channel_id,
                            player_ref,
                            player_id,
                            seconds,
                            cal.iso_ts(local_occurred),
                            week_iso,
                            cal.iso_ts(local_now),
                        ),
                    )
            cursor = conn.execute(
                "INSERT OR IGNORE INTO activity_events "
                "(player_id, event_id, seconds, occurred_at, week_start, source, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    player_id,
                    event_id,
                    seconds,
                    cal.iso_ts(local_occurred),
                    week_iso,
                    source,
                    cal.iso_ts(local_now),
                ),
            )
            if cursor.rowcount == 0:
                stored = conn.execute(
                    "SELECT * FROM activity_events "
                    "WHERE player_id = ? AND event_id = ?",
                    (player_id, event_id),
                ).fetchone()
                stored_week = (
                    str(stored["week_start"]) if stored is not None else week_iso
                )
                score = conn.execute(
                    "SELECT * FROM weekly_scores WHERE week_start = ? AND player_id = ?",
                    (stored_week, player_id),
                ).fetchone()
                stored_occurred = (
                    cal.parse_datetime(str(stored["occurred_at"]))
                    if stored is not None
                    else local_occurred
                )
                stored_day = stored_occurred.date()
                duplicate_day_seconds = self._day_seconds(
                    conn, player_id, stored_day
                )
                duplicate_checkin = conn.execute(
                    "SELECT * FROM checkins WHERE player_id = ? AND date = ?",
                    (player_id, stored_day.isoformat()),
                ).fetchone()
                return {
                    "accepted": False,
                    "duplicate": True,
                    "player_id": player_id,
                    "event_id": event_id,
                    "week_start": stored_week,
                    "seconds": int(stored["seconds"]) if stored is not None else 0,
                    "week_seconds": int(score["seconds"]) if score else 0,
                    "week_xp": int(score["xp"]) if score else 0,
                    "day_seconds": duplicate_day_seconds,
                    "day_xp": xp_for_seconds(duplicate_day_seconds),
                    "checkin": (
                        {
                            "created": False,
                            "source": str(duplicate_checkin["source"]),
                            "date": stored_day.isoformat(),
                            "seconds": int(duplicate_checkin["seconds"]),
                            "xp": int(duplicate_checkin["xp"]),
                        }
                        if duplicate_checkin is not None
                        else None
                    ),
                }

            group = conn.execute(
                "SELECT g.id FROM groups g JOIN group_members gm ON gm.group_id = g.id "
                "WHERE g.week_start = ? AND gm.player_id = ? "
                "ORDER BY g.id DESC LIMIT 1",
                (week_iso, player_id),
            ).fetchone()
            group_id = int(group["id"]) if group is not None else None
            score = conn.execute(
                "SELECT * FROM weekly_scores WHERE week_start = ? AND player_id = ?",
                (week_iso, player_id),
            ).fetchone()
            if score is None:
                week_seconds = seconds
                week_xp = xp_for_seconds(week_seconds)
                conn.execute(
                    "INSERT INTO weekly_scores "
                    "(week_start, player_id, group_id, seconds, xp) VALUES (?, ?, ?, ?, ?)",
                    (week_iso, player_id, group_id, week_seconds, week_xp),
                )
            else:
                week_seconds = int(score["seconds"]) + seconds
                week_xp = xp_for_seconds(week_seconds)
                conn.execute(
                    "UPDATE weekly_scores SET seconds = ?, xp = ?, "
                    "group_id = COALESCE(?, group_id) "
                    "WHERE week_start = ? AND player_id = ?",
                    (week_seconds, week_xp, group_id, week_iso, player_id),
                )

            checkin = self._auto_checkin(
                conn,
                player_id=player_id,
                player=player,
                day=local_occurred.date(),
                day_seconds=self._day_seconds(
                    conn, player_id, local_occurred.date()
                ),
                now=local_now,
            )
            if checkin and checkin.get("created"):
                self._recompute_streak(
                    conn, player_id, today=local_now.date(), now=local_now
                )
            if checkin is not None:
                self._apply_daily_progression_with(
                    conn, player_id, now=local_now
                )

            day_seconds = self._day_seconds(
                conn, player_id, local_occurred.date()
            )
            if checkin and checkin.get("created"):
                self._record_checkin_feed_with(
                    conn,
                    player_id=player_id,
                    day=local_occurred.date(),
                    week_start=week_iso,
                    xp=int(checkin.get("xp") or xp_for_seconds(day_seconds)),
                    source=str(checkin.get("source") or "verified"),
                    now=local_now,
                )
            return {
                "accepted": True,
                "duplicate": False,
                "player_id": player_id,
                "event_id": event_id,
                "week_start": week_iso,
                "seconds": seconds,
                "week_seconds": week_seconds,
                "week_xp": week_xp,
                "day_seconds": day_seconds,
                "day_xp": xp_for_seconds(day_seconds),
                "checkin": checkin,
            }

    @staticmethod
    def _day_seconds(conn: sqlite3.Connection, player_id: str, day: date) -> int:
        start = cal.iso_ts(cal.day_start_at(day))
        end = cal.iso_ts(cal.day_end_at(day))
        row = conn.execute(
            "SELECT COALESCE(SUM(seconds), 0) AS n FROM activity_events "
            "WHERE player_id = ? AND occurred_at >= ? AND occurred_at < ?",
            (player_id, start, end),
        ).fetchone()
        return int(row["n"])

    def day_seconds(self, player_id: str, day: date | datetime | str) -> int:
        with self._reader() as conn:
            return self._day_seconds(conn, player_id, cal.parse_date(day))
