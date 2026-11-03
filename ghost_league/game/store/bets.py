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
    GROUP_MARKET_LABELS,
    GROUP_MARKETS,
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
    group_market_allowed,
    group_market_odds_table,
    group_market_threshold,
    group_market_won,
    payout_for_win,
    target_in_range,
    wager_result,
    weekly_bet_locks_at,
)
from ..rules import group_quota, xp_for_seconds

_GROUP_BET_SELECT = (
    "SELECT gb.*, (SELECT COUNT(*) FROM group_members gm "
    "WHERE gm.group_id = gb.group_id) AS group_size "
    "FROM group_bets gb"
)


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
        market = str(data.get("market") or "top3")
        size_value = data.get("group_size")
        group_size = int(size_value) if size_value is not None else None
        if group_size and group_size > 0:
            target_rank = group_market_threshold(market, group_size)
            quota = group_quota(group_size)
        else:
            target_rank = GROUP_TARGET_RANK if market == "top3" else None
            quota = None
        return {
            "id": int(data["id"]),
            "player_id": str(data["player_id"]),
            "kind": "group",
            "market": market,
            "market_label": GROUP_MARKET_LABELS.get(market, market),
            "period_key": str(data["week_start"]),
            "rival_id": None,
            "stake": int(data["stake"]),
            "free_stake": int(data["free_stake"]),
            "paid_stake": int(data["paid_stake"]),
            "target_rank": target_rank,
            "target_margin": 0,
            "odds": float(data["odds"]),
            "status": str(data["status"]),
            "placed_at": str(data["placed_at"]),
            "locked_at": None,
            "settled_at": data["settled_at"],
            "payout": int(data["payout"]),
            "result_diff": None,
            "group_id": int(data["group_id"]),
            "group_size": group_size,
            "promotion_quota": quota,
            "demotion_quota": quota,
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
        market: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            f"{_GROUP_BET_SELECT} WHERE gb.player_id = ? "
            "AND gb.week_start = ? AND gb.market = ?",
            (player_id, week_iso, market),
        ).fetchone()

    @staticmethod
    def _group_bet_rows_with(
        conn: sqlite3.Connection,
        player_id: str,
        week_iso: str,
    ) -> dict[str, sqlite3.Row]:
        rows = conn.execute(
            f"{_GROUP_BET_SELECT} WHERE gb.player_id = ? "
            "AND gb.week_start = ? ORDER BY gb.id",
            (player_id, week_iso),
        ).fetchall()
        return {str(row["market"]): row for row in rows}

    @staticmethod
    def _group_bet_row_by_id_with(
        conn: sqlite3.Connection,
        group_bet_id: int,
    ) -> sqlite3.Row | None:
        return conn.execute(
            f"{_GROUP_BET_SELECT} WHERE gb.id = ?",
            (group_bet_id,),
        ).fetchone()

    @staticmethod
    def _group_position_with(
        conn: sqlite3.Connection,
        week_iso: str,
        group_id: int,
        player_id: str,
    ) -> dict[str, Any] | None:
        """Return one player's current group rank and the full score order."""

        group = conn.execute(
            "SELECT id, tier FROM groups WHERE id = ? AND week_start = ?",
            (group_id, week_iso),
        ).fetchone()
        if group is None:
            return None
        rows = conn.execute(
            "SELECT gm.player_id AS player_id, "
            "ws.xp AS xp, ws.week_start AS score_week "
            "FROM group_members gm "
            "LEFT JOIN weekly_scores ws ON ws.week_start = ? "
            "AND ws.player_id = gm.player_id "
            "WHERE gm.group_id = ? "
            "ORDER BY COALESCE(ws.xp, 0) DESC, gm.player_id ASC",
            (week_iso, group_id),
        ).fetchall()
        scores: list[dict[str, Any]] = []
        rank: int | None = None
        xp = 0
        for index, row in enumerate(rows, start=1):
            scored = row["score_week"] is not None
            row_xp = int(row["xp"]) if row["xp"] is not None else 0
            score_row = {
                "rank": index,
                "player_id": str(row["player_id"]),
                "xp": row_xp,
                "scored": scored,
            }
            scores.append(score_row)
            if str(row["player_id"]) == player_id:
                xp = row_xp
                rank = index if scored else None
        return {
            "group_id": int(group["id"]),
            "tier": str(group["tier"]),
            "group_size": len(rows),
            "rank": rank,
            "xp": xp,
            "scores": scores,
        }

    @staticmethod
    def _group_market_xp_gaps(
        position: dict[str, Any] | None,
        *,
        group_size: int,
        rank: int,
    ) -> dict[str, int]:
        """Return each market's XP cushion/deficit for the current rank."""

        if position is None or group_size < 1:
            return {market: 0 for market in GROUP_MARKETS}
        scores = position["scores"]

        def xp_at(rank_number: int) -> int:
            if 1 <= rank_number <= len(scores):
                return int(scores[rank_number - 1]["xp"])
            return 0

        gaps: dict[str, int] = {}
        for market in GROUP_MARKETS:
            threshold = min(
                group_market_threshold(market, group_size), group_size
            )
            if threshold < 1:
                gaps[market] = xp_at(1) - int(position["xp"])
            elif rank <= threshold:
                gaps[market] = (
                    int(position["xp"]) - xp_at(threshold + 1)
                    if threshold < group_size
                    else 0
                )
            else:
                gaps[market] = int(position["xp"]) - xp_at(threshold)
        return gaps

    def _group_state_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        week_iso: str,
    ) -> dict[str, Any] | None:
        """Build the group-market entries visible to one player's tier."""

        group = conn.execute(
            "SELECT g.id, g.tier FROM groups g "
            "JOIN group_members gm ON gm.group_id = g.id "
            "WHERE g.week_start = ? AND gm.player_id = ? "
            "ORDER BY g.id DESC LIMIT 1",
            (week_iso, player_id),
        ).fetchone()
        if group is None:
            return None
        group_id = int(group["id"])
        tier = str(group["tier"])
        position = self._group_position_with(
            conn, week_iso, group_id, player_id
        )
        group_size = int(position["group_size"]) if position else 0
        rank = position["rank"] if position else None
        effective_rank = int(rank) if rank is not None else group_size
        existing = self._group_bet_rows_with(conn, player_id, week_iso)
        if group_size > 0:
            gaps = self._group_market_xp_gaps(
                position, group_size=group_size, rank=effective_rank
            )
            odds = group_market_odds_table(
                group_size=group_size,
                rank=effective_rank,
                xp_gaps=gaps,
            )
            quota = group_quota(group_size)
        else:
            odds = None
            quota = 0
        markets: list[dict[str, Any]] = []
        for market in GROUP_MARKETS:
            allowed = group_market_allowed(market, tier)
            row = existing.get(market)
            bet = self._group_bet_payload(row) if row is not None else None
            reason: str | None = None
            if not allowed:
                reason = (
                    "diamond_no_promotion"
                    if market == "promote"
                    else "bronze_no_demotion"
                )
            elif bet is not None:
                reason = "already_placed"
            elif group_size < 1:
                reason = "no_group"
            markets.append(
                {
                    "market": market,
                    "label": GROUP_MARKET_LABELS[market],
                    "available": allowed,
                    "can_place": (
                        allowed and bet is None and group_size >= 1
                    ),
                    "reason": reason,
                    "target_rank": (
                        group_market_threshold(market, group_size)
                        if group_size > 0
                        else (
                            GROUP_TARGET_RANK if market == "top3" else None
                        )
                    ),
                    "promotion_quota": quota,
                    "demotion_quota": quota,
                    "odds": (
                        float(bet["odds"])
                        if bet is not None
                        else (odds[market] if odds is not None else None)
                    ),
                    "status": str(bet["status"]) if bet is not None else "open",
                    "bet": bet,
                }
            )
        legacy = (
            self._group_bet_payload(existing["top3"])
            if "top3" in existing
            else None
        )
        return {
            "group_id": group_id,
            "tier": tier,
            "group_size": group_size,
            "rank": rank,
            "group": legacy,
            # Bronze must not receive ``no_demote`` and Diamond must not
            # receive ``promote``.  The store still rejects a direct submit.
            "groups": [entry for entry in markets if entry["available"]],
        }

    def _bets_for_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        week_iso: str,
        day_iso: str,
    ) -> dict[str, Any]:
        weekly = self._bet_row_with(conn, player_id, "weekly", week_iso)
        daily = self._bet_row_with(conn, player_id, "daily", day_iso)
        group_state = self._group_state_with(conn, player_id, week_iso)
        return {
            "weekly": self._bet_payload(weekly) if weekly is not None else None,
            "daily": self._bet_payload(daily) if daily is not None else None,
            "group": group_state["group"] if group_state else None,
            "groups": group_state["groups"] if group_state else [],
        }

    def bets_for(
        self,
        player_id: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Return weekly/daily bets plus the three group-market states."""

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
        market: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be non-empty")
        if kind not in {"weekly", "daily", "group"}:
            raise BetRejected("invalid_kind", "下注类型不合法")
        if kind != "group" and market is not None:
            raise BetRejected(
                "invalid_market", "只有组注支持盘口"
            )
        resolved_market = market or "top3"
        if kind == "group" and resolved_market not in GROUP_MARKETS:
            raise BetRejected(
                "invalid_market",
                "盘口必须是 top3、promote 或 no_demote",
            )
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
            f"group-bet:{player_id}:{week_iso}:{resolved_market}:{request_id}"
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
                    conn, player_id, week_iso, resolved_market
                )
                if existing_group is not None:
                    if str(existing_group["idempotency_key"]) == bet_key:
                        return self._group_bet_payload(existing_group)
                    raise BetAlreadyPlaced("本周这个盘口已经下过注")
                keyed_group = conn.execute(
                    f"{_GROUP_BET_SELECT} WHERE gb.idempotency_key = ?",
                    (bet_key,),
                ).fetchone()
                if keyed_group is not None:
                    return self._group_bet_payload(keyed_group)

                if local_now >= weekly_bet_locks_at(week_date):
                    raise BetWindowClosed("组注已截止")
                group = conn.execute(
                    "SELECT g.id AS group_id, g.tier AS tier FROM groups g "
                    "JOIN group_members gm ON gm.group_id = g.id "
                    "WHERE g.week_start = ? AND gm.player_id = ? "
                    "ORDER BY g.id DESC LIMIT 1",
                    (week_iso, player_id),
                ).fetchone()
                if group is None:
                    raise BetRejected(
                        "no_group", "本周还没有分组，暂时不能下组注"
                    )
                tier = str(group["tier"])
                if not group_market_allowed(resolved_market, tier):
                    detail = (
                        "Diamond 段位不能押升段"
                        if resolved_market == "promote"
                        else "Bronze 段位不能押不降段"
                    )
                    raise BetRejected("market_unavailable", detail)

                group_id = int(group["group_id"])
                position = self._group_position_with(
                    conn, week_iso, group_id, player_id
                )
                group_size = int(position["group_size"]) if position else 0
                rank = position["rank"] if position else None
                effective_rank = (
                    int(rank) if rank is not None else max(group_size, 1)
                )
                if group_size > 0:
                    gaps = self._group_market_xp_gaps(
                        position,
                        group_size=group_size,
                        rank=effective_rank,
                    )
                    odds = group_market_odds_table(
                        group_size=group_size,
                        rank=effective_rank,
                        xp_gaps=gaps,
                    )[resolved_market]
                else:
                    odds = group_market_odds_table(
                        group_size=2,
                        rank=2,
                        xp_gaps={resolved_market: 0},
                    )[resolved_market]

                if paid_stake > 0:
                    self._debit_diamonds_with(  # type: ignore[attr-defined]
                        conn,
                        player_id=player_id,
                        amount=paid_stake,
                        reason="group_bet_stake",
                        ref_type="group_bet",
                        ref_id=f"{week_iso}:{resolved_market}",
                        idempotency_key=f"group-bet-stake:{bet_key}",
                        now=local_now,
                        create_for_unknown=False,
                    )
                now_iso = cal.iso_ts(local_now)
                cursor = conn.execute(
                    "INSERT INTO group_bets "
                    "(player_id, week_start, market, group_id, stake, "
                    "free_stake, paid_stake, odds, status, placed_at, "
                    "settled_at, payout, group_rank, idempotency_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'placed', ?, NULL, 0, "
                    "NULL, ?)",
                    (
                        player_id,
                        week_iso,
                        resolved_market,
                        group_id,
                        resolved_stake,
                        FREE_BET_STAKE,
                        paid_stake,
                        odds,
                        now_iso,
                        bet_key,
                    ),
                )
                group_bet_id = int(cursor.lastrowid)
                stored_group = self._group_bet_row_by_id_with(
                    conn, group_bet_id
                )
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
                conn, rival
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

        Each of ``top3``, ``promote`` and ``no_demote`` is judged on its own
        threshold against the player's final group rank.  Ties break by
        ascending ``player_id``.  The actual personal rank is written back,
        and a replayed settlement cannot pay twice.  A missing group, tier or
        personal score is void.
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

    def _settle_group_bets_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        local_now: datetime,
    ) -> dict[str, Any]:
        settled_at = cal.iso_ts(local_now)
        rows = conn.execute(
            f"{_GROUP_BET_SELECT} WHERE gb.week_start = ? "
            "AND gb.status = 'placed' ORDER BY gb.id",
            (week_iso,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            group_bet_id = int(row["id"])
            player_id = str(row["player_id"])
            group_id = int(row["group_id"])
            paid_stake = int(row["paid_stake"])
            stake = int(row["stake"])
            market = str(row["market"])

            position = self._group_position_with(
                conn, week_iso, group_id, player_id
            )
            group_rank = position["rank"] if position is not None else None
            group_size = (
                int(position["group_size"]) if position is not None else 0
            )
            tier = str(position["tier"]) if position is not None else None

            if (
                group_rank is None
                or group_size < 1
                or tier is None
                or market not in GROUP_MARKETS
            ):
                # Missing group/score data is a data anomaly, so void the bet
                # and return only the paid principal.
                status = "void"
                payout = paid_stake
            elif group_market_won(
                market,
                rank=int(group_rank),
                group_size=group_size,
                tier=tier,
            ):
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
            stored = self._group_bet_row_by_id_with(conn, group_bet_id)
            results.append(self._group_bet_payload(stored))

        return {
            "week_start": week_iso,
            "status": "settled",
            "settled": len(results),
            "results": results,
        }


__all__ = ["BetsMixin"]
