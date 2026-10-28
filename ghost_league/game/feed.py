"""Deterministic in-group feed events, reactions, and tags.

The feed never invents activity: callers only write an event after a real
check-in or a settled ``weekly_results`` row exists.  AI reactions are a pure
function of ``event_id + actor_id`` plus the event's own evidence, so replaying
the same data always produces the same emoji/tag without an LLM.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

FEED_CHECKIN: Final = "checkin"
FEED_PROMOTED: Final = "promoted"
FEED_CHAMPION: Final = "champion"
FEED_KINDS: Final = (FEED_CHECKIN, FEED_PROMOTED, FEED_CHAMPION)

FEED_EMOJIS: Final[tuple[str, ...]] = (
    "盯",
    "卷",
    "递茶",
    "记下了",
    "肃然起敬",
    "同行",
)

FEED_TAGS: Final[tuple[str, ...]] = (
    "稳",
    "狠",
    "慢热",
    "夜航",
    "爆发",
    "苦行",
    "手稳",
    "敢冲",
)

TIER_LABELS: Final[dict[str, str]] = {
    "Bronze": "青铜",
    "Silver": "白银",
    "Gold": "黄金",
    "Sapphire": "蓝宝石",
    "Ruby": "红宝石",
    "Emerald": "翡翠",
    "Amethyst": "紫水晶",
    "Pearl": "珍珠",
    "Obsidian": "黑曜石",
    "Diamond": "钻石",
}

# A tag is only eligible when the event itself can explain it.  ``champion``
# is the only kind allowed to be 狠/爆发; ``checkin`` is the only kind allowed
# to be 稳/慢热.  A zero-XP event is never allowed to claim 爆发.
_CHECKIN_TAGS: Final[tuple[str, ...]] = ("稳", "慢热", "夜航", "手稳")
_PROMOTED_TAGS: Final[tuple[str, ...]] = ("敢冲", "苦行", "手稳")
_CHAMPION_TAGS: Final[tuple[str, ...]] = ("狠", "爆发", "敢冲")
_ZERO_XP_TAGS: Final[tuple[str, ...]] = ("慢热",)


def tier_label(tier: str) -> str:
    return TIER_LABELS.get(str(tier), str(tier))


def format_xp(xp: int) -> str:
    return f"{max(0, int(xp)):,}"


def checkin_body(xp: int) -> str:
    return f"今天点着了 {format_xp(xp)} XP"


def promoted_body(from_tier: str, to_tier: str) -> str:
    return f"这周从{tier_label(from_tier)}升到{tier_label(to_tier)}"


def champion_body(xp: int) -> str:
    return f"这周在小组拿下第一，{format_xp(xp)} XP"


def _digest(event_id: int | str, actor_id: str) -> bytes:
    # The contract is hash(event_id + actor_id); keep the concatenation exact
    # and stable across processes.
    return hashlib.sha256(f"{event_id}{actor_id}".encode("utf-8")).digest()


def ai_actor_rank(event_id: int | str, actor_id: str) -> int:
    """Stable ordering key used to pick at most three AI responders."""

    return int.from_bytes(_digest(event_id, actor_id)[:8], "big")


def reaction_emoji(event_id: int | str, actor_id: str) -> str:
    digest = _digest(event_id, actor_id)
    index = int.from_bytes(digest[8:16], "big") % len(FEED_EMOJIS)
    return FEED_EMOJIS[index]


def allowed_tags(kind: str, payload: dict[str, Any] | None) -> tuple[str, ...]:
    """Return tags that the event evidence can justify."""

    data = payload or {}
    try:
        xp = int(data.get("xp") or 0)
    except (TypeError, ValueError):
        xp = 0
    if xp <= 0:
        return _ZERO_XP_TAGS if kind == FEED_CHECKIN else ()
    if kind == FEED_CHECKIN:
        return _CHECKIN_TAGS
    if kind == FEED_PROMOTED:
        return _PROMOTED_TAGS
    if kind == FEED_CHAMPION:
        return _CHAMPION_TAGS
    return ()


def reaction_tag(
    event_id: int | str,
    actor_id: str,
    *,
    kind: str,
    payload: dict[str, Any] | None,
) -> str | None:
    tags = allowed_tags(kind, payload)
    if not tags:
        return None
    digest = _digest(event_id, actor_id)
    index = int.from_bytes(digest[16:24], "big") % len(tags)
    return tags[index]


__all__ = [
    "FEED_CHAMPION",
    "FEED_CHECKIN",
    "FEED_EMOJIS",
    "FEED_KINDS",
    "FEED_PROMOTED",
    "FEED_TAGS",
    "TIER_LABELS",
    "ai_actor_rank",
    "allowed_tags",
    "champion_body",
    "checkin_body",
    "format_xp",
    "promoted_body",
    "reaction_emoji",
    "reaction_tag",
    "tier_label",
]
