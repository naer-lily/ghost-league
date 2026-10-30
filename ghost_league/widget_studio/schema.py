"""Validation and selection rules for Widget Studio templates.

A template is plain JSON on disk.  This module is deliberately free of HTTP and
database concerns so the store, renderer and tests share exactly one schema.

Version 4 stores every style next to the background it belongs to:
``backgrounds[].styles`` is the only style source.  The streak number and the
flame form one counter component whose layout is only an anchor
(``backgrounds[].layout.counter``); ``counter.scale`` and ``counter.gap`` drive
the pair together.  Text variants keep their own positions but share the
background's ``styles.label``.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

CANVAS_WIDTH = 1536
CANVAS_HEIGHT = 914
CANVAS_RADIUS = 128
TEMPLATE_VERSION = 4
MIGRATION_SCRIPT = "scripts/migrate_widget_template_v4.py"
MAX_FILE_BYTES = 15 * 1024 * 1024

TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ASSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

WHEN_FIELDS = {
    "hour_from",
    "hour_to",
    "weekdays",
    "streak_min",
    "streak_max",
    "completed_today",
    "league",
    "event",
}
TEXT_ALIGNS = {"left", "center", "right"}
FITS = {"cover", "contain"}
STYLE_KEYS = {"label", "counter"}
COUNTER_SCALE_MIN = 0.5
COUNTER_SCALE_MAX = 2.0
COUNTER_GAP_MIN = 0
COUNTER_GAP_MAX = 160
LETTER_SPACING_MIN = -10
LETTER_SPACING_MAX = 40
STROKE_WIDTH_MIN = 0
STROKE_WIDTH_MAX = 12


class ValidationError(ValueError):
    """Raised when a template, asset path or condition is invalid."""


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{field} must be a number")
    number = float(value)
    _require(number == number and abs(number) != float("inf"), f"{field} must be finite")
    if minimum is not None:
        _require(number >= minimum, f"{field} must be >= {minimum}")
    return number


def _bounded_number(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    number = _number(value, field)
    _require(minimum <= number <= maximum, f"{field} must be {minimum}-{maximum}")
    return number


def _text(value: Any, field: str, *, minimum: int = 0, maximum: int = 200) -> str:
    _require(isinstance(value, str), f"{field} must be a string")
    cleaned = value
    _require(minimum <= len(cleaned) <= maximum, f"{field} must be {minimum}-{maximum} characters")
    return cleaned


def slugify(name: str) -> str:
    """Turn a display name into a safe template id.

    ASCII letters/digits are kept.  Names made only of CJK characters fall back
    to ``widget``; the store appends ``-2`` and so on on collision.
    """

    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    slug = slug[:64].strip("-")
    return slug or "widget"


def validate_template_id(template_id: Any) -> str:
    if not isinstance(template_id, str) or not TEMPLATE_ID_RE.fullmatch(template_id):
        raise ValidationError("invalid template id")
    return template_id


def validate_asset_id(asset_id: Any) -> str:
    if not isinstance(asset_id, str) or not ASSET_ID_RE.fullmatch(asset_id):
        raise ValidationError("invalid asset id")
    return asset_id


def validate_src(src: Any, *, template_dir: Path, web_root: Path) -> str:
    """Validate a local template path or a ``ghost:assets/...`` path.

    The resulting resolved path must stay inside the allowed root.  Absolute
    paths, URLs, ``..`` segments and backslashes are rejected.
    """

    if not isinstance(src, str) or not src or len(src) > 300:
        raise ValidationError("src must be a relative asset path")
    _require("\\" not in src, "src cannot contain backslashes")
    _require("://" not in src, "src cannot be a URL")

    if src.startswith("ghost:"):
        relative = src[len("ghost:") :]
        _require(relative.startswith("assets/"), "ghost src must point at assets/")
        _require(not relative.startswith("/"), "ghost src cannot be absolute")
        parts = PurePosixPath(relative).parts
        _require(".." not in parts and "." not in parts, "ghost src cannot contain . or ..")
        _require(bool(parts), "ghost src is empty")
        candidate = (web_root / Path(*parts)).resolve()
        root = web_root.resolve()
        _require(candidate.is_relative_to(root), "ghost src escapes the web root")
        _require(candidate.suffix.lower() in IMAGE_SUFFIXES, "ghost src must be an image")
        return src

    _require(not src.startswith("/"), "src cannot be absolute")
    parts = PurePosixPath(src).parts
    _require(bool(parts), "src is empty")
    _require(".." not in parts and "." not in parts, "src cannot contain . or ..")
    candidate = (template_dir / Path(*parts)).resolve()
    root = template_dir.resolve()
    _require(candidate.is_relative_to(root), "src escapes the template directory")
    _require(candidate.suffix.lower() in IMAGE_SUFFIXES, "src must be an image")
    return src


def resolve_src(src: str, *, template_dir: Path, web_root: Path) -> Path:
    validate_src(src, template_dir=template_dir, web_root=web_root)
    if src.startswith("ghost:"):
        return (web_root / Path(*PurePosixPath(src[len("ghost:") :]).parts)).resolve()
    return (template_dir / Path(*PurePosixPath(src).parts)).resolve()


def normalize_when(raw: Any, field: str = "when") -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object")
    unknown = set(raw) - WHEN_FIELDS
    if unknown:
        raise ValidationError(f"{field} has unknown fields: {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {}

    has_from = "hour_from" in raw
    has_to = "hour_to" in raw
    if has_from != has_to:
        raise ValidationError(f"{field} needs both hour_from and hour_to")
    if has_from:
        start, end = raw["hour_from"], raw["hour_to"]
        if not is_int(start) or not 0 <= start <= 23:
            raise ValidationError(f"{field}.hour_from must be 0-23")
        if not is_int(end) or not 0 <= end <= 23:
            raise ValidationError(f"{field}.hour_to must be 0-23")
        result["hour_from"] = start
        result["hour_to"] = end

    if "weekdays" in raw:
        weekdays = raw["weekdays"]
        if not isinstance(weekdays, list) or not weekdays:
            raise ValidationError(f"{field}.weekdays must be a non-empty list")
        cleaned: list[int] = []
        for day in weekdays:
            if not is_int(day) or not 1 <= day <= 7:
                raise ValidationError(f"{field}.weekdays must contain 1-7")
            if day not in cleaned:
                cleaned.append(day)
        result["weekdays"] = cleaned

    for key in ("streak_min", "streak_max"):
        if key in raw:
            value = raw[key]
            if not is_int(value) or value < 0:
                raise ValidationError(f"{field}.{key} must be a non-negative integer")
            result[key] = value
    if (
        "streak_min" in result
        and "streak_max" in result
        and result["streak_min"] > result["streak_max"]
    ):
        raise ValidationError(f"{field}.streak_min cannot exceed streak_max")

    if "completed_today" in raw:
        if not isinstance(raw["completed_today"], bool):
            raise ValidationError(f"{field}.completed_today must be a boolean")
        result["completed_today"] = raw["completed_today"]

    for key in ("league", "event"):
        if key in raw:
            value = raw[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 64:
                raise ValidationError(f"{field}.{key} must be 1-64 characters")
            result[key] = value

    return result


def _normalize_shadow(raw: Any, field: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object or null")
    color = raw.get("color", "rgba(0,0,0,0.35)")
    if not isinstance(color, str) or not 1 <= len(color) <= 64:
        raise ValidationError(f"{field}.color must be a CSS color")
    blur = _number(raw.get("blur", 0), f"{field}.blur", minimum=0)
    return {
        "color": color,
        "blur": blur,
        "offsetX": _number(raw.get("offsetX", 0), f"{field}.offsetX"),
        "offsetY": _number(raw.get("offsetY", 0), f"{field}.offsetY"),
    }


def _normalize_text_style(
    raw: Any, field: str, *, decorated: bool
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object")
    align = raw.get("align", "left")
    if align not in TEXT_ALIGNS:
        raise ValidationError(f"{field}.align must be left, center or right")
    color = raw.get("color", "#17324d")
    if not isinstance(color, str) or not 1 <= len(color) <= 64:
        raise ValidationError(f"{field}.color must be a CSS color")
    font_weight = raw.get("fontWeight", 400)
    if not is_int(font_weight) or not 100 <= font_weight <= 900:
        raise ValidationError(f"{field}.fontWeight must be 100-900")
    style = {
        "width": _number(raw.get("width", 520), f"{field}.width", minimum=1),
        "height": _number(raw.get("height", 100), f"{field}.height", minimum=1),
        "fontSize": _number(raw.get("fontSize", 48), f"{field}.fontSize", minimum=1),
        "fontWeight": font_weight,
        "color": color,
        "align": align,
        "lineHeight": _number(raw.get("lineHeight", 1.2), f"{field}.lineHeight", minimum=0.1),
        "shadow": _normalize_shadow(raw.get("shadow"), f"{field}.shadow"),
    }
    if decorated:
        letter_spacing = _bounded_number(
            raw.get("letterSpacing", 0),
            f"{field}.letterSpacing",
            minimum=LETTER_SPACING_MIN,
            maximum=LETTER_SPACING_MAX,
        )
        stroke_width = _bounded_number(
            raw.get("strokeWidth", 0),
            f"{field}.strokeWidth",
            minimum=STROKE_WIDTH_MIN,
            maximum=STROKE_WIDTH_MAX,
        )
        stroke_color = raw.get("strokeColor", color)
        if not isinstance(stroke_color, str) or not 1 <= len(stroke_color) <= 64:
            raise ValidationError(f"{field}.strokeColor must be a CSS color")
        style["letterSpacing"] = letter_spacing
        style["strokeWidth"] = stroke_width
        style["strokeColor"] = stroke_color
    return style


def normalize_text_style(raw: Any, field: str) -> dict[str, Any]:
    """Normalize the shared text/label style (includes typography extras)."""

    return _normalize_text_style(raw, field, decorated=True)


def normalize_number_style(raw: Any, field: str) -> dict[str, Any]:
    """Normalize the counter number style (no letter spacing/stroke knobs)."""

    return _normalize_text_style(raw, field, decorated=False)


def normalize_flame_style(raw: Any, field: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object")
    opacity = _number(raw.get("opacity", 1), f"{field}.opacity", minimum=0)
    if opacity > 1:
        raise ValidationError(f"{field}.opacity must be 0-1")
    return {
        "width": _number(raw.get("width", 120), f"{field}.width", minimum=1),
        "height": _number(raw.get("height", 140), f"{field}.height", minimum=1),
        "opacity": opacity,
    }


def normalize_counter_style(raw: Any, field: str = "styles.counter") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object")
    return {
        "scale": _bounded_number(
            raw.get("scale", 1.0),
            f"{field}.scale",
            minimum=COUNTER_SCALE_MIN,
            maximum=COUNTER_SCALE_MAX,
        ),
        "gap": _bounded_number(
            raw.get("gap", 30),
            f"{field}.gap",
            minimum=COUNTER_GAP_MIN,
            maximum=COUNTER_GAP_MAX,
        ),
        "flame": normalize_flame_style(raw.get("flame"), f"{field}.flame"),
        "number": normalize_number_style(raw.get("number"), f"{field}.number"),
    }


def normalize_styles(raw: Any, field: str = "styles") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object")
    missing = STYLE_KEYS - set(raw)
    if missing:
        raise ValidationError(f"{field} is missing: {', '.join(sorted(missing))}")
    return {
        "label": normalize_text_style(raw["label"], f"{field}.label"),
        "counter": normalize_counter_style(raw["counter"], f"{field}.counter"),
    }


def _normalize_position(raw: Any, field: str) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object with x and y")
    return {
        "x": _number(raw.get("x"), f"{field}.x"),
        "y": _number(raw.get("y"), f"{field}.y"),
    }


def normalize_layout(raw: Any, index: int) -> dict[str, Any]:
    field = f"backgrounds[{index}].layout"
    if not isinstance(raw, dict):
        raise ValidationError(f"{field} must be an object")
    unknown = set(raw) - {"counter", "texts"}
    if unknown:
        raise ValidationError(
            f"{field} has unknown fields: {', '.join(sorted(unknown))}; "
            "version 4 only has counter and texts"
        )
    texts_raw = raw.get("texts")
    if not isinstance(texts_raw, list) or not texts_raw:
        raise ValidationError(f"{field}.texts must be a non-empty list")
    texts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text_index, item in enumerate(texts_raw):
        text_field = f"{field}.texts[{text_index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{text_field} must be an object")
        text_id = item.get("id")
        if not isinstance(text_id, str) or not ASSET_ID_RE.fullmatch(text_id):
            raise ValidationError(f"{text_field}.id is invalid")
        if text_id in seen:
            raise ValidationError(f"{field} has duplicate text id: {text_id}")
        seen.add(text_id)
        texts.append(
            {
                "id": text_id,
                "text": _text(item.get("text", ""), f"{text_field}.text", maximum=500),
                "x": _number(item.get("x"), f"{text_field}.x"),
                "y": _number(item.get("y"), f"{text_field}.y"),
            }
        )
    return {
        "counter": _normalize_position(raw.get("counter"), f"{field}.counter"),
        "texts": texts,
    }


def normalize_background(
    raw: Any,
    index: int,
    *,
    template_dir: Path,
    web_root: Path,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError(f"backgrounds[{index}] must be an object")
    bg_id = validate_asset_id(raw.get("id"))
    src = validate_src(raw.get("src"), template_dir=template_dir, web_root=web_root)
    name = raw.get("name", bg_id)
    if not isinstance(name, str) or not 1 <= len(name) <= 80:
        raise ValidationError(f"backgrounds[{index}].name must be 1-80 characters")
    priority = raw.get("priority", 0)
    if not is_int(priority) or not -1_000_000 <= priority <= 1_000_000:
        raise ValidationError(f"backgrounds[{index}].priority must be an integer")
    fit = raw.get("fit", "cover")
    if fit not in FITS:
        raise ValidationError(f"backgrounds[{index}].fit must be cover or contain")
    return {
        "id": bg_id,
        "name": name,
        "src": src,
        "when": normalize_when(raw.get("when", {}), f"backgrounds[{index}].when"),
        "priority": priority,
        "fit": fit,
        "offsetX": _number(raw.get("offsetX", 0), f"backgrounds[{index}].offsetX"),
        "offsetY": _number(raw.get("offsetY", 0), f"backgrounds[{index}].offsetY"),
        "scale": _number(raw.get("scale", 1), f"backgrounds[{index}].scale", minimum=0.01),
        "styles": normalize_styles(
            raw.get("styles"), f"backgrounds[{index}].styles"
        ),
        "layout": normalize_layout(raw.get("layout"), index),
    }


def normalize_template(
    raw: Any,
    *,
    template_dir: Path,
    web_root: Path,
    expected_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError("template must be a JSON object")
    version = raw.get("version")
    if version != TEMPLATE_VERSION:
        raise ValidationError(
            f"template version must be {TEMPLATE_VERSION}; "
            f"version {version!r} must be migrated with {MIGRATION_SCRIPT}"
        )
    if "layers" in raw:
        raise ValidationError(
            f"version {TEMPLATE_VERSION} templates do not have global layers; "
            f"migrate with {MIGRATION_SCRIPT}"
        )
    if "styles" in raw:
        raise ValidationError(
            f"version {TEMPLATE_VERSION} stores styles per background; "
            f"remove top-level styles and migrate with {MIGRATION_SCRIPT}"
        )
    template_id = validate_template_id(raw.get("id"))
    if expected_id is not None and template_id != expected_id:
        raise ValidationError("template id does not match the URL")
    name = raw.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValidationError("name must be 1-80 characters")

    canvas_raw = raw.get("canvas", {})
    if not isinstance(canvas_raw, dict):
        raise ValidationError("canvas must be an object")
    width = canvas_raw.get("width", CANVAS_WIDTH)
    height = canvas_raw.get("height", CANVAS_HEIGHT)
    radius = canvas_raw.get("radius", CANVAS_RADIUS)
    if not is_int(width) or not 1 <= width <= 8192:
        raise ValidationError("canvas.width must be 1-8192")
    if not is_int(height) or not 1 <= height <= 8192:
        raise ValidationError("canvas.height must be 1-8192")
    if not is_int(radius) or not 0 <= radius <= min(width, height) // 2:
        raise ValidationError("canvas.radius is out of range")

    backgrounds_raw = raw.get("backgrounds")
    if not isinstance(backgrounds_raw, list):
        raise ValidationError("backgrounds must be a list")
    backgrounds = [
        normalize_background(
            item, index, template_dir=template_dir, web_root=web_root
        )
        for index, item in enumerate(backgrounds_raw)
    ]
    if not backgrounds:
        raise ValidationError("every template needs at least one background")
    seen: set[str] = set()
    for background in backgrounds:
        if background["id"] in seen:
            raise ValidationError(f"duplicate background id: {background['id']}")
        seen.add(background["id"])
    if not any(not background["when"] for background in backgrounds):
        raise ValidationError("every template needs at least one fallback background (when: {})")

    normalized: dict[str, Any] = {
        "version": TEMPLATE_VERSION,
        "id": template_id,
        "name": name.strip(),
        "canvas": {"width": width, "height": height, "radius": radius},
        "backgrounds": backgrounds,
    }
    updated_at = raw.get("updated_at")
    if updated_at is not None:
        if not isinstance(updated_at, str) or not 1 <= len(updated_at) <= 64:
            raise ValidationError("updated_at must be an ISO timestamp string")
        normalized["updated_at"] = updated_at
    return normalized


def _hour_matches(hour: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def background_matches(background: dict[str, Any], context: dict[str, Any]) -> bool:
    when = background.get("when") or {}
    if not when:
        return True
    if "hour_from" in when:
        hour = context.get("hour")
        if not is_int(hour) or not _hour_matches(hour, when["hour_from"], when["hour_to"]):
            return False
    if "weekdays" in when:
        weekday = context.get("weekday")
        if not is_int(weekday) or weekday not in when["weekdays"]:
            return False
    if "streak_min" in when:
        streak = context.get("streak")
        if not is_int(streak) or streak < when["streak_min"]:
            return False
    if "streak_max" in when:
        streak = context.get("streak")
        if not is_int(streak) or streak > when["streak_max"]:
            return False
    if "completed_today" in when:
        completed = context.get("completed_today")
        if not isinstance(completed, bool) or completed != when["completed_today"]:
            return False
    if "league" in when:
        if context.get("league") != when["league"]:
            return False
    if "event" in when:
        if context.get("event") != when["event"]:
            return False
    return True


def select_background(
    template: dict[str, Any], context: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Return ``(background, used_fallback)`` for a context.

    Fallbacks are only considered after every conditional background has been
    tested, so a low-priority fallback can never shadow a specific rule.
    """

    backgrounds = template.get("backgrounds") or []
    conditional = [
        (index, background)
        for index, background in enumerate(backgrounds)
        if background.get("when")
    ]
    conditional.sort(key=lambda item: (-int(item[1].get("priority", 0)), item[0]))
    for _, background in conditional:
        if background_matches(background, context):
            return background, False
    for background in backgrounds:
        if not background.get("when"):
            return background, True
    raise ValidationError("template has no fallback background")


__all__ = [
    "ASSET_ID_RE",
    "CANVAS_HEIGHT",
    "CANVAS_RADIUS",
    "CANVAS_WIDTH",
    "COUNTER_GAP_MAX",
    "COUNTER_GAP_MIN",
    "COUNTER_SCALE_MAX",
    "COUNTER_SCALE_MIN",
    "FITS",
    "IMAGE_SUFFIXES",
    "LETTER_SPACING_MAX",
    "LETTER_SPACING_MIN",
    "MAX_FILE_BYTES",
    "MIGRATION_SCRIPT",
    "STROKE_WIDTH_MAX",
    "STROKE_WIDTH_MIN",
    "STYLE_KEYS",
    "TEMPLATE_VERSION",
    "ValidationError",
    "background_matches",
    "normalize_background",
    "normalize_counter_style",
    "normalize_flame_style",
    "normalize_layout",
    "normalize_number_style",
    "normalize_styles",
    "normalize_template",
    "normalize_text_style",
    "normalize_when",
    "resolve_src",
    "select_background",
    "slugify",
    "validate_asset_id",
    "validate_src",
    "validate_template_id",
]
