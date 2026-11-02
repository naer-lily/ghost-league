"""Gacha star rarity, type, palette, visual seed, and default naming.

The shop no longer sells a fixed "named star"; each purchase rolls one rarity
from :data:`RARITY_WEIGHTS`, then one type from that rarity's pool.  Rolls use
the operating system entropy source via :mod:`secrets` so they are not
predictable from the process PRNG state.

Everything in this module is pure except the rolls themselves.  The palette
and visual seed produced by :func:`make_star_visual` are persisted on the star
row; later SVG rendering only reads the stored values and never re-rolls them.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import re
import secrets
import unicodedata
from typing import Any

from .rules import ShopQuantityRejected

# Sum is exactly 1.0 (0.5 + 0.3 + 0.15 + 0.045 + 0.005).  Keep the literal
# table as the single source of truth; the roll converts the weights to
# integer millionths so floating point cannot shift a boundary.
RARITY_WEIGHTS: dict[str, float] = {
    "common": 0.5,
    "uncommon": 0.3,
    "rare": 0.15,
    "epic": 0.045,
    "legendary": 0.005,
}

RARITY_LABELS: dict[str, str] = {
    "common": "微光",
    "uncommon": "星辉",
    "rare": "耀星",
    "epic": "奇点",
    "legendary": "神话",
}

RARITY_TYPE_POOLS: dict[str, list[str]] = {
    "common": ["red_dwarf", "orange_dwarf", "yellow_dwarf"],
    "uncommon": ["white_dwarf", "blue_white_star", "variable_star"],
    "rare": ["red_giant", "blue_giant", "binary_star"],
    "epic": ["triple_star", "neutron_star", "pulsar"],
    "legendary": ["black_hole_relic"],
}

# Convenience alias for callers that only need the complete type pool.
TYPE_POOLS = RARITY_TYPE_POOLS

TYPE_LABELS: dict[str, str] = {
    "red_dwarf": "红矮星",
    "orange_dwarf": "橙矮星",
    "yellow_dwarf": "黄矮星",
    "white_dwarf": "白矮星",
    "blue_white_star": "蓝白星",
    "variable_star": "变星",
    "red_giant": "红巨星",
    "blue_giant": "蓝巨星",
    "binary_star": "双星",
    "triple_star": "三合星",
    "neutron_star": "中子星",
    "pulsar": "脉冲星",
    "black_hole_relic": "黑洞遗迹",
}

TYPE_PALETTES: dict[str, list[str]] = {
    "red_dwarf": ["#ff8a6b", "#ffd2a8", "#6b1d2a"],
    "orange_dwarf": ["#ffb066", "#ffe0b2", "#5a2b18"],
    "yellow_dwarf": ["#ffe08a", "#fff4c2", "#5a4a1a"],
    "white_dwarf": ["#e8f2ff", "#ffffff", "#6b7c99"],
    "blue_white_star": ["#bfe4ff", "#ffffff", "#2b5b8a"],
    "variable_star": ["#ffd166", "#ff6b6b", "#3b2a5a"],
    "red_giant": ["#ff6b5e", "#ffc2a8", "#4a0f18"],
    "blue_giant": ["#7cc7ff", "#dff4ff", "#123a6b"],
    "binary_star": ["#ffd166", "#8ad7ff", "#3a2b5a"],
    "triple_star": ["#ffb3c7", "#9fe7d8", "#5a3a6b"],
    "neutron_star": ["#d9f6ff", "#8ad7ff", "#1a2a4a"],
    "pulsar": ["#c9a7ff", "#6be7ff", "#1a103a"],
    "black_hole_relic": ["#b388ff", "#ff9e6b", "#0b0614"],
}

STAR_TYPES: tuple[str, ...] = tuple(TYPE_PALETTES)

COMPANION_COUNTS: dict[str, int] = {
    "binary_star": 1,
    "triple_star": 2,
}

STAR_NAME_MAX_LENGTH = 40
VISUAL_SEED_MAX = (1 << 63) - 1

_CATALOG_CODE_RE = re.compile(r"^GL-(\d{4})-([0-9A-F]{8})$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Names are generated only when the buyer omits ``name``.  They are still
# private to the owner and never rendered into the SVG.
_NAME_WORDS: tuple[str, ...] = (
    "霜蓝",
    "余烬",
    "遥汐",
    "星野",
    "月白",
    "青黛",
    "赤霄",
    "长庚",
    "启明",
    "流光",
    "听雪",
    "云岫",
    "疏影",
    "落霞",
    "寒酥",
    "南辰",
    "北辰",
    "银砾",
    "望舒",
    "羲和",
    "惊鸿",
    "扶光",
    "沉璧",
    "初霁",
    "眠川",
    "燃犀",
    "照夜",
    "衔烛",
    "拾光",
    "归潮",
    "过隙",
    "未央",
    "朝露",
    "暮云",
    "暗香",
    "知微",
    "沧溟",
    "碧落",
    "玄英",
    "素商",
)

_WEIGHT_SCALE = 1_000_000
_RARITY_UNITS: tuple[tuple[str, int], ...] = tuple(
    (rarity, round(weight * _WEIGHT_SCALE))
    for rarity, weight in RARITY_WEIGHTS.items()
)
_TOTAL_WEIGHT_UNITS = sum(units for _, units in _RARITY_UNITS)


def _rarity_by_type() -> dict[str, str]:
    return {
        star_type: rarity
        for rarity, types in RARITY_TYPE_POOLS.items()
        for star_type in types
    }


RARITY_BY_TYPE: dict[str, str] = _rarity_by_type()


def roll_star_rarity() -> str:
    """Return one rarity using the integer weights derived from the table."""

    pick = secrets.randbelow(_TOTAL_WEIGHT_UNITS)
    cumulative = 0
    for rarity, units in _RARITY_UNITS:
        cumulative += units
        if pick < cumulative:
            return rarity
    return _RARITY_UNITS[-1][0]  # pragma: no cover - defensive only


def roll_star_type(rarity: str) -> str:
    """Uniformly pick one type from the rarity pool."""

    try:
        pool = RARITY_TYPE_POOLS[rarity]
    except KeyError as exc:
        raise ValueError(f"unknown star rarity: {rarity}") from exc
    return secrets.choice(pool)


def companion_count_for(star_type: str) -> int:
    return COMPANION_COUNTS.get(star_type, 0)


def _shift_palette(
    palette: list[str] | tuple[str, ...], season_key: str | None
) -> tuple[str, str, str]:
    """Apply a small, deterministic month hue offset for seasonal stars."""

    if not season_key:
        return palette
    match = re.match(r"^(\d{4})-(\d{2})$", str(season_key))
    if match is None:
        return palette
    month = max(1, min(12, int(match.group(2))))
    year = int(match.group(1))
    hue_shift = ((month - 1) / 12.0) * 0.08 + (year % 4) * 0.005
    shifted: list[str] = []
    for color in palette:
        red, green, blue = _hex_to_rgb(color)
        hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
        hue = (hue + hue_shift) % 1.0
        lightness = max(0.05, min(0.95, lightness * 0.96 + 0.02))
        saturation = max(0.05, min(1.0, saturation * 0.94 + 0.03))
        shifted.append(_rgb_to_hex(*colorsys.hls_to_rgb(hue, lightness, saturation)))
    return (shifted[0], shifted[1], shifted[2])


def _hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = str(color).lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid palette color: {color}")
    return tuple(
        int(value[index : index + 2], 16) / 255.0 for index in (0, 2, 4)
    )  # type: ignore[return-value]


def _rgb_to_hex(red: float, green: float, blue: float) -> str:
    channels = [
        max(0, min(255, round(channel * 255))) for channel in (red, green, blue)
    ]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def make_star_visual(
    star_type: str,
    rarity: str,
    season_key: str | None = None,
) -> dict[str, Any]:
    """Return the persistent palette, 63-bit visual seed, and companions."""

    if rarity not in RARITY_TYPE_POOLS:
        raise ValueError(f"unknown star rarity: {rarity}")
    if star_type not in TYPE_PALETTES:
        raise ValueError(f"unknown star type: {star_type}")
    base = TYPE_PALETTES[star_type]
    palette = list(_shift_palette(base, season_key))
    visual_seed = secrets.randbits(63)
    while visual_seed == 0:  # pragma: no cover - astronomically unlikely
        visual_seed = secrets.randbits(63)
    return {
        "palette": palette,
        "visual_seed": visual_seed,
        "companion_count": companion_count_for(star_type),
    }


def generate_star_name() -> str:
    """Generate one private default name from the Chinese two-character pool."""

    return secrets.choice(_NAME_WORDS)


def validate_star_name(name: str | None) -> str:
    """Trim and validate a user-provided name; empty values are rejected."""

    if not isinstance(name, str):
        raise ShopQuantityRejected("invalid_star_name", "star name is required")
    normalized = name.strip()
    if not normalized or len(normalized) > STAR_NAME_MAX_LENGTH:
        raise ShopQuantityRejected(
            "invalid_star_name", "star name must be 1-40 characters"
        )
    if any(
        character in "\r\n"
        or unicodedata.category(character).startswith("C")
        for character in normalized
    ):
        raise ShopQuantityRejected(
            "invalid_star_name",
            "star name must not contain newlines or control characters",
        )
    return normalized


def is_valid_palette(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(
            isinstance(color, str) and _HEX_COLOR_RE.match(color) is not None
            for color in value
        )
    )


def parse_palette_json(value: Any, star_type: str | None = None) -> list[str]:
    """Read a stored palette or fall back to the type palette."""

    palette: Any = value
    if isinstance(value, str) and value:
        try:
            palette = json.loads(value)
        except (TypeError, ValueError):
            palette = None
    if is_valid_palette(palette):
        return [str(color) for color in palette]
    fallback = TYPE_PALETTES.get(
        str(star_type or ""), ["#ffffff", "#ffffff", "#000000"]
    )
    return list(fallback)


def catalog_year(acquired_at: Any) -> str:
    match = re.match(r"^(\d{4})-", str(acquired_at or ""))
    if match is not None:
        return match.group(1)
    return "2026"


def deterministic_catalog_code(star_id: str, acquired_at: Any, salt: int = 0) -> str:
    digest = hashlib.sha256(
        f"catalog:{star_id}:{salt}".encode("utf-8")
    ).hexdigest()
    return f"GL-{catalog_year(acquired_at)}-{digest[:8].upper()}"


def catalog_code_is_valid(value: Any) -> bool:
    return isinstance(value, str) and _CATALOG_CODE_RE.match(value) is not None


def deterministic_star_visual(
    star_id: str,
    *,
    season_key: str | None = None,
    star_type: str | None = None,
    rarity: str | None = None,
) -> dict[str, Any]:
    """Deterministically backfill a legacy row from its stable id.

    Existing valid values passed by the caller take precedence; missing or
    unknown values are derived without the operating system entropy source so
    rerunning the migration produces identical data.
    """

    digest = hashlib.sha256(f"star-visual:{star_id}".encode("utf-8")).digest()
    resolved_rarity = rarity if rarity in RARITY_TYPE_POOLS else None
    resolved_type = star_type if star_type in TYPE_PALETTES else None
    if resolved_type is None:
        if resolved_rarity is None:
            # Use the same coarse weight boundaries as the live roll.
            pick = int.from_bytes(digest[:8], "big") % _TOTAL_WEIGHT_UNITS
            cumulative = 0
            for candidate, units in _RARITY_UNITS:
                cumulative += units
                if pick < cumulative:
                    resolved_rarity = candidate
                    break
        assert resolved_rarity is not None
        pool = RARITY_TYPE_POOLS[resolved_rarity]
        resolved_type = pool[int.from_bytes(digest[8:16], "big") % len(pool)]
    resolved_rarity = RARITY_BY_TYPE[resolved_type]
    palette = list(_shift_palette(TYPE_PALETTES[resolved_type], season_key))
    seed = int.from_bytes(digest[16:24], "big") & VISUAL_SEED_MAX
    if seed == 0:
        seed = 1
    return {
        "star_type": resolved_type,
        "rarity": resolved_rarity,
        "palette": palette,
        "visual_seed": seed,
        "companion_count": companion_count_for(resolved_type),
    }
