"""Deliberately tiny v1 AI policy.

Only two actions exist: one 15-minute XP increment per account/hour and,
optionally, one cheapest affordable star per day.  No bets, tasks, rival
selection or multi-account coordination.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TZ: Final = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:  # pragma: no cover - tzdata is normally present
    TZ = timezone.utc

XP_EVENT_PREFIX: Final = "ai_channel"
STAR_REQUEST_PREFIX: Final = "ai_star"
STAR_KINDS: Final = frozenset({"star", "seasonal_star"})


def parse_at(value: datetime | str | None = None) -> datetime:
    """Normalize a CLI/test timestamp to an aware datetime."""

    if value is None:
        moment = datetime.now(TZ)
    elif isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError("at must be a datetime or ISO-8601 string")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ)
    return moment


def xp_event_id(user_id: str, at: datetime) -> str:
    """Stable per-account/hour id; repeating a tick in the same hour replays."""

    return f"{XP_EVENT_PREFIX}:{user_id}:{at.strftime('%Y%m%dT%H')}"


def star_request_id(user_id: str, item_id: str, at: datetime) -> str:
    """Stable per-account/item/day id so repeated ticks do not double-buy."""

    return f"{STAR_REQUEST_PREFIX}:{user_id}:{item_id}:{at.strftime('%Y%m%d')}"


def choose_star(
    shop: Sequence[Mapping[str, Any]],
    diamonds: Any,
) -> Mapping[str, Any] | None:
    """Return the cheapest available star the wallet can afford."""

    if isinstance(diamonds, bool) or not isinstance(diamonds, int):
        return None
    candidates: list[tuple[int, str, Mapping[str, Any]]] = []
    for item in shop:
        if not isinstance(item, Mapping):
            continue
        if item.get("kind") not in STAR_KINDS:
            continue
        if item.get("available") is False:
            continue
        item_id = item.get("id")
        price = item.get("price_diamonds")
        if not isinstance(item_id, str) or not item_id:
            continue
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            continue
        candidates.append((price, item_id, item))
    if not candidates:
        return None
    price, _, item = min(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    if diamonds < price:
        return None
    return item


__all__ = [
    "STAR_KINDS",
    "STAR_REQUEST_PREFIX",
    "TZ",
    "XP_EVENT_PREFIX",
    "choose_star",
    "parse_at",
    "star_request_id",
    "xp_event_id",
]
