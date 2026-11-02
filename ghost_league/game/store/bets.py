"""Weekly/daily/group rival bets with a per-bet free stake.

Every bet carries up to 20 free principal, so only ``paid_stake`` is taken
from the diamond wallet when the bet is placed.  A win pays on the full
``stake``; a draw/void refunds only the paid part.  Every payout uses a key
derived from the bet id, so replaying settlement can never pay twice.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from .. import calendar as cal
from ..rival import (
    FREE_BET_STAKE,
    GROUP_ODDS,
    GROUP_TARGET_RANK,
    MAX_PAID_STAKE,
    MIN_PAID_STAKE,
    BetAlreadyPlaced,
    BetRejected,
    BetWindowClosed,
    RivalUnavailable,
    bet_odds,
    daily_bet_locks_at,
    daily_bet_settles_at,
    group_bet_settles_at,
    payout_for_win,
    target_in_range,
    wager_result,
    weekly_bet_locks_at,
)
from ..rules import xp_for_seconds


class BetsMixin:
    """Rival bet placement and the two settlement passes."""

    @staticmethod
    def _bet_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": int(data["id"]),
            "player_id": str(data["player_id"]),
            "kind": str(data["kind"]),
            "period_key": str(data["period_key"]),
            "rival_id": str(data["rival_id"]),
            "stake": int(data["stake"]),
            "free_stake": int(data["free_stake"]),
            "paid_stake": int(data["paid_stake"]),
            "target_margin": int(data["target_margin"]),
            "odds": float(data["odds"]),
            "status": str(data["status"]),
            "placed_at": str(data["placed_at"]),
            "locked_at": data["locked_at"],
            "settled_at": data["settled_at"],
            "payout": int(data["payout"]),
            "result_diff": (
                int(data["result_diff"])
                if data["result_diff"] is not None
                else None
            ),
        }

    @staticmethod
    def _group_bet_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": int(data["id"]),
            "player_id": str(data["player_id"]),
            "kind": "group",
            "period_key": str(data["week_start"]),
            "rival_id": None,
            "stake": int(data["stake"]),
            "free_stake": int(data["free_stake"]),
            "paid_stake": int(data["paid_stake"]),
            "target_rank": GROUP_TARGET_RANK,
            "target_margin": 0,
            "odds": float(data["odds"]),
            "status": str(data["status"]),
            "placed_at": str(data["placed_at"]),
            "locked_at": None,
            "settled_at": data["settled_at"],
            "payout": int(data["payout"]),
            "result_diff": None,
            "group_id": int(data["group_id"]),
            "group_rank": (
                int(data["group_rank"])
                if data["group_rank"] is not None
                else None
            ),
        }

    @staticmethod
    def _bet_row_with(
        conn: sqlite3.Connection,
        player_id: str,
        kind: str,
        period_key: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM bets WHERE player_id = ? AND kind = ? "
            "AND period_key = ?",
            (player_id, kind, period_key),
        ).fetchone()

    @staticmethod
    def _group_bet_row_with(
        conn: sqlite3.Connection,
        player_id: str,
        week_iso: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM group_bets WHERE player_id = ? AND week_start = ?",
            (player_id, week_iso),
        ).fetchone()

    def _bets_for_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        week_iso: str,
        day_iso: str,
    ) -> dict[str, dict[str, Any] | None]:
        weekly = self._bet_row_with(conn, player_id, "weekly", week_iso)
        daily = self._bet_row_with(conn, player_id, "daily", day_iso)
        group = self._group_bet_row_with(conn, player_id, week_iso)
        return {
            "weekly": self._bet_payload(weekly) if weekly is not None else None,
            "daily": self._bet_payload(daily) if daily is not None else None,
            "group": (
                self._group_bet_payload(group) if group is not None else None
            ),
        }

    def bets_for(
        self,
        player_id: str,
        now: datetime | str | None = None,
    ) -> dict[str, dict[str, Any] | None]:
        """Return this week's weekly/group bet and today's daily bet."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        week_iso = cal.iso_date(cal.week_start(local_now))
        day_iso = local_now.date().isoformat()
        with self._reader() as conn:
            return self._bets_for_with(conn, player_id, week_iso, day_iso)

    def has_unsettled_daily_bets(self, day: date | datetime | str) -> bool:
        """True when ``day`` still has a placed daily bet.

        The scheduler uses this to catch up overdue days without creating
        no-op runs for days that never had a bet.
        """

        day_iso = cal.iso_date(day)
        with self._reader() as conn:
            row = conn.execute(
                "SELECT 1 FROM bets WHERE kind = 'daily' AND period_key = ? "
                "AND status = 'placed' LIMIT 1",
                (day_iso,),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    def place_bet(
        self,
        player_id: str,
        kind: str,
        paid_stake: int = 0,
        target_margin: int | None = None,
        now: datetime | str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be non-empty")
        if kind not in {"weekly", "daily", "group"}:
            raise BetRejected("invalid_kind", "下注类型不合法")
        if isinstance(paid_stake, bool) or not isinstance(paid_stake, int):
            raise BetRejected(
                "invalid_stake", "自付钻石必须是 0 到 500 的整数"
            )
        if not MIN_PAID_STAKE <= paid_stake <= MAX_PAID_STAKE:
            raise BetRejected(
                "invalid_stake", "自付钻石必须在 0 到 500 之间"
            )
        if isinstance(target_margin, bool) or (
            target_margin is not None and not isinstance(target_margin, int)
        ):
            raise BetRejected("invalid_target", "目标差值不合法")

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        week_date = cal.week_start(local_now)
        week_iso = week_date.isoformat()
        day_iso = local_now.date().isoformat()
        period_key = week_iso if kind != "daily" else day_iso
        resolved_stake = FREE_BET_STAKE + paid_stake
        bet_key = (
            f"group-bet:{player_id}:{week_iso}:{request_id}"
            if kind == "group"
            else f"bet:{player_id}:{kind}:{period_key}:{request_id}"
        )

        with self.transaction() as conn:
            player = self._get_player_with(conn, player_id)  # type: ignore[attr-defined]
            if str(player["kind"]) != "human":
                raise BetRejected("human_only", "只有真人可以下注")

            if kind == "group":
                if target_margin not in (None, 0):
                    raise BetRejected("invalid_target", "组注不需要目标差值")
                existing_group = self._group_bet_row_with(
                    conn, player_id, week_iso
                )
                if existing_group is not None:
                    if str(existing_group["idempotency_key"]) == bet_key:
                        return self._group_bet_payload(existing_group)
                    raise BetAlreadyPlaced("本周已经下过组注")
                keyed_group = conn.execute(
                    "SELECT * FROM group_bets WHERE idempotency_key = ?",
                    (bet_key,),
                ).fetchone()
                if keyed_group is not None:
                    return self._group_bet_payload(keyed_group)

                if local_now >= weekly_bet_locks_at(week_date):
                    raise BetWindowClosed("组注已截止")
                group = conn.execute(
                    "SELECT g.id AS group_id FROM groups g "
                    "JOIN group_members gm ON gm.group_id = g.id "
                    "WHERE g.week_start = ? AND gm.player_id = ? "
                    "ORDER BY g.id DESC LIMIT 1",
                    (week_iso, player_id),
                ).fetchone()
                if group is None:
                    raise BetRejected(
                        "no_group", "本周还没有分组，暂时不能下组注"
                    )

                if paid_stake > 0:
                    self._debit_diamonds_with(  # type: ignore[attr-defined]
                        conn,
                        player_id=player_id,
                        amount=paid_stake,
                        reason="group_bet_stake",
                        ref_type="group_bet",
                        ref_id=week_iso,
                        idempotency_key=f"group-bet-stake:{bet_key}",
                        now=local_now,
                        create_for_unknown=False,
                    )
                now_iso = cal.iso_ts(local_now)
                cursor = conn.execute(
                    "INSERT INTO group_bets "
                    "(player_id, week_start, group_id, stake, free_stake, "
                    "paid_stake, odds, status, placed_at, settled_at, payout, "
                    "group_rank, idempotency_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'placed', ?, NULL, 0, "
                    "NULL, ?)",
                    (
                        player_id,
                        week_iso,
                        int(group["group_id"]),
                        resolved_stake,
                        FREE_BET_STAKE,
                        paid_stake,
                        GROUP_ODDS,
                        now_iso,
                        bet_key,
                    ),
                )
                group_bet_id = int(cursor.lastrowid)
                stored_group = conn.execute(
                    "SELECT * FROM group_bets WHERE id = ?", (group_bet_id,)
                ).fetchone()
                return self._group_bet_payload(stored_group)

            if target_margin is None:
                raise BetRejected(
                    "invalid_target", "请选择目标差值"
                )
            if target_margin < 0:
                raise BetRejected(
                    "invalid_target", "目标差值不能为负数"
                )

            existing = self._bet_row_with(conn, player_id, kind, period_key)
            if existing is not None:
                if str(existing["idempotency_key"]) == bet_key:
                    return self._bet_payload(existing)
                raise BetAlreadyPlaced(
                    "本周已经下注" if kind == "weekly" else "今天已经下注"
                )
            keyed = conn.execute(
                "SELECT * FROM bets WHERE idempotency_key = ?", (bet_key,)
            ).fetchone()
            if keyed is not None:
                return self._bet_payload(keyed)

            assignment = conn.execute(
                "SELECT rival_id FROM rival_assignments "
                "WHERE week_start = ? AND player_id = ?",
                (week_iso, player_id),
            ).fetchone()
            if assignment is None:
                raise RivalUnavailable()

            if kind == "weekly":
                if local_now >= weekly_bet_locks_at(week_date):
                    raise BetWindowClosed("周注已截止")
            elif local_now >= daily_bet_locks_at(local_now.date()):
                raise BetWindowClosed("日注已截止")

            rival_id = str(assignment["rival_id"])
            rival = self._rival_player_row_with(  # type: ignore[attr-defined]
                conn, week_iso, rival_id, day_iso
            )
            projection = self._projection_with(  # type: ignore[attr-defined]
                conn, local_now, rival
            )
            assert projection is not None
            week_estimate = int(projection["rival_week_estimate"])
            day_estimate = int(projection["rival_today_estimate"])
            if not target_in_range(
                kind,
                target_margin,
                week_estimate,
                day_estimate,
            ):
                raise BetRejected(
                    "invalid_target", "目标差值超出可选范围"
                )
            odds = bet_odds(
                kind,
                target_margin,
                week_estimate,
                day_estimate,
                int(player["power"] or 0),
                int(rival["power"] or 0),
            )

            if paid_stake > 0:
                self._debit_diamonds_with(  # type: ignore[attr-defined]
                    conn,
                    player_id=player_id,
                    amount=paid_stake,
                    reason="bet_stake",
                    ref_type="bet",
                    ref_id=f"{kind}:{period_key}",
                    idempotency_key=f"bet-stake:{bet_key}",
                    now=local_now,
                    create_for_unknown=False,
                )
            now_iso = cal.iso_ts(local_now)
            cursor = conn.execute(
                "INSERT INTO bets "
                "(player_id, kind, period_key, rival_id, stake, free_stake, "
                "paid_stake, target_margin, odds, status, placed_at, "
                "locked_at, settled_at, payout, result_diff, "
                "idempotency_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'placed', ?, ?, NULL, "
                "0, NULL, ?)",
                (
                    player_id,
                    kind,
                    period_key,
                    rival_id,
                    resolved_stake,
                    FREE_BET_STAKE,
                    paid_stake,
                    target_margin,
                    odds,
                    now_iso,
                    now_iso,
                    bet_key,
                ),
            )
            bet_id = int(cursor.lastrowid)
            stored = conn.execute(
                "SELECT * FROM bets WHERE id = ?", (bet_id,)
            ).fetchone()
            return self._bet_payload(stored)

    # ------------------------------------------------------------------
    # Settlement helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _checkin_xp_at(
        conn: sqlite3.Connection,
        player_id: str,
        day: date,
        cutoff: datetime,
    ) -> int:
        """Return the check-in XP that was visible at ``cutoff``.

        ``checkins.xp`` is the real daily XP snapshot, but its row keeps the
        first check-in timestamp while its XP is updated later.  For a late
        settlement we therefore reconstruct a verified day from the activity
        events strictly before 22:30.  Repaired days are final and are used as
        stored.
        """

        day_iso = cal.iso_date(day)
        row = conn.execute(
            "SELECT xp, source, checked_at FROM checkins "
            "WHERE player_id = ? AND date = ?",
            (player_id, day_iso),
        ).fetchone()
        if row is None:
            return 0
        if str(row["source"]) == "repaired":
            return int(row["xp"])
        start_iso = cal.iso_ts(cal.day_start_at(day))
        cutoff_iso = cal.iso_ts(cutoff)
        events = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(seconds), 0) AS seconds "
            "FROM activity_events WHERE player_id = ? "
            "AND occurred_at >= ? AND occurred_at < ?",
            (player_id, start_iso, cutoff_iso),
        ).fetchone()
        if int(events["n"]) > 0:
            return xp_for_seconds(int(events["seconds"]))
        try:
            checked_at = cal.parse_datetime(str(row["checked_at"]))
        except (TypeError, ValueError):
            checked_at = None
        if checked_at is not None and checked_at > cutoff:
            return 0
        return int(row["xp"])

    @staticmethod
    def _weekly_xp_with(
        conn: sqlite3.Connection, week_iso: str, player_id: str
    ) -> int:
        row = conn.execute(
            "SELECT xp FROM weekly_scores WHERE week_start = ? "
            "AND player_id = ?",
            (week_iso, player_id),
        ).fetchone()
        return int(row["xp"]) if row is not None else 0

    def _credit_payout_with(
        self,
        conn: sqlite3.Connection,
        *,
        bet_id: int,
        player_id: str,
        payout: int,
        now: datetime,
    ) -> None:
        if payout <= 0:
            return
        self._credit_diamonds_with(  # type: ignore[attr-defined]
            conn,
            player_id=player_id,
            amount=int(payout),
            reason="bet_payout",
            ref_type="bet",
            ref_id=str(bet_id),
            idempotency_key=f"bet-payout:{bet_id}",
            now=now,
        )

    def _credit_group_payout_with(
        self,
        conn: sqlite3.Connection,
        *,
        group_bet_id: int,
        player_id: str,
        payout: int,
        now: datetime,
    ) -> None:
        if payout <= 0:
            return
        self._credit_diamonds_with(  # type: ignore[attr-defined]
            conn,
            player_id=player_id,
            amount=int(payout),
            reason="group_bet_payout",
            ref_type="group_bet",
            ref_id=str(group_bet_id),
            idempotency_key=f"group-bet-payout:{group_bet_id}",
            now=now,
        )

    # ------------------------------------------------------------------
    # Daily settlement
    # ------------------------------------------------------------------
    def settle_daily_bets(
        self,
        day: date | datetime | str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        day_date = cal.parse_date(day)
        day_iso = day_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        settle_at = daily_bet_settles_at(day_date)
        if local_now < settle_at:
            return {
                "day": day_iso,
                "status": "skipped",
                "reason": "before_settlement",
                "settled": 0,
                "results": [],
            }

        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bets WHERE kind = 'daily' AND period_key = ? "
                "AND status = 'placed' ORDER BY id",
                (day_iso,),
            ).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                bet_id = int(row["id"])
                player_id = str(row["player_id"])
                rival_id = str(row["rival_id"])
                my_xp = self._checkin_xp_at(
                    conn, player_id, day_date, settle_at
                )
                rival_xp = self._checkin_xp_at(
                    conn, rival_id, day_date, settle_at
                )
                diff = my_xp - rival_xp
                target = int(row["target_margin"])
                status = wager_result(diff, target)
                if status == "won":
                    payout = payout_for_win(
                        int(row["stake"]), float(row["odds"])
                    )
                elif status == "void":
                    payout = int(row["paid_stake"])
                else:
                    payout = 0
                cursor = conn.execute(
                    "UPDATE bets SET status = ?, settled_at = ?, "
                    "payout = ?, result_diff = ? "
                    "WHERE id = ? AND status = 'placed'",
                    (
                        status,
                        cal.iso_ts(local_now),
                        payout,
                        diff,
                        bet_id,
                    ),
                )
                if cursor.rowcount == 0:
                    continue
                self._credit_payout_with(
                    conn,
                    bet_id=bet_id,
                    player_id=player_id,
                    payout=payout,
                    now=local_now,
                )
                stored = conn.execute(
                    "SELECT * FROM bets WHERE id = ?", (bet_id,)
                ).fetchone()
                results.append(self._bet_payload(stored))

        return {
            "day": day_iso,
            "status": "settled",
            "settled": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # Weekly settlement
    # ------------------------------------------------------------------
    def settle_weekly_bets(
        self,
        week: date | datetime | str,
        now: datetime | str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        if local_now < cal.week_end_at(week_date):
            return {
                "week_start": week_iso,
                "status": "skipped",
                "reason": "week_not_ended",
                "settled": 0,
                "results": [],
            }
        if conn is not None:
            return self._settle_weekly_bets_with(conn, week_iso, local_now)
        with self.transaction() as tx:
            return self._settle_weekly_bets_with(tx, week_iso, local_now)

    def _settle_weekly_bets_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        local_now: datetime,
    ) -> dict[str, Any]:
        settled_at = cal.iso_ts(local_now)
        rows = conn.execute(
            "SELECT * FROM bets WHERE kind = 'weekly' AND period_key = ? "
            "AND status = 'placed' ORDER BY id",
            (week_iso,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            bet_id = int(row["id"])
            player_id = str(row["player_id"])
            rival_id = str(row["rival_id"])
            my_xp = self._weekly_xp_with(conn, week_iso, player_id)
            rival_xp = self._weekly_xp_with(conn, week_iso, rival_id)
            diff = my_xp - rival_xp
            target = int(row["target_margin"])
            status = wager_result(diff, target)
            if status == "won":
                payout = payout_for_win(
                    int(row["stake"]), float(row["odds"])
                )
            elif status == "void":
                payout = int(row["paid_stake"])
            else:
                payout = 0
            cursor = conn.execute(
                "UPDATE bets SET status = ?, settled_at = ?, "
                "payout = ?, result_diff = ? "
                "WHERE id = ? AND status = 'placed'",
                (status, settled_at, payout, diff, bet_id),
            )
            if cursor.rowcount == 0:
                continue
            self._credit_payout_with(
                conn,
                bet_id=bet_id,
                player_id=player_id,
                payout=payout,
                now=local_now,
            )
            stored = conn.execute(
                "SELECT * FROM bets WHERE id = ?", (bet_id,)
            ).fetchone()
            results.append(self._bet_payload(stored))
        return {
            "week_start": week_iso,
            "status": "settled",
            "settled": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # Group settlement
    # ------------------------------------------------------------------
    def settle_group_bets(
        self,
        week: date | datetime | str,
        now: datetime | str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Settle this week's group bets on the next Monday 00:05 pass.

        A group bet wins when the player's own ``weekly_scores.xp`` ranks in
        the top three of their group; ties break by ascending ``player_id``.
        The actual personal rank is written back, and a replayed settlement
        cannot pay twice.  A missing group or missing score is void.
        """

        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        if local_now < group_bet_settles_at(week_date):
            return {
                "week_start": week_iso,
                "status": "skipped",
                "reason": "before_group_settlement",
                "settled": 0,
                "results": [],
            }
        if conn is not None:
            return self._settle_group_bets_with(conn, week_iso, local_now)
        with self.transaction() as tx:
            return self._settle_group_bets_with(tx, week_iso, local_now)

    @staticmethod
    def _player_group_rank_with(
        conn: sqlite3.Connection,
        week_iso: str,
        group_id: int,
        player_id: str,
    ) -> int | None:
        """Rank one player inside their own group, or ``None`` if data is missing."""

        group = conn.execute(
            "SELECT 1 FROM groups WHERE id = ? AND week_start = ?",
            (group_id, week_iso),
        ).fetchone()
        if group is None:
            return None
        score = conn.execute(
            "SELECT 1 FROM weekly_scores WHERE week_start = ? "
            "AND player_id = ?",
            (week_iso, player_id),
        ).fetchone()
        if score is None:
            return None
        rows = conn.execute(
            "SELECT gm.player_id AS player_id, ws.xp AS xp "
            "FROM group_members gm "
            "JOIN weekly_scores ws "
            "ON ws.week_start = ? AND ws.player_id = gm.player_id "
            "WHERE gm.group_id = ? "
            "ORDER BY ws.xp DESC, gm.player_id ASC",
            (week_iso, group_id),
        ).fetchall()
        for index, ranked in enumerate(rows, start=1):
            if str(ranked["player_id"]) == player_id:
                return index
        return None

    def _settle_group_bets_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        local_now: datetime,
    ) -> dict[str, Any]:
        settled_at = cal.iso_ts(local_now)
        rows = conn.execute(
            "SELECT * FROM group_bets WHERE week_start = ? "
            "AND status = 'placed' ORDER BY id",
            (week_iso,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            group_bet_id = int(row["id"])
            player_id = str(row["player_id"])
            group_id = int(row["group_id"])
            paid_stake = int(row["paid_stake"])
            stake = int(row["stake"])

            group_rank = self._player_group_rank_with(
                conn, week_iso, group_id, player_id
            )

            if group_rank is None:
                # Missing group/score data is a data anomaly, so void the bet
                # and return only the paid principal.
                status = "void"
                payout = paid_stake
            elif group_rank <= GROUP_TARGET_RANK:
                status = "won"
                payout = payout_for_win(stake, float(row["odds"]))
            else:
                status = "lost"
                payout = 0

            cursor = conn.execute(
                "UPDATE group_bets SET status = ?, settled_at = ?, "
                "payout = ?, group_rank = ? "
                "WHERE id = ? AND status = 'placed'",
                (status, settled_at, payout, group_rank, group_bet_id),
            )
            if cursor.rowcount == 0:
                continue
            self._credit_group_payout_with(
                conn,
                group_bet_id=group_bet_id,
                player_id=player_id,
                payout=payout,
                now=local_now,
            )
            stored = conn.execute(
                "SELECT * FROM group_bets WHERE id = ?", (group_bet_id,)
            ).fetchone()
            results.append(self._group_bet_payload(stored))

        return {
            "week_start": week_iso,
            "status": "settled",
            "settled": len(results),
            "results": results,
        }


__all__ = ["BetsMixin"]
