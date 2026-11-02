"""Unified personal history for ``GET /v1/me/history``.

Six sources are projected into one timeline.  Every query is scoped to a
single ``player_id``; the projection never joins wallets, other players, or
private ledger rows.  Timestamps are normalised to the game's Asia/Shanghai
ISO-8601 format so mixed SQLite representations (ISO text, Unix seconds,
date-only strings) sort deterministically.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, time
from typing import Any

from ...schedule import TZ
from .. import calendar as cal
from ..rival import GROUP_MARKET_LABELS, group_market_threshold
from ..stars import RARITY_LABELS, TYPE_LABELS

HISTORY_TYPES = (
    "checkin",
    "bet",
    "group_bet",
    "rival",
    "star",
    "week",
)
DEFAULT_HISTORY_LIMIT = 100
MAX_HISTORY_LIMIT = 200

_BET_STATUS_LABELS = {
    "placed": "待结算",
    "won": "已赢",
    "lost": "未中",
    "void": "已退回",
}
_OUTCOME_LABELS = {
    "win": "获胜",
    "loss": "落败",
    "draw": "平局",
}
_UNIX_SECONDS = re.compile(r"^-?\d+(?:\.\d+)?$")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _xp(value: Any) -> str:
    return f"{_number(value):,}"


def _odds(value: Any) -> str:
    try:
        rendered = f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "—"
    return rendered or "0"


def _iso_at(value: Any) -> str | None:
    """Normalise ISO text, Unix seconds, or a date-only string to game time."""

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return cal.iso_ts(cal.as_local(value))
    if isinstance(value, (int, float)):
        try:
            return cal.iso_ts(datetime.fromtimestamp(float(value), tz=TZ))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if _UNIX_SECONDS.fullmatch(text):
        try:
            return cal.iso_ts(datetime.fromtimestamp(float(text), tz=TZ))
        except (OverflowError, OSError, ValueError):
            return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            return cal.iso_ts(datetime.combine(date.fromisoformat(text), time.min, tzinfo=TZ))
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return cal.iso_ts(cal.as_local(parsed))


def _join(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


class HistoryMixin:
    """Read-only projection of one player's personal timeline."""

    def personal_history(
        self,
        player_id: str,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        if limit < 1 or limit > MAX_HISTORY_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {MAX_HISTORY_LIMIT}"
            )

        items: list[dict[str, Any]] = []
        with self._reader() as conn:
            self._append_checkins(conn, player_id, items)
            self._append_bets(conn, player_id, items)
            self._append_group_bets(conn, player_id, items)
            self._append_rival_results(conn, player_id, items)
            self._append_stars(conn, player_id, items)
            self._append_weekly_results(conn, player_id, items)

        # Stable ordering: id ascending first, then newest ``at`` first.
        items.sort(key=lambda item: str(item["id"]))
        items.sort(key=lambda item: str(item["at"]), reverse=True)
        return items[:limit]

    # -- source projections -------------------------------------------
    def _append_checkins(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM checkins WHERE player_id = ?",
            (player_id,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            day = _text(record.get("date"))
            at = (
                _iso_at(record.get("created_at"))
                or _iso_at(record.get("checked_at"))
                or _iso_at(record.get("repaired_at"))
                or _iso_at(day)
            )
            if at is None:
                continue
            domain = _text(record.get("domain"))
            content = _text(record.get("content"))
            body = _join(domain, content) or "打卡记录"
            items.append(
                {
                    "id": f"checkin:{day}",
                    "type": "checkin",
                    "at": at,
                    "title": "打卡",
                    "body": body,
                    "data": {
                        "date": day,
                        "domain": domain,
                        "content": content,
                    },
                }
            )

    def _append_bets(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM bets WHERE player_id = ?",
            (player_id,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            at = _iso_at(record.get("settled_at")) or _iso_at(
                record.get("placed_at")
            )
            if at is None:
                continue
            kind = _text(record.get("kind"))
            kind_label = "日注" if kind == "daily" else "周注"
            status = _text(record.get("status"))
            status_label = _BET_STATUS_LABELS.get(status, status or "待结算")
            target = _number(record.get("target_margin"))
            payout = _number(record.get("payout"))
            body = _join(
                kind_label,
                f"目标 +{_xp(target)} XP",
                f"赔率 ×{_odds(record.get('odds'))}",
                status_label,
                f"派彩 {_xp(payout)}" if payout > 0 else "",
            )
            items.append(
                {
                    "id": f"bet:{_number(record.get('id'))}",
                    "type": "bet",
                    "at": at,
                    "title": "下注",
                    "body": body,
                    "data": {
                        "kind": kind,
                        "period_key": _text(record.get("period_key")),
                        "target_margin": target,
                        "odds": float(record.get("odds") or 0),
                        "status": status,
                        "payout": payout,
                    },
                }
            )

    def _append_group_bets(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        rows = conn.execute(
            "SELECT gb.*, (SELECT COUNT(*) FROM group_members gm "
            "WHERE gm.group_id = gb.group_id) AS group_size "
            "FROM group_bets gb WHERE gb.player_id = ?",
            (player_id,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            at = _iso_at(record.get("settled_at")) or _iso_at(
                record.get("placed_at")
            )
            if at is None:
                continue
            status = _text(record.get("status"))
            status_label = _BET_STATUS_LABELS.get(status, status or "待结算")
            market = _text(record.get("market")) or "top3"
            label = GROUP_MARKET_LABELS.get(market, "组内下注")
            group_size = record.get("group_size")
            target_rank = (
                group_market_threshold(market, int(group_size))
                if group_size is not None and int(group_size) > 0
                else None
            )
            rank = record.get("group_rank")
            rank_label = (
                f"组内第 {_number(rank)} 名"
                if rank is not None
                else f"{label}·待结算"
            )
            payout = _number(record.get("payout"))
            body = _join(
                rank_label,
                f"赔率 ×{_odds(record.get('odds'))}",
                status_label,
                f"派彩 {_xp(payout)}" if payout > 0 else "",
            )
            items.append(
                {
                    "id": f"group_bet:{_number(record.get('id'))}",
                    "type": "group_bet",
                    "at": at,
                    "title": label,
                    "body": body,
                    "data": {
                        "week_start": _text(record.get("week_start")),
                        "market": market,
                        "market_label": label,
                        "group_rank": (
                            _number(rank) if rank is not None else None
                        ),
                        "target_rank": target_rank,
                        "odds": float(record.get("odds") or 0),
                        "status": status,
                        "payout": payout,
                    },
                }
            )

    def _append_rival_results(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM rival_results WHERE player_id = ?",
            (player_id,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            at = _iso_at(record.get("settled_at"))
            if at is None:
                continue
            outcome = _text(record.get("outcome"))
            outcome_label = _OUTCOME_LABELS.get(outcome, outcome or "已结算")
            reward = _number(record.get("reward_diamonds"))
            body = _join(
                f"我 {_xp(record.get('my_xp'))} XP",
                f"宿敌 {_xp(record.get('rival_xp'))} XP",
                outcome_label,
                f"奖励 {_xp(reward)} 钻石" if reward > 0 else "无奖励",
            )
            week_start = _text(record.get("week_start"))
            items.append(
                {
                    "id": f"rival:{week_start}",
                    "type": "rival",
                    "at": at,
                    "title": "宿敌",
                    "body": body,
                    "data": {
                        "week_start": week_start,
                        "my_xp": _number(record.get("my_xp")),
                        "rival_xp": _number(record.get("rival_xp")),
                        "outcome": outcome,
                        "reward_diamonds": reward,
                    },
                }
            )

    def _append_stars(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM player_stars WHERE player_id = ?",
            (player_id,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            at = _iso_at(record.get("acquired_at"))
            if at is None:
                continue
            star_type = _text(record.get("star_type"))
            rarity = _text(record.get("rarity"))
            type_label = TYPE_LABELS.get(star_type, star_type or "星星")
            rarity_label = RARITY_LABELS.get(rarity, rarity)
            name = _text(record.get("name")) or "未命名星星"
            star_id = _text(record.get("id"))
            items.append(
                {
                    "id": f"star:{star_id}",
                    "type": "star",
                    "at": at,
                    "title": "星星",
                    "body": _join(name, type_label, rarity_label),
                    "data": {
                        "name": name,
                        "kind": _text(record.get("kind")),
                        "star_type": star_type,
                        "type_label": type_label,
                        "rarity": rarity,
                        "rarity_label": rarity_label,
                        "season_key": record.get("season_key"),
                    },
                }
            )

    def _append_weekly_results(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM weekly_results WHERE player_id = ?",
            (player_id,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            at = _iso_at(record.get("settled_at"))
            if at is None:
                continue
            promoted = _flag(record.get("promoted"))
            demoted = _flag(record.get("demoted"))
            movement = "晋级" if promoted else "降级" if demoted else "留段"
            clean = _number(record.get("clean_checkins"))
            tier = _text(record.get("tier"))
            rank = _number(record.get("rank"))
            xp = _number(record.get("xp"))
            week_start = _text(record.get("week_start"))
            items.append(
                {
                    "id": f"week:{week_start}",
                    "type": "week",
                    "at": at,
                    "title": "周结算",
                    "body": _join(
                        tier,
                        f"第 {rank} 名",
                        f"{_xp(xp)} XP",
                        movement,
                        f"干净打卡 {clean} 天",
                    ),
                    "data": {
                        "week_start": week_start,
                        "group_id": _number(record.get("group_id")),
                        "tier": tier,
                        "rank": rank,
                        "xp": xp,
                        "promoted": promoted,
                        "demoted": demoted,
                        "clean_checkins": clean,
                    },
                }
            )


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "HISTORY_TYPES",
    "HistoryMixin",
    "MAX_HISTORY_LIMIT",
]
