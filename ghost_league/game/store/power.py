"""Power rating derived from recent weekly XP percentiles.

Power is a display-only number on a 0..2000 scale.  It never feeds ranking,
grouping, promotion, or settlement.  The calculation is deliberately kept as
one pure function over a SQLite connection so the hourly refresh, weekly final
history, and tests all use exactly the same formula.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from typing import Any

from .. import calendar as cal

POWER_WINDOW_WEEKS = 4
POWER_WEIGHTS = (0.4, 0.3, 0.2, 0.1)
POWER_MIN = 0
POWER_MAX = 2000


def _window_weeks(week_start: Any) -> list[str]:
    """Return four ISO week starts, newest first, ending at ``week_start``."""

    start = cal.week_start(week_start)
    return [
        cal.iso_date(start - timedelta(days=7 * offset))
        for offset in range(POWER_WINDOW_WEEKS)
    ]


def power_from_percentile(percentile: float) -> int:
    """Map a weighted percentile (0..1) onto the 0..2000 integer scale."""

    value = round(1000 + 1000 * (2 * float(percentile) - 1))
    return max(POWER_MIN, min(POWER_MAX, int(value)))


def compute_power_snapshot(
    conn: sqlite3.Connection,
    now: datetime | str | None = None,
    week_start: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute every player's power for the window ending at ``week_start``.

    The four most recent natural weeks are considered, newest first.  A week is
    available only when it has at least one ``weekly_scores`` row; the current
    week's live XP is therefore used as-is.  Each player is weighted over the
    weeks where that player actually has a row, and the available weights are
    renormalized, so one week produces a power immediately rather than a
    provisional placeholder.
    """

    local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
    anchor = cal.week_start(week_start if week_start is not None else local_now)
    weeks = _window_weeks(anchor)

    # player_id -> list of (week_index, percentile, weekly_xp)
    per_player: dict[str, list[tuple[int, float, int]]] = {}
    for index, week_iso in enumerate(weeks):
        rows = conn.execute(
            "SELECT player_id, xp FROM weekly_scores WHERE week_start = ?",
            (week_iso,),
        ).fetchall()
        if not rows:
            continue
        total = len(rows)
        xp_values = sorted(int(row["xp"]) for row in rows)
        for row in rows:
            player_id = str(row["player_id"])
            xp = int(row["xp"])
            less_count = bisect_left(xp_values, xp)
            equal_count = bisect_right(xp_values, xp) - less_count
            percentile = (less_count + equal_count / 2) / total
            per_player.setdefault(player_id, []).append(
                (index, percentile, xp)
            )

    has_players = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'players'"
    ).fetchone()
    player_ids = (
        {str(row["id"]) for row in conn.execute("SELECT id FROM players")}
        if has_players is not None
        else set()
    )
    player_ids.update(per_player)

    snapshot: dict[str, dict[str, Any]] = {}
    for player_id in sorted(player_ids):
        entries = per_player.get(player_id)
        if not entries:
            snapshot[player_id] = {
                "power": None,
                "percentile": None,
                "raw_xp": 0,
                "weeks_used": 0,
                "provisional": True,
            }
            continue
        weight_sum = sum(POWER_WEIGHTS[index] for index, _, _ in entries)
        weighted = sum(
            POWER_WEIGHTS[index] * percentile
            for index, percentile, _ in entries
        )
        percentile = weighted / weight_sum
        # Entries are appended newest week first, so the first one is the
        # freshest raw XP available for this player.
        raw_xp = entries[0][2]
        snapshot[player_id] = {
            "power": power_from_percentile(percentile),
            "percentile": percentile,
            "raw_xp": raw_xp,
            "weeks_used": len(entries),
            "provisional": False,
        }
    return snapshot


class PowerMixin:
    """Refresh current power and persist final per-week power history."""

    def recompute_power(
        self,
        now: datetime | str | None = None,
        *,
        week_start: Any | None = None,
    ) -> dict[str, Any]:
        """Refresh ``players.power*`` from the live weekly scores.

        This writes only the current player projection.  It never writes
        ``player_power_history``; that table is reserved for settled weeks.
        """

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        anchor = cal.week_start(
            week_start if week_start is not None else local_now
        )
        week_iso = cal.iso_date(anchor)
        updated_at = cal.iso_ts(local_now)
        updated = 0
        rated = 0
        with self.transaction() as conn:
            snapshot = compute_power_snapshot(
                conn, now=local_now, week_start=anchor
            )
            for player_id, data in snapshot.items():
                provisional = 1 if data["provisional"] else 0
                if not data["provisional"]:
                    rated += 1
                cursor = conn.execute(
                    "UPDATE players SET power = ?, power_percentile = ?, "
                    "power_week = ?, power_updated_at = ?, "
                    "power_provisional = ? WHERE id = ?",
                    (
                        data["power"],
                        data["percentile"],
                        week_iso,
                        updated_at,
                        provisional,
                        player_id,
                    ),
                )
                updated += cursor.rowcount
        return {
            "week_start": week_iso,
            "updated_at": updated_at,
            "players": updated,
            "rated": rated,
            "provisional": updated - rated,
        }

    def write_power_history(
        self,
        week_start: Any,
        *,
        now: datetime | str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """Write the final power snapshot for one settled week.

        Rows are immutable once written: re-running settlement safely fills in
        missing rows for older databases but never changes a final value.
        """

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        anchor = cal.week_start(week_start)
        week_iso = cal.iso_date(anchor)
        computed_at = cal.iso_ts(local_now)
        if conn is not None:
            return self._write_power_history_with(
                conn, week_iso, computed_at=computed_at, now=local_now
            )
        with self.transaction() as tx:
            return self._write_power_history_with(
                tx, week_iso, computed_at=computed_at, now=local_now
            )

    @staticmethod
    def _write_power_history_with(
        conn: sqlite3.Connection,
        week_iso: str,
        *,
        computed_at: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        snapshot = compute_power_snapshot(conn, now=now, week_start=week_iso)
        rows: list[dict[str, Any]] = []
        for player_id, data in snapshot.items():
            if data["power"] is None:
                continue
            conn.execute(
                "INSERT INTO player_power_history "
                "(week_start, player_id, power, percentile, raw_xp, "
                "weeks_used, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(week_start, player_id) DO NOTHING",
                (
                    week_iso,
                    player_id,
                    data["power"],
                    data["percentile"],
                    data["raw_xp"],
                    data["weeks_used"],
                    computed_at,
                ),
            )
            rows.append(
                {
                    "week_start": week_iso,
                    "player_id": player_id,
                    "power": data["power"],
                    "percentile": data["percentile"],
                    "raw_xp": data["raw_xp"],
                    "weeks_used": data["weeks_used"],
                    "computed_at": computed_at,
                }
            )
        return rows
