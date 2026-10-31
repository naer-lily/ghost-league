"""Week locking, settlement, standings, and history."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .. import calendar as cal
from ..rules import (
    CHECKIN_SECONDS,
    GameError,
    group_movement,
    rank_scores,
    xp_for_seconds,
)

class SettlementMixin:
    """Settle a week and expose its read-only standings/history views."""

    def standings(
        self,
        week: date | datetime | str,
        *,
        group_id: int | None = None,
        now: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self._reader() as conn:
            if group_id is None:
                row = conn.execute(
                    "SELECT id FROM groups WHERE week_start = ? ORDER BY id LIMIT 1",
                    (week_iso,),
                ).fetchone()
                if row is None:
                    return []
                group_id = int(row["id"])
            rows = conn.execute(
                "SELECT gm.player_id, gm.is_human, p.kind, p.display_name, "
                "COALESCE(ws.seconds, 0) AS seconds, COALESCE(ws.xp, 0) AS xp "
                "FROM group_members gm JOIN players p ON p.id = gm.player_id "
                "LEFT JOIN weekly_scores ws ON ws.week_start = ? "
                "AND ws.player_id = gm.player_id "
                "WHERE gm.group_id = ?",
                (week_iso, group_id),
            ).fetchall()
            scores = [
                {
                    "player_id": str(row["player_id"]),
                    "seconds": int(row["seconds"]),
                    "xp": int(row["xp"]),
                }
                for row in rows
            ]
            ordered = rank_scores(
                [ScoreRowLike(**score) for score in scores]  # type: ignore[arg-type]
            )
            rank_by_player = {
                row.player_id: index + 1 for index, row in enumerate(ordered)
            }
            output: list[dict[str, Any]] = []
            for row in sorted(
                rows, key=lambda r: (-int(r["xp"]), str(r["player_id"]))
            ):
                player_id = str(row["player_id"])
                checkin = conn.execute(
                    "SELECT source FROM checkins WHERE player_id = ? AND date = ?",
                    (player_id, local_now.date().isoformat()),
                ).fetchone()
                streak = conn.execute(
                    "SELECT current FROM streaks WHERE player_id = ?", (player_id,)
                ).fetchone()
                output.append(
                    {
                        "rank": rank_by_player[player_id],
                        "player_id": player_id,
                        "display_name": str(row["display_name"]),
                        "kind": str(row["kind"]),
                        "is_ai": str(row["kind"]) == "ai",
                        "seconds": int(row["seconds"]),
                        "xp": int(row["xp"]),
                        "checkin": str(checkin["source"]) if checkin else None,
                        "streak": int(streak["current"]) if streak else 0,
                    }
                )
            return output

    def player_status(
        self,
        player_id: str,
        *,
        week: date | datetime | str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        week_date = cal.week_start(week or local_now)
        week_iso = week_date.isoformat()
        with self._reader() as conn:
            player = self._get_player_with(conn, player_id)
            group = conn.execute(
                "SELECT g.* FROM groups g JOIN group_members gm ON gm.group_id = g.id "
                "WHERE g.week_start = ? AND gm.player_id = ? "
                "ORDER BY g.id DESC LIMIT 1",
                (week_iso, player_id),
            ).fetchone()
            score = conn.execute(
                "SELECT * FROM weekly_scores WHERE week_start = ? AND player_id = ?",
                (week_iso, player_id),
            ).fetchone()
            today_seconds = self._day_seconds(conn, player_id, local_now.date())
            checkin = conn.execute(
                "SELECT source FROM checkins WHERE player_id = ? AND date = ?",
                (player_id, local_now.date().isoformat()),
            ).fetchone()
            streak = conn.execute(
                "SELECT * FROM streaks WHERE player_id = ?", (player_id,)
            ).fetchone()
            ember = conn.execute(
                "SELECT * FROM ember_balance WHERE player_id = ?", (player_id,)
            ).fetchone()
            lifetime = conn.execute(
                "SELECT COALESCE(SUM(xp), 0) AS total FROM weekly_scores "
                "WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        standings = (
            self.standings(
                week_date, group_id=int(group["id"]), now=local_now
            )
            if group is not None
            else []
        )
        rank = next(
            (row["rank"] for row in standings if row["player_id"] == player_id), None
        )
        return {
            "player": player,
            "week_start": week_iso,
            "group": dict(group) if group else None,
            "group_size": len(standings),
            "tier": str(group["tier"]) if group else None,
            "rank": rank,
            "seconds": int(score["seconds"]) if score else 0,
            "xp": int(score["xp"]) if score else 0,
            "lifetime_xp": int(lifetime["total"]) if lifetime else 0,
            "today_seconds": today_seconds,
            "today_xp": xp_for_seconds(today_seconds),
            "required_xp": CHECKIN_SECONDS // 6,
            "checkin": str(checkin["source"]) if checkin else None,
            "streak": dict(streak) if streak else {
                "current": 0,
                "longest": 0,
                "clean_current": 0,
                "last_checked_date": None,
            },
            "ember_balance": int(ember["balance"]) if ember else 0,
            "ember_cap": 3,
        }

    def history(self, player_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT * FROM weekly_results WHERE player_id = ? "
            "ORDER BY week_start DESC"
        )
        params: list[Any] = [player_id]
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            sql += " LIMIT ?"
            params.append(limit)
        with self._reader() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    **dict(row),
                    "promoted": bool(row["promoted"]),
                    "demoted": bool(row["demoted"]),
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------
    def settle_week(
        self,
        week: date | datetime | str,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        week_end = cal.week_end_at(week_date)
        if local_now < week_end:
            raise GameError(f"week {week_iso} has not ended yet")
        settled_at = cal.iso_ts(local_now)

        with self.transaction() as conn:
            week_row = conn.execute(
                "SELECT * FROM weeks WHERE week_start = ?", (week_iso,)
            ).fetchone()
            if week_row is not None and week_row["status"] == "settled":
                self._apply_weekly_progression_with(
                    conn, week_iso, now=local_now
                )
                self._sync_weekly_feed_with(
                    conn, week_iso, now=local_now
                )
                results = conn.execute(
                    "SELECT * FROM weekly_results WHERE week_start = ? "
                    "ORDER BY group_id, rank",
                    (week_iso,),
                ).fetchall()
                return {
                    "week_start": week_iso,
                    "already_settled": True,
                    "results": [
                        {
                            **dict(row),
                            "promoted": bool(row["promoted"]),
                            "demoted": bool(row["demoted"]),
                        }
                        for row in results
                    ],
                }

            groups = conn.execute(
                "SELECT * FROM groups WHERE week_start = ? ORDER BY id",
                (week_iso,),
            ).fetchall()
            if not groups:
                # No real group exists: return empty without fabricating a week.
                return {
                    "week_start": week_iso,
                    "already_settled": False,
                    "results": [],
                }
            self._ensure_week_with(conn, week_iso, "locked")

            # Settle every group independently.  Rank is local to the group,
            # and that group's quota decides its own promotions/demotions;
            # there is deliberately no tier-wide ranking.
            results: list[dict[str, Any]] = []
            for group in groups:
                group_id = int(group["id"])
                tier = str(group["tier"])
                members = conn.execute(
                    "SELECT gm.player_id FROM group_members gm "
                    "WHERE gm.group_id = ? ORDER BY gm.player_id",
                    (group_id,),
                ).fetchall()
                if not members:
                    continue
                score_rows = []
                for member in members:
                    pid = str(member["player_id"])
                    seconds_row = conn.execute(
                        "SELECT COALESCE(SUM(seconds), 0) AS n FROM activity_events "
                        "WHERE player_id = ? AND week_start = ?",
                        (pid, week_iso),
                    ).fetchone()
                    seconds = int(seconds_row["n"])
                    xp = xp_for_seconds(seconds)
                    conn.execute(
                        "INSERT INTO weekly_scores "
                        "(week_start, player_id, group_id, seconds, xp) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(week_start, player_id) DO UPDATE SET "
                        "group_id = excluded.group_id, seconds = excluded.seconds, "
                        "xp = excluded.xp",
                        (week_iso, pid, group_id, seconds, xp),
                    )
                    score_rows.append({"player_id": pid, "seconds": seconds, "xp": xp})
                ordered = sorted(
                    score_rows, key=lambda row: (-row["seconds"], row["player_id"])
                )
                group_size = len(ordered)
                for rank, score in enumerate(ordered, start=1):
                    promoted, demoted = group_movement(rank, tier, group_size)
                    conn.execute(
                        "UPDATE weekly_scores SET group_id = ?, locked_at = ?, "
                        "rank = ?, promoted = ?, demoted = ? "
                        "WHERE week_start = ? AND player_id = ?",
                        (
                            group_id,
                            settled_at,
                            rank,
                            1 if promoted else 0,
                            1 if demoted else 0,
                            week_iso,
                            score["player_id"],
                        ),
                    )
                    checkin_row = conn.execute(
                        "SELECT "
                        "SUM(CASE WHEN source = 'repaired' THEN 1 ELSE 0 END) AS repaired, "
                        "SUM(CASE WHEN source = 'verified' THEN 1 ELSE 0 END) AS clean "
                        "FROM checkins WHERE player_id = ? AND date >= ? AND date < ?",
                        (
                            score["player_id"],
                            week_iso,
                            (week_date + timedelta(days=7)).isoformat(),
                        ),
                    ).fetchone()
                    repaired_days = int(checkin_row["repaired"] or 0)
                    clean_checkins = int(checkin_row["clean"] or 0)
                    conn.execute(
                        "INSERT OR IGNORE INTO weekly_results "
                        "(week_start, player_id, group_id, tier, rank, xp, promoted, "
                        "demoted, repaired_days, clean_checkins, settled_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            week_iso,
                            score["player_id"],
                            group_id,
                            tier,
                            rank,
                            score["xp"],
                            1 if promoted else 0,
                            1 if demoted else 0,
                            repaired_days,
                            clean_checkins,
                            settled_at,
                        ),
                    )
                    results.append(
                        {
                            "week_start": week_iso,
                            "player_id": score["player_id"],
                            "group_id": group_id,
                            "tier": tier,
                            "rank": rank,
                            "xp": score["xp"],
                            "promoted": promoted,
                            "demoted": demoted,
                            "repaired_days": repaired_days,
                            "clean_checkins": clean_checkins,
                            "settled_at": settled_at,
                        }
                    )
            results.sort(key=lambda row: (int(row["group_id"]), int(row["rank"])))
            conn.execute(
                "UPDATE weeks SET status = 'settled', settled_at = ? "
                "WHERE week_start = ?",
                (settled_at, week_iso),
            )
            self._apply_weekly_progression_with(
                conn, week_iso, now=local_now
            )
            self._sync_weekly_feed_with(
                conn, week_iso, now=local_now
            )
            return {
                "week_start": week_iso,
                "already_settled": False,
                "results": results,
            }


class ScoreRowLike:
    """Small adapter so standings can reuse the pure ranking helper."""

    __slots__ = ("player_id", "seconds", "xp")

    def __init__(self, *, player_id: str, seconds: int, xp: int) -> None:
        self.player_id = player_id
        self.seconds = seconds
        self.xp = xp
