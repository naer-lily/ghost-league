"""Public, embeddable league status badge and iframe page.

The badge is intentionally built from the explicit ``status_for`` projection so
it never has access to account tokens or internal league data.  SVG and HTML are
rendered as plain strings with XML/HTML escaping; there are no external assets
or scripts.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .game.rules import SECONDS_PER_XP
from .schedule import TZ
from .themes import DEFAULT_ICON_THEME, icon_theme_or_default

TIER_LABELS: dict[str, str] = {
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

# Tier artwork lives beside the web app and is embedded into the SVG as a data
# URI.  Keeping the accent pairs here lets the glow and fallback ring match the
# tier even when an icon file cannot be read.
TIER_VISUALS: dict[str, tuple[str, str]] = {
    "Bronze": ("#d08a5a", "#8a4c29"),
    "Silver": ("#cfd8e6", "#7e8aa3"),
    "Gold": ("#ffd45c", "#c8861f"),
    "Sapphire": ("#4e9bff", "#2455b8"),
    "Ruby": ("#ff5577", "#b81f46"),
    "Emerald": ("#4be5ad", "#168c68"),
    "Amethyst": ("#bf73ff", "#7430bf"),
    "Pearl": ("#ffe9f6", "#c795bd"),
    "Obsidian": ("#7b6bff", "#261a5f"),
    "Diamond": ("#8ff4ff", "#2f8da6"),
}

TIER_SLUGS: dict[str, str] = {
    "Bronze": "bronze",
    "Silver": "silver",
    "Gold": "gold",
    "Sapphire": "sapphire",
    "Ruby": "ruby",
    "Emerald": "emerald",
    "Amethyst": "amethyst",
    "Pearl": "pearl",
    "Obsidian": "obsidian",
    "Diamond": "diamond",
}

@dataclass(frozen=True)
class FrameVisual:
    """One equipped frame's self-contained SVG treatment.

    ``asset`` names a PNG in :data:`FRAME_ASSET_DIR`; the renderer embeds it as
    a base64 data URI and centres it on the tier icon.  The transparent middle
    of the artwork therefore lines up with the icon, while the decorated ring
    extends beyond it.  New frames only need one registry entry.
    """

    asset: str
    glow_color: str
    glow_opacity: float = 0.34
    top_margin: int = 4
    # Fraction of the image's half-size that contains visible pixels.  The
    # ember art has a tall flame at the top, so this keeps the whole ring
    # inside the card instead of letting the viewport crop it.
    content_half_ratio: float = 0.99
    center_dx: float = 0.0
    center_dy: float = 0.0


# Every frame uses the same canvas/hole geometry: the canvas is 1.36x the
# avatar (icon) diameter, its centre is a 1.00x hole, and the glow is 1.08x the
# canvas.  See docs/AVATAR_FRAME_SPEC.md.
FRAME_CANVAS_SCALE = 1.36
FRAME_GLOW_SCALE = 1.08


# Equipped frames are a generic visual registry.  Adding an equipped frame
# means adding one entry here plus the PNG under ``web/assets/frames``.
FRAME_VISUALS: dict[str, FrameVisual] = {
    "frame_ember": FrameVisual(
        asset="frame_ember.png",
        glow_color="#ff5a1f",
    ),
    "frame_clown": FrameVisual(
        asset="frame_clown.png",
        glow_color="#ffc857",
    ),
}

_CARD_ICON_DIR = (
    Path(__file__).resolve().parents[1] / "web" / "assets" / "tiers" / "card"
)
_FRAME_ASSET_DIR = Path(__file__).resolve().parents[1] / "web" / "assets" / "frames"

# Registry of badge-card icon directories.  Adding a style only requires one
# entry here plus its card asset directory; unknown styles use classic.
TIER_ICON_THEMES: dict[str, Path] = {
    "classic": _CARD_ICON_DIR,
    "material": _CARD_ICON_DIR / "material",
}


@dataclass(frozen=True)
class BadgeGeometry:
    """Layout coordinates for one icon theme's SVG badge.

    The card artwork in each theme has different transparent padding, so the
    icon and the surrounding copy need independent scales and positions.
    Keeping every row here also makes the rendered viewBox and all clipping
    regions derive from the same source of truth.
    """

    height: int
    icon_size: int
    icon_x: int
    icon_y: int
    icon_glow_radius: int
    icon_disc_radius: int
    fallback_ring_radius: int
    fallback_inner_radius: int
    tier_label_y: int
    left_divider_x: int
    left_divider_top: int
    left_divider_bottom: int
    content_x: int
    name_y: int
    name_clip_y: int
    name_clip_width: int
    activity_y: int
    group_y: int
    right_divider_x: int
    right_divider_top: int
    right_divider_bottom: int
    right_content_x: int
    week_y: int
    stat_cards_y: int
    bottom_line_y: int
    bottom_text_y: int
    bar_x: int
    bar_y: int
    bar_width: int
    checkin_y: int

    @property
    def icon_center_x(self) -> int:
        return self.icon_x + self.icon_size // 2

    @property
    def icon_center_y(self) -> int:
        return self.icon_y + self.icon_size // 2

    @property
    def activity_text_y(self) -> int:
        return self.activity_y + 21

    @property
    def xp_clip_y(self) -> int:
        return self.week_y + 6

    @property
    def xp_y(self) -> int:
        return self.week_y + 58

    @property
    def stat_label_y(self) -> int:
        return self.stat_cards_y + 16

    @property
    def stat_value_y(self) -> int:
        return self.stat_cards_y + 38

    @property
    def checkin_center_y(self) -> int:
        return self.checkin_y + 17

    @property
    def checkin_text_y(self) -> int:
        return self.checkin_y + 23


# Material card assets are cropped to their alpha bounds and padded by 4% of
# the short side.  A single canvas size cannot equalize visible area across the
# ten differently-shaped marks, so each size below is computed from the actual
# trimmed alpha coverage.  At 144 px the classic badge shows about 16,286
# alpha-weighted pixels; the formula used for every material tier was
# ``round(sqrt(16286 * trimmed_side**2 / alpha_sum))``.
CLASSIC_VISIBLE_ALPHA_AREA = 16286.08
MATERIAL_ICON_SIZES: dict[str, int] = {
    "bronze": 172,
    "silver": 171,
    "gold": 164,
    "sapphire": 194,
    "ruby": 194,
    "emerald": 174,
    "amethyst": 174,
    "pearl": 166,
    "obsidian": 192,
    "diamond": 196,
}

# ``classic`` restores the task75 layout exactly.  ``material`` uses the
# trimmed assets above and a 280 px card so the icon, tier label and bottom row
# stay clear of each other.
BADGE_GEOMETRIES: dict[str, BadgeGeometry] = {
    "classic": BadgeGeometry(
        height=260,
        icon_size=144,
        icon_x=36,
        icon_y=26,
        icon_glow_radius=82,
        icon_disc_radius=72,
        fallback_ring_radius=58,
        fallback_inner_radius=46,
        tier_label_y=190,
        left_divider_x=197,
        left_divider_top=56,
        left_divider_bottom=190,
        content_x=220,
        name_y=84,
        name_clip_y=52,
        name_clip_width=306,
        activity_y=96,
        group_y=158,
        right_divider_x=538,
        right_divider_top=56,
        right_divider_bottom=190,
        right_content_x=558,
        week_y=70,
        stat_cards_y=142,
        bottom_line_y=198,
        bottom_text_y=225,
        bar_x=208,
        bar_y=210,
        bar_width=526,
        checkin_y=201,
    ),
    "material": BadgeGeometry(
        height=280,
        icon_size=168,
        icon_x=24,
        icon_y=12,
        icon_glow_radius=104,
        icon_disc_radius=94,
        fallback_ring_radius=78,
        fallback_inner_radius=62,
        tier_label_y=230,
        left_divider_x=216,
        left_divider_top=56,
        left_divider_bottom=232,
        content_x=238,
        name_y=96,
        name_clip_y=64,
        name_clip_width=284,
        activity_y=108,
        group_y=176,
        right_divider_x=538,
        right_divider_top=56,
        right_divider_bottom=218,
        right_content_x=558,
        week_y=78,
        stat_cards_y=152,
        bottom_line_y=240,
        bottom_text_y=267,
        bar_x=208,
        bar_y=252,
        bar_width=526,
        checkin_y=243,
    ),
}


def _badge_geometry(tier_name: str, icon_theme: str) -> BadgeGeometry:
    """Return theme geometry with the tier-specific material icon scale."""

    geometry = BADGE_GEOMETRIES.get(
        icon_theme,
        BADGE_GEOMETRIES[DEFAULT_ICON_THEME],
    )
    if icon_theme != "material":
        return geometry
    slug = TIER_SLUGS.get(tier_name, "bronze")
    icon_size = MATERIAL_ICON_SIZES[slug]
    # Keep the icon centred in the left column; the widest material mark is
    # still comfortably left of the divider at x=216.
    return replace(
        geometry,
        icon_size=icon_size,
        icon_x=108 - icon_size // 2,
    )

_FONT_FAMILY = (
    "'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', "
    "system-ui, sans-serif"
)


def xml_escape(value: object) -> str:
    """Escape text for XML text nodes and quoted attributes."""

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _xp(seconds: object) -> int:
    try:
        value = int(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, value) // 6


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _tier_group_label(tier: object, group_id: object) -> str:
    tier_name = str(tier or "Bronze")
    label = TIER_LABELS.get(tier_name, tier_name)
    group = str(group_id or "")
    suffix = group.split("-", 1)[1] if "-" in group else group
    return f"{label} · {suffix}" if suffix else label


def _short_time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "--:--"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "--:--"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(TZ)
    return parsed.strftime("%H:%M")


def _tier_visual(tier: object) -> tuple[str, str, str]:
    """Return the Chinese label and accent colours for one tier."""

    tier_name = str(tier or "Bronze")
    if tier_name not in TIER_VISUALS:
        tier_name = "Bronze"
    accent, accent_dark = TIER_VISUALS[tier_name]
    return TIER_LABELS[tier_name], accent, accent_dark


@lru_cache(maxsize=len(TIER_SLUGS) * len(TIER_ICON_THEMES))
def _tier_icon_data_uri(tier: object, theme: object = DEFAULT_ICON_THEME) -> str | None:
    """Return one optimized tier icon as a self-contained PNG data URI.

    The requested theme is part of the cache key.  Unknown themes and missing
    files transparently reuse the classic artwork; if neither exists the badge
    renderer keeps its existing letter-free ring fallback.
    """

    tier_name = str(tier or "Bronze")
    slug = TIER_SLUGS.get(tier_name, "bronze")
    requested_theme = icon_theme_or_default(theme)
    candidates = [requested_theme]
    if requested_theme != DEFAULT_ICON_THEME:
        candidates.append(DEFAULT_ICON_THEME)
    for candidate in candidates:
        directory = TIER_ICON_THEMES.get(candidate, _CARD_ICON_DIR)
        try:
            payload = (directory / f"{slug}.png").read_bytes()
        except OSError:
            continue
        if payload:
            encoded = base64.b64encode(payload).decode("ascii")
            return f"data:image/png;base64,{encoded}"
    return None


@lru_cache(maxsize=None)
def _frame_data_uri(asset: str) -> str | None:
    """Return one equipped frame PNG as a self-contained data URI."""

    if not asset or Path(asset).name != asset:
        return None
    try:
        payload = (_FRAME_ASSET_DIR / asset).read_bytes()
    except OSError:
        return None
    if not payload:
        return None
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _frame_markup(frame_id: object, geometry: BadgeGeometry) -> tuple[str, str]:
    """Return ``(defs, markup)`` for one equipped frame, if it has artwork.

    The image is centred on the icon and drawn before the icon, so the icon
    stays crisp over the transparent middle of the frame.  The canvas is always
    1.36x the icon diameter, with a 1.00x transparent centre; the frame artwork
    itself must not add its own padding or per-asset scale.  The top margin keeps
    the ring inside the card viewport for the tall ember flame.
    """

    key = str(frame_id or "").strip()
    visual = FRAME_VISUALS.get(key)
    if visual is None:
        return "", ""
    data_uri = _frame_data_uri(visual.asset)
    if data_uri is None:
        return "", ""

    size = geometry.icon_size * FRAME_CANVAS_SCALE
    half = size / 2
    cx = geometry.icon_center_x + visual.center_dx
    cy = geometry.icon_center_y + visual.center_dy
    min_cy = half * visual.content_half_ratio + visual.top_margin
    if cy < min_cy:
        cy = min_cy
    x = cx - half
    y = cy - half
    glow_radius = half * FRAME_GLOW_SCALE

    defs = f'''
    <radialGradient id="badge-frame-glow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0.52" stop-color="{visual.glow_color}" stop-opacity="{visual.glow_opacity}"/>
      <stop offset="0.78" stop-color="{visual.glow_color}" stop-opacity="{visual.glow_opacity * 0.42:.3f}"/>
      <stop offset="1" stop-color="{visual.glow_color}" stop-opacity="0"/>
    </radialGradient>'''
    markup = f'''
  <g class="badge-frame" data-frame="{xml_escape(key)}">
    <circle cx="{cx:.2f}" cy="{cy:.2f}" r="{glow_radius:.2f}" fill="url(#badge-frame-glow)"/>
    <image class="badge-frame-image" x="{x:.2f}" y="{y:.2f}" width="{size:.2f}" height="{size:.2f}" preserveAspectRatio="xMidYMid meet" href="{data_uri}"/>
  </g>'''
    return defs, markup


def _display_width(value: object, size: float) -> int:
    """Approximate the rendered width of a short label without a font engine."""

    units = 0.0
    for char in str(value):
        if char.isspace():
            units += 0.45
        elif ord(char) < 128:
            units += 0.58
        else:
            units += 1.0
    return round(units * size)


def render_badge(status: Mapping[str, Any]) -> str:
    """Render one status snapshot as a self-contained SVG status card."""

    raw_name = str(status.get("display_name") or status.get("user_id") or "—")
    raw_activity = str(status.get("activity_label") or "练习")
    tier_name = str(status.get("tier") or "Bronze")
    icon_theme = icon_theme_or_default(status.get("icon_theme"))
    geometry = _badge_geometry(tier_name, icon_theme)
    tier_label, tier_accent, tier_accent_dark = _tier_visual(tier_name)

    display_name = xml_escape(raw_name)
    activity_line = f"活动 · {raw_activity}"
    activity_label = xml_escape(activity_line)
    group = status.get("group")
    group_no = group.get("no") if isinstance(group, Mapping) else None
    group_label = group.get("label") if isinstance(group, Mapping) else None
    if isinstance(group_label, str) and group_label:
        tier_group = xml_escape(group_label)
    else:
        tier_group = xml_escape(
            _tier_group_label(
                status.get("tier"),
                f"G{int(group_no):02d}" if isinstance(group_no, int) else "",
            )
        )
    tier_label_escaped = xml_escape(tier_label)
    equipped_title = str(status.get("equipped_title") or "").strip()
    title_markup = ""
    if equipped_title:
        title_line = xml_escape(f"称号 · {equipped_title}")
        title_markup = (
            f'\n  <text x="{geometry.content_x}" y="{geometry.group_y + 23}" '
            f'font-family="{_FONT_FAMILY}" font-size="15" font-weight="700" '
            f'fill="{tier_accent}">{title_line}</text>'
        )
    frame_defs, frame_markup = _frame_markup(status.get("frame_id"), geometry)
    tier_icon_uri = _tier_icon_data_uri(tier_name, icon_theme)
    updated_at = xml_escape(_short_time(status.get("updated_at")))

    today_seconds = max(0, _integer(status.get("today_seconds")))
    required_xp = max(0, _integer(status.get("required_xp")))
    target_seconds = required_xp * SECONDS_PER_XP
    week_xp = max(0, _integer(status.get("xp")))
    today_xp = max(0, _integer(status.get("today_xp")))
    target_xp = required_xp
    rank = _integer(status.get("rank"))
    group_size = _integer(status.get("group_size"))
    streak = status.get("streak")
    current_streak = _integer(
        streak.get("current") if isinstance(streak, Mapping) else 0
    )
    checked_in = bool(status.get("checkin"))

    # Progress is deliberately based on raw seconds.  XP is rounded down for
    # display, so using the rounded values here would change when the bar fills.
    if target_seconds > 0:
        progress = min(100.0, max(0.0, (today_seconds / target_seconds) * 100))
    else:
        progress = 0.0
    filled_width = round(geometry.bar_width * progress / 100, 1)
    progress_bar = ""
    if filled_width > 0:
        progress_bar = (
            f'<rect x="{geometry.bar_x}" y="{geometry.bar_y}" '
            f'width="{filled_width}" height="14" '
            f'rx="7" fill="{tier_accent}"/>'
        )

    # Keep larger XP values inside the fixed right-hand column.  The common
    # three-digit case keeps its original 56px size; longer values only step
    # down as far as needed.
    week_xp_text = f"{week_xp} XP"
    week_xp_font_size = 56
    while (
        week_xp_font_size > 40
        and _display_width(week_xp_text, week_xp_font_size) > 278
    ):
        week_xp_font_size -= 2

    if checked_in:
        checkin_fill = "#5ce0be"
        checkin_text = "已打卡"
    else:
        checkin_fill = "#f6c86a"
        checkin_text = "未打卡"

    activity_width = min(286, max(150, _display_width(activity_line, 16) + 40))

    # The icon sits in its own left column with the Chinese tier label
    # underneath.  A ring keeps the card readable if an icon file is missing.
    if tier_icon_uri is None:
        tier_icon_markup = (
            f'<circle cx="{geometry.icon_center_x}" cy="{geometry.icon_center_y}" '
            f'r="{geometry.fallback_ring_radius}" fill="#0d1425" '
            f'fill-opacity="0.52" stroke="{tier_accent}" stroke-width="8" '
            f'stroke-opacity="0.9"/>'
            f'<circle cx="{geometry.icon_center_x}" cy="{geometry.icon_center_y}" '
            f'r="{geometry.fallback_inner_radius}" fill="none" '
            f'stroke="{tier_accent}" stroke-width="2" stroke-opacity="0.42"/>'
        )
    else:
        tier_icon_markup = (
            f'<image x="{geometry.icon_x}" y="{geometry.icon_y}" '
            f'width="{geometry.icon_size}" height="{geometry.icon_size}" '
            f'preserveAspectRatio="xMidYMid meet" href="{tier_icon_uri}"/>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 {geometry.height}" width="880" height="{geometry.height}" role="img" aria-labelledby="badge-title badge-desc">
  <title id="badge-title">联赛状态</title>
  <desc id="badge-desc">{display_name} 的联赛状态</desc>
  <defs>
    <linearGradient id="badge-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0b1020"/>
      <stop offset="0.55" stop-color="#11182b"/>
      <stop offset="1" stop-color="#171d33"/>
    </linearGradient>
    <linearGradient id="badge-tier" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{tier_accent}" stop-opacity="0.55"/>
      <stop offset="1" stop-color="{tier_accent_dark}" stop-opacity="0.22"/>
    </linearGradient>
    <linearGradient id="badge-accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{tier_accent}"/>
      <stop offset="1" stop-color="#5ce0be"/>
    </linearGradient>
    <radialGradient id="badge-glow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="{tier_accent}" stop-opacity="0.20"/>
      <stop offset="1" stop-color="{tier_accent}" stop-opacity="0"/>
    </radialGradient>{frame_defs}
    <clipPath id="badge-name-clip"><rect x="{geometry.content_x}" y="{geometry.name_clip_y}" width="{geometry.name_clip_width}" height="42" rx="4"/></clipPath>
    <clipPath id="badge-activity-clip"><rect x="{geometry.content_x}" y="{geometry.activity_y}" width="{activity_width}" height="30" rx="15"/></clipPath>
    <clipPath id="badge-xp-clip"><rect x="{geometry.right_content_x}" y="{geometry.xp_clip_y}" width="290" height="58" rx="4"/></clipPath>
  </defs>
  <rect width="880" height="{geometry.height}" rx="24" fill="url(#badge-bg)"/>
  <rect x="1" y="1" width="878" height="{geometry.height - 2}" rx="23" fill="none" stroke="#2a3352"/>
  <circle cx="826" cy="46" r="142" fill="url(#badge-glow)"/>
  <circle cx="826" cy="46" r="74" fill="{tier_accent}" opacity="0.035"/>
  <rect x="{geometry.content_x}" y="18" width="5" height="24" rx="2.5" fill="url(#badge-accent)"/>
  <text x="{geometry.content_x + 16}" y="39" font-family="{_FONT_FAMILY}" font-size="27" font-weight="700" fill="#f4f7ff">联赛状态</text>
  <text x="848" y="37" text-anchor="end" font-family="{_FONT_FAMILY}" font-size="15" fill="#9aa6c8">最后更新 {updated_at}</text>

  <circle cx="{geometry.icon_center_x}" cy="{geometry.icon_center_y}" r="{geometry.icon_glow_radius}" fill="url(#badge-glow)"/>
  <circle cx="{geometry.icon_center_x}" cy="{geometry.icon_center_y}" r="{geometry.icon_disc_radius}" fill="{tier_accent}" opacity="0.07"/>{frame_markup}
  {tier_icon_markup}
  <text x="{geometry.icon_center_x}" y="{geometry.tier_label_y}" text-anchor="middle" font-family="{_FONT_FAMILY}" font-size="18" font-weight="700" fill="{tier_accent}">{tier_label_escaped}</text>

  <line x1="{geometry.left_divider_x}" y1="{geometry.left_divider_top}" x2="{geometry.left_divider_x}" y2="{geometry.left_divider_bottom}" stroke="#29314d"/>
  <g clip-path="url(#badge-name-clip)">
    <text x="{geometry.content_x}" y="{geometry.name_y}" font-family="{_FONT_FAMILY}" font-size="36" font-weight="700" fill="#f4f7ff">{display_name}</text>
  </g>
  <rect x="{geometry.content_x}" y="{geometry.activity_y}" width="{activity_width}" height="30" rx="15" fill="{tier_accent}" fill-opacity="0.10" stroke="{tier_accent}" stroke-opacity="0.28"/>
  <circle cx="{geometry.content_x + 16}" cy="{geometry.activity_y + 15}" r="4" fill="{tier_accent}"/>
  <g clip-path="url(#badge-activity-clip)">
    <text x="{geometry.content_x + 28}" y="{geometry.activity_text_y}" font-family="{_FONT_FAMILY}" font-size="16" font-weight="600" fill="{tier_accent}">{activity_label}</text>
  </g>
  <text x="{geometry.content_x}" y="{geometry.group_y}" font-family="{_FONT_FAMILY}" font-size="20" font-weight="600" fill="#cbd5f5">{tier_group}</text>{title_markup}

  <line x1="{geometry.right_divider_x}" y1="{geometry.right_divider_top}" x2="{geometry.right_divider_x}" y2="{geometry.right_divider_bottom}" stroke="#29314d"/>
  <text x="{geometry.right_content_x}" y="{geometry.week_y}" font-family="{_FONT_FAMILY}" font-size="24" font-weight="700" fill="#c2cdea">本周</text>
  <g clip-path="url(#badge-xp-clip)">
    <text x="{geometry.right_content_x}" y="{geometry.xp_y}" font-family="{_FONT_FAMILY}" font-size="{week_xp_font_size}" font-weight="800" fill="#ffffff">{week_xp_text}</text>
  </g>

  <rect x="{geometry.right_content_x}" y="{geometry.stat_cards_y}" width="138" height="46" rx="11" fill="#ffffff" fill-opacity="0.025" stroke="#ffffff" stroke-opacity="0.045"/>
  <text x="{geometry.right_content_x + 12}" y="{geometry.stat_label_y}" font-family="{_FONT_FAMILY}" font-size="13" fill="#8f9bbb">组内排名</text>
  <text x="{geometry.right_content_x + 12}" y="{geometry.stat_value_y}" font-family="{_FONT_FAMILY}" font-size="18" font-weight="700" fill="#f4f7ff">第 {rank} / {group_size}</text>

  <rect x="{geometry.right_content_x + 152}" y="{geometry.stat_cards_y}" width="138" height="46" rx="11" fill="#ffffff" fill-opacity="0.025" stroke="#ffffff" stroke-opacity="0.045"/>
  <text x="{geometry.right_content_x + 164}" y="{geometry.stat_label_y}" font-family="{_FONT_FAMILY}" font-size="13" fill="#8f9bbb">当前连胜</text>
  <text x="{geometry.right_content_x + 164}" y="{geometry.stat_value_y}" font-family="{_FONT_FAMILY}" font-size="18" font-weight="700" fill="#f4f7ff">{current_streak} 天</text>

  <line x1="32" y1="{geometry.bottom_line_y}" x2="848" y2="{geometry.bottom_line_y}" stroke="#29314d"/>
  <text x="32" y="{geometry.bottom_text_y}" font-family="{_FONT_FAMILY}" font-size="17" font-weight="600" fill="#c7d2ef">今日 {today_xp} / {target_xp} XP</text>
  <rect x="{geometry.bar_x}" y="{geometry.bar_y}" width="{geometry.bar_width}" height="14" rx="7" fill="#252d49"/>
  {progress_bar}
  <rect x="748" y="{geometry.checkin_y}" width="100" height="34" rx="17" fill="{checkin_fill}" fill-opacity="0.12" stroke="{checkin_fill}" stroke-opacity="0.38"/>
  <circle cx="765" cy="{geometry.checkin_center_y}" r="4.5" fill="{checkin_fill}"/>
  <text x="778" y="{geometry.checkin_text_y}" font-family="{_FONT_FAMILY}" font-size="16" font-weight="700" fill="{checkin_fill}">{checkin_text}</text>
</svg>'''


def render_embed(user_id: str) -> str:
    """Render the minimal auto-refreshing iframe page for one account."""

    badge_url = xml_escape(f"/badge/{quote(user_id, safe='')}.svg")
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>联赛状态</title>
  <style>
    html, body {{ margin: 0; padding: 0; background: transparent; }}
    body {{ overflow: hidden; }}
    img {{ display: block; width: 100%; height: auto; border: 0; }}
  </style>
</head>
<body>
  <img src="{badge_url}" width="880" alt="联赛状态">
</body>
</html>'''


__all__ = [
    "BADGE_GEOMETRIES",
    "BadgeGeometry",
    "TIER_ICON_THEMES",
    "TIER_LABELS",
    "render_badge",
    "render_embed",
    "xml_escape",
]
