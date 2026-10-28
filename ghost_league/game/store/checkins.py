"""Check-ins, streaks, and the ember ledger/balance."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from .. import calendar as cal
from ..rules import (
    CHECKIN_SECONDS,
    DuplicateIdempotencyKey,
    RepairRejected,
    earned_embers_for_week,
    ember_grant_amount,
    is_valid_repair_day,
    xp_for_seconds,
)
from .core import _row_to_dict

class CheckinsMixin:
    """Daily check-ins, streak maintenance, and ember accounting."""

    def _auto_checkin(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        player: dict[str, Any],
        day: date,
        day_seconds: int,
        now: datetime,
    ) -> dict[str, Any] | None:
        if day_seconds < CHECKIN_SECONDS:
            return None
        day_iso = day.isoformat()
        existing = conn.execute(
            "SELECT * FROM checkins WHERE player_id = ? AND date = ?",
            (player_id, day_iso),
        ).fetchone()
        day_xp = xp_for_seconds(day_seconds)
        if existing is None:
            conn.execute(
                "INSERT INTO checkins "
                "(player_id, date, source, seconds, xp, checked_at, repaired_at, "
                "repair_cost, status) VALUES (?, ?, 'verified', ?, ?, ?, NULL, 0, 'verified')",
                (player_id, day_iso, day_seconds, day_xp, cal.iso_ts(now)),
            )
            return {
                "created": True,
                "source": "verified",
                "date": day_iso,
                "seconds": day_seconds,
                "xp": day_xp,
            }
        if existing["source"] == "verified":
            if int(existing["seconds"]) != day_seconds:
                conn.execute(
                    "UPDATE checkins SET seconds = ?, xp = ? "
                    "WHERE player_id = ? AND date = ? AND source = 'verified'",
                    (day_seconds, day_xp, player_id, day_iso),
                )
            return {
                "created": False,
                "source": "verified",
                "date": day_iso,
                "seconds": day_seconds,
                "xp": day_xp,
            }
        # A repair is final and must never be overwritten by a later arrival.
        return {
            "created": False,
            "source": "repaired",
            "date": day_iso,
            "seconds": int(existing["seconds"]),
            "xp": int(existing["xp"]),
        }

    def get_checkin(self, player_id: str, day: date | str) -> dict[str, Any] | None:
        day_iso = cal.iso_date(day)
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM checkins WHERE player_id = ? AND date = ?",
                (player_id, day_iso),
            ).fetchone()
            return _row_to_dict(row)

    def checkins_between(
        self, player_id: str, start: date | str, end_exclusive: date | str
    ) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM checkins WHERE player_id = ? AND date >= ? AND date < ? "
                "ORDER BY date",
                (player_id, cal.iso_date(start), cal.iso_date(end_exclusive)),
            ).fetchall()
            return [dict(row) for row in rows]

    def _recompute_streak(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        *,
        today: date,
        now: datetime,
    ) -> dict[str, Any]:
        rows = conn.execute(
            "SELECT date, source FROM checkins WHERE player_id = ? ORDER BY date",
            (player_id,),
        ).fetchall()
        runs: list[list[sqlite3.Row]] = []
        current_run: list[sqlite3.Row] = []
        previous: date | None = None
        for row in rows:
            row_date = date.fromisoformat(str(row["date"]))
            if previous is not None and row_date == previous + timedelta(days=1):
                current_run.append(row)
            else:
                if current_run:
                    runs.append(current_run)
                current_run = [row]
            previous = row_date
        if current_run:
            runs.append(current_run)

        longest = max((len(run) for run in runs), default=0)
        latest = date.fromisoformat(str(rows[-1]["date"])) if rows else None
        if latest is None or latest < today - timedelta(days=1):
            current = 0
            clean_current = 0
        elif runs:
            current = len(runs[-1])
            clean_current = sum(1 for row in runs[-1] if row["source"] == "verified")
        else:
            current = 0
            clean_current = 0

        old = conn.execute(
            "SELECT longest FROM streaks WHERE player_id = ?", (player_id,)
        ).fetchone()
        longest = max(longest, int(old["longest"]) if old else 0)
        conn.execute(
            "INSERT INTO streaks "
            "(player_id, current, longest, clean_current, last_checked_date, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(player_id) DO UPDATE SET "
            "current = excluded.current, longest = excluded.longest, "
            "clean_current = excluded.clean_current, "
            "last_checked_date = excluded.last_checked_date, "
            "updated_at = excluded.updated_at",
            (
                player_id,
                current,
                longest,
                clean_current,
                rows[-1]["date"] if rows else None,
                cal.iso_ts(now),
            ),
        )
        return {
            "current": current,
            "longest": longest,
            "clean_current": clean_current,
            "last_checked_date": rows[-1]["date"] if rows else None,
        }

    def get_streak(self, player_id: str) -> dict[str, Any] | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM streaks WHERE player_id = ?", (player_id,)
            ).fetchone()
            return _row_to_dict(row)

    def refresh_streak(
        self,
        player_id: str,
        *,
        today: date | datetime | str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Recompute the current streak from persisted check-ins."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        local_today = cal.parse_date(today) if today is not None else local_now.date()
        with self.transaction() as conn:
            self._get_player_with(conn, player_id)
            return self._recompute_streak(
                conn, player_id, today=local_today, now=local_now
            )

    def get_ember_balance(self, player_id: str) -> dict[str, Any] | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM ember_balance WHERE player_id = ?", (player_id,)
            ).fetchone()
            return _row_to_dict(row)

    def ember_ledger(self, player_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM ember_ledger WHERE player_id = ? ORDER BY id",
                (player_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def grant_daily_embers(
        self,
        player_id: str,
        day: date | datetime | str,
        *,
        as_of: datetime | str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Grant the weekly XP-derived embers at most once per local day."""

        day_date = cal.parse_date(day)
        week_date = cal.week_start(day_date)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        cutoff = cal.day_end_at(day_date)
        if as_of is not None:
            cutoff = min(cal.parse_datetime(as_of), cutoff)

        with self.transaction() as conn:
            self._get_player_with(conn, player_id)
            row = conn.execute(
                "SELECT COALESCE(SUM(seconds), 0) AS n FROM activity_events "
                "WHERE player_id = ? AND week_start = ? AND occurred_at < ?",
                (player_id, week_iso, cal.iso_ts(cutoff)),
            ).fetchone()
            week_seconds = int(row["n"])
            balance_row = conn.execute(
                "SELECT * FROM ember_balance WHERE player_id = ?", (player_id,)
            ).fetchone()
            if balance_row is None:
                balance = 0
                week_earned = 0
                conn.execute(
                    "INSERT INTO ember_balance "
                    "(player_id, balance, week_earned, week_start, updated_at) "
                    "VALUES (?, 0, 0, ?, ?)",
                    (player_id, week_iso, cal.iso_ts(local_now)),
                )
            else:
                balance = int(balance_row["balance"])
                week_earned = int(balance_row["week_earned"])
                if balance_row["week_start"] != week_iso and (
                    balance_row["week_start"] is None
                    or str(balance_row["week_start"]) < week_iso
                ):
                    week_earned = 0
                    conn.execute(
                        "UPDATE ember_balance SET week_earned = 0, week_start = ?, "
                        "updated_at = ? WHERE player_id = ?",
                        (week_iso, cal.iso_ts(local_now), player_id),
                    )

            earned = earned_embers_for_week(week_seconds)
            added = ember_grant_amount(
                week_seconds=week_seconds,
                granted_this_week=week_earned,
                balance=balance,
            )
            idempotency_key = f"ember-grant:{player_id}:{week_iso}:{day_date.isoformat()}"
            granted = 0
            if added > 0:
                new_balance = balance + added
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO ember_ledger "
                    "(player_id, week_start, delta, balance_after, reason, ref, "
                    "idempotency_key, created_at) VALUES (?, ?, ?, ?, 'weekly_xp', ?, ?, ?)",
                    (
                        player_id,
                        week_iso,
                        added,
                        new_balance,
                        f"{week_iso} week_xp={xp_for_seconds(week_seconds)}",
                        idempotency_key,
                        cal.iso_ts(local_now),
                    ),
                )
                if cursor.rowcount:
                    granted = added
                    balance = new_balance
                    week_earned += added
                    conn.execute(
                        "UPDATE ember_balance SET balance = ?, week_earned = ?, "
                        "week_start = ?, updated_at = ? WHERE player_id = ?",
                        (
                            balance,
                            week_earned,
                            week_iso,
                            cal.iso_ts(local_now),
                            player_id,
                        ),
                    )
            self._apply_daily_progression_with(
                conn, player_id, now=local_now
            )
            return {
                "player_id": player_id,
                "date": day_date.isoformat(),
                "week_start": week_iso,
                "week_seconds": week_seconds,
                "week_xp": xp_for_seconds(week_seconds),
                "earned_this_week": earned,
                "granted": granted,
                "balance": balance,
                "week_earned": week_earned,
                "idempotency_key": idempotency_key,
            }

    def settle_completed_days(
        self,
        now: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """Catch up daily ember settlement for completed days."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        today = local_now.date()
        yesterday = today - timedelta(days=1)
        current_week = cal.week_start(today)
        starts = [current_week]
        if today.weekday() == 0:
            # Sunday just closed; settle its ember grant before the new week.
            starts.insert(0, current_week - timedelta(days=7))
        output: list[dict[str, Any]] = []
        for player in self.list_players(active_only=True):
            joined = date.fromisoformat(player["joined_week"])
            for start in starts:
                start = max(start, joined)
                if yesterday < start:
                    continue
                day = start
                while day <= yesterday:
                    if self.get_week(day) is None:
                        self.ensure_week(day)
                    output.append(
                        self.grant_daily_embers(
                            player["id"],
                            day,
                            as_of=cal.day_end_at(day) - timedelta(seconds=1),
                            now=local_now,
                        )
                    )
                    day += timedelta(days=1)
        return output

    def repair_checkin(
        self,
        player_id: str,
        day: date | datetime | str,
        *,
        idempotency_key: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        if not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        day_date = cal.parse_date(day)
        day_iso = day_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        ref = f"{player_id}:{day_iso}"

        with self.transaction() as conn:
            self._get_player_with(conn, player_id)
            prior = conn.execute(
                "SELECT * FROM ember_ledger WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if prior is not None:
                if prior["reason"] != "repair" or prior["ref"] != ref:
                    raise DuplicateIdempotencyKey(
                        "idempotency_key already used for a different request"
                    )
                streak = conn.execute(
                    "SELECT * FROM streaks WHERE player_id = ?", (player_id,)
                ).fetchone()
                return {
                    "repaired": True,
                    "duplicate": True,
                    "player_id": player_id,
                    "date": day_iso,
                    "embers_spent": -int(prior["delta"]),
                    "balance": int(prior["balance_after"]),
                    "current_streak": int(streak["current"]) if streak else 0,
                    "clean_current": int(streak["clean_current"]) if streak else 0,
                    "history_marker": "repaired",
                }

            valid, reason = is_valid_repair_day(
                day=day_date, today=local_now.date(), now=local_now
            )
            if not valid:
                raise RepairRejected(reason, f"repair date rejected: {reason}")

            existing = conn.execute(
                "SELECT * FROM checkins WHERE player_id = ? AND date = ?",
                (player_id, day_iso),
            ).fetchone()
            if existing is not None:
                raise RepairRejected(
                    "already_checked_in", f"{day_iso} already has a check-in"
                )

            day_seconds = self._day_seconds(conn, player_id, day_date)
            if day_seconds == 0:
                raise RepairRejected("zero_xp", f"{day_iso} has no activity")
            if day_seconds >= CHECKIN_SECONDS:
                raise RepairRejected(
                    "already_checked_in",
                    f"{day_iso} already reached the check-in threshold",
                )

            balance_row = conn.execute(
                "SELECT * FROM ember_balance WHERE player_id = ?", (player_id,)
            ).fetchone()
            balance = int(balance_row["balance"]) if balance_row else 0
            if balance < 1:
                raise RepairRejected(
                    "insufficient_embers", "an ember is required to repair"
                )

            conn.execute(
                "INSERT INTO checkins "
                "(player_id, date, source, seconds, xp, checked_at, repaired_at, "
                "repair_cost, status) VALUES (?, ?, 'repaired', ?, ?, ?, ?, 1, 'repaired')",
                (
                    player_id,
                    day_iso,
                    day_seconds,
                    xp_for_seconds(day_seconds),
                    cal.iso_ts(local_now),
                    cal.iso_ts(local_now),
                ),
            )
            new_balance = balance - 1
            conn.execute(
                "UPDATE ember_balance SET balance = ?, updated_at = ? WHERE player_id = ?",
                (new_balance, cal.iso_ts(local_now), player_id),
            )
            conn.execute(
                "INSERT INTO ember_ledger "
                "(player_id, week_start, delta, balance_after, reason, ref, "
                "idempotency_key, created_at) "
                "VALUES (?, ?, -1, ?, 'repair', ?, ?, ?)",
                (
                    player_id,
                    cal.week_start(day_date).isoformat(),
                    new_balance,
                    ref,
                    idempotency_key,
                    cal.iso_ts(local_now),
                ),
            )
            streak = self._recompute_streak(
                conn, player_id, today=local_now.date(), now=local_now
            )
            self._apply_daily_progression_with(
                conn, player_id, now=local_now
            )
            return {
                "repaired": True,
                "duplicate": False,
                "player_id": player_id,
                "date": day_iso,
                "seconds": day_seconds,
                "xp": xp_for_seconds(day_seconds),
                "embers_spent": 1,
                "balance": new_balance,
                "current_streak": streak["current"],
                "clean_current": streak["clean_current"],
                "history_marker": "repaired",
            }
