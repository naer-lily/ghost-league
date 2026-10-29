"""Deterministic progression catalog and milestone rewards (v1).

Titles and cosmetics are display-only.  Nothing here changes XP, ranking,
grouping, or settlement; the same milestones and the same award function are
used for local humans and Channel-provided AI players.
"""

from __future__ import annotations

from typing import Any, Final

MILESTONE_FIRST_CHECKIN: Final = "first_checkin"
MILESTONE_STREAK_3: Final = "streak_3"
MILESTONE_STREAK_7: Final = "streak_7"
MILESTONE_STREAK_BROKEN: Final = "streak_broken"
MILESTONE_TOP_3: Final = "top_3"
MILESTONE_CHAMPION: Final = "champion"
MILESTONE_PROMOTED: Final = "promoted"

MILESTONE_ORDER: Final[tuple[str, ...]] = (
    MILESTONE_FIRST_CHECKIN,
    MILESTONE_STREAK_3,
    MILESTONE_STREAK_7,
    MILESTONE_STREAK_BROKEN,
    MILESTONE_TOP_3,
    MILESTONE_CHAMPION,
    MILESTONE_PROMOTED,
)

# Fixed catalog seed.  Rows never grow with users and are never purchasable.
CATALOG_TITLES: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "title_ignition",
        "name": "点火",
        "description": "首次完成 100 XP 打卡",
    },
    {
        "id": "title_three_days",
        "name": "三日不息",
        "description": "连续打卡 3 天",
    },
    {
        "id": "title_seven_days",
        "name": "七日不熄",
        "description": "连续打卡 7 天",
    },
    {
        "id": "title_stage",
        "name": "登台",
        "description": "首次进入周榜前 3",
    },
    {
        "id": "title_champion",
        "name": "周冠",
        "description": "首次获得周榜第 1",
    },
    {
        "id": "title_ascent",
        "name": "向上",
        "description": "首次晋级",
    },
    {
        "id": "title_clown",
        "name": "小丑",
        "description": "断掉一次连胜后获得",
    },
)

CATALOG_ITEMS: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "frame_ember",
        "name": "余烬",
        "slot": "frame",
        "description": "首次完成 100 XP 打卡",
    },
    {
        "id": "frame_clown",
        "name": "小丑帽",
        "slot": "frame",
        "description": "断掉一次连胜后获得",
    },
    {
        "id": "backdrop_night",
        "name": "夜航",
        "slot": "backdrop",
        "description": "连续打卡 7 天",
    },
    {
        "id": "badge_champion",
        "name": "冠军环",
        "slot": "badge_accent",
        "description": "首次获得周榜第 1",
    },
)

# One milestone row per trigger; rewards are inserted with INSERT OR IGNORE so
# replaying the same event can never duplicate a title or item.
MILESTONE_REWARDS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    MILESTONE_FIRST_CHECKIN: {
        "titles": ("title_ignition",),
        "items": ("frame_ember",),
    },
    MILESTONE_STREAK_3: {"titles": ("title_three_days",), "items": ()},
    MILESTONE_STREAK_7: {
        "titles": ("title_seven_days",),
        "items": ("backdrop_night",),
    },
    MILESTONE_STREAK_BROKEN: {
        "titles": ("title_clown",),
        "items": ("frame_clown",),
    },
    MILESTONE_TOP_3: {"titles": ("title_stage",), "items": ()},
    MILESTONE_CHAMPION: {
        "titles": ("title_champion",),
        "items": ("badge_champion",),
    },
    MILESTONE_PROMOTED: {"titles": ("title_ascent",), "items": ()},
}

MILESTONE_CONDITIONS: Final[dict[str, str]] = {
    MILESTONE_FIRST_CHECKIN: "首次完成 100 XP 打卡",
    MILESTONE_STREAK_3: "连续打卡 3 天（补签计入）",
    MILESTONE_STREAK_7: "连续打卡 7 天（补签计入）",
    MILESTONE_STREAK_BROKEN: "断掉一次连胜（同一天只记一次）",
    MILESTONE_TOP_3: "首次进入周榜前 3",
    MILESTONE_CHAMPION: "首次获得周榜第 1",
    MILESTONE_PROMOTED: "首次晋级",
}

TITLE_BY_ID: Final[dict[str, dict[str, str]]] = {
    row["id"]: row for row in CATALOG_TITLES
}
ITEM_BY_ID: Final[dict[str, dict[str, str]]] = {
    row["id"]: row for row in CATALOG_ITEMS
}
ITEM_SLOTS: Final[tuple[str, ...]] = ("frame", "backdrop", "badge_accent")


def milestone_payload(
    milestone_id: str,
    *,
    week_start: str,
    day: str | None = None,
    source: str | None = None,
    streak: int | None = None,
    rank: int | None = None,
    promoted: bool | None = None,
) -> dict[str, Any]:
    """Build the small internal payload stored beside one award."""

    payload: dict[str, Any] = {
        "milestone_id": milestone_id,
        "week_start": week_start,
    }
    if day is not None:
        payload["day"] = day
    if source is not None:
        payload["source"] = source
    if streak is not None:
        payload["streak"] = streak
    if rank is not None:
        payload["rank"] = rank
    if promoted is not None:
        payload["promoted"] = promoted
    return payload
