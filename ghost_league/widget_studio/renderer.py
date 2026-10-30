"""Pillow production renderer for Widget Studio templates (schema v3).

Styles are global: every label uses ``styles.label``, the streak number uses
``styles.streak`` and the flame uses ``styles.flame``.  Positions come from the
selected background's ``layout``.  One of the background's text variants is
chosen at random per request unless the caller pins ``text=<text-id>``.
"""

from __future__ import annotations

import io
import random
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

from .schema import resolve_src

FONT_REGULAR = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
FONT_BOLD = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
FONT_INDEX = 2  # Noto Sans CJK SC
PLACEHOLDER_RE = re.compile(r"\{(streak|xp|rank|name)\}")
CJK_RANGE = "\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef"
INCOMPLETE_STREAK_COLOR = "#9a9a9a"
INCOMPLETE_STREAK_SHADOW = "rgba(0,0,0,0.28)"
# Flame PNGs carry transparent padding around the visible artwork.  Crop to the
# alpha bbox, then keep ~9% breathing room inside the style box so the visible
# flame is roughly 200px tall for a 220px box (instead of shrinking to ~178px).
FLAME_VISIBLE_SCALE = 0.91
_FONT_CACHE: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}


class RenderError(ValueError):
    pass


def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    wanted = max(1, int(round(size)))
    key = (wanted, 700 if weight >= 600 else 400)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    path = FONT_BOLD if weight >= 600 else FONT_REGULAR
    try:
        font = ImageFont.truetype(str(path), wanted, index=FONT_INDEX)
    except OSError:
        font = ImageFont.load_default(size=wanted)
    _FONT_CACHE[key] = font
    return font


def parse_color(value: Any, default: tuple[int, int, int, int] = (0, 0, 0, 255)) -> tuple[int, int, int, int]:
    if not isinstance(value, str):
        return default
    text = value.strip()
    rgba = re.fullmatch(r"rgba?\(([^)]+)\)", text, re.IGNORECASE)
    if rgba:
        parts = [part.strip() for part in rgba.group(1).split(",")]
        if len(parts) not in {3, 4}:
            return default
        try:
            channels = [
                round(float(part[:-1]) * 2.55) if part.endswith("%") else round(float(part))
                for part in parts[:3]
            ]
            alpha = 255
            if len(parts) == 4:
                alpha = (
                    round(float(parts[3][:-1]) * 2.55)
                    if parts[3].endswith("%")
                    else round(float(parts[3]) * 255)
                )
        except ValueError:
            return default
        return (
            max(0, min(255, channels[0])),
            max(0, min(255, channels[1])),
            max(0, min(255, channels[2])),
            max(0, min(255, alpha)),
        )
    try:
        parsed = ImageColor.getrgb(text)
    except (ValueError, AttributeError):
        return default
    if len(parsed) == 3:
        return (*parsed, 255)
    return parsed  # type: ignore[return-value]


def _open_rgba(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            source.load()
            return source.convert("RGBA")
    except OSError as exc:
        raise RenderError(f"cannot read image: {path.name}") from exc


def _grayscale(image: Image.Image, brightness: float = 0.85) -> Image.Image:
    """Convert RGB to neutral gray while keeping the original alpha channel."""

    gray = ImageOps.grayscale(image.convert("RGB"))
    if brightness != 1:
        gray = gray.point(lambda value: round(value * brightness))
    return Image.merge("RGBA", (gray, gray, gray, image.getchannel("A")))


def _scaled_size(
    width: int, height: int, canvas_width: int, canvas_height: int, fit: str, scale: float
) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise RenderError("invalid image dimensions")
    cover = max(canvas_width / width, canvas_height / height)
    contain = min(canvas_width / width, canvas_height / height)
    ratio = (cover if fit == "cover" else contain) * max(0.01, scale)
    return max(1, round(width * ratio)), max(1, round(height * ratio))


def _paste_background(
    canvas: Image.Image,
    source: Image.Image,
    background: dict[str, Any],
) -> None:
    width, height = _scaled_size(
        source.width,
        source.height,
        canvas.width,
        canvas.height,
        background.get("fit", "cover"),
        float(background.get("scale", 1)),
    )
    resized = source.resize((width, height), Image.Resampling.LANCZOS)
    x = (canvas.width - width) // 2 + round(float(background.get("offsetX", 0)))
    y = (canvas.height - height) // 2 + round(float(background.get("offsetY", 0)))
    canvas.alpha_composite(resized, (x, y))


def _format_text(value: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        item = context.get(key)
        return "" if item is None else str(item)

    return PLACEHOLDER_RE.sub(replace, value)


def _tokens(paragraph: str) -> list[str]:
    """Split into wrap tokens: CJK characters stand alone, English by words."""

    tokens: list[str] = []
    for match in re.finditer(
        rf"\s+|[{CJK_RANGE}]|[^\s{CJK_RANGE}]+", paragraph
    ):
        tokens.append(match.group(0))
    return tokens


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[tuple[str, float]]:
    lines: list[tuple[str, float]] = []

    def flush(current: str) -> None:
        cleaned = current.rstrip()
        lines.append((cleaned, font.getlength(cleaned)))

    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append(("", 0.0))
            continue
        current = ""
        for token in _tokens(paragraph):
            if token.isspace():
                if current and not current.endswith(" "):
                    current += " "
                continue
            chunks: list[str] = []
            remaining = token
            while remaining and font.getlength(remaining) > max_width:
                cut = 1
                while cut < len(remaining) and font.getlength(remaining[: cut + 1]) <= max_width:
                    cut += 1
                chunks.append(remaining[:cut])
                remaining = remaining[cut:]
            if remaining:
                chunks.append(remaining)
            for chunk in chunks:
                candidate = current + chunk
                if current and font.getlength(candidate) > max_width:
                    flush(current)
                    current = chunk.lstrip()
                else:
                    current = candidate
        if current:
            flush(current)
        elif not lines or lines[-1][0] != "":
            lines.append(("", 0.0))
    return lines


def _aligned_left(align: str, width: int, line_width: float) -> float:
    if align == "center":
        return max(0.0, (width - line_width) / 2)
    if align == "right":
        return max(0.0, width - line_width)
    return 0.0


def _draw_text_box(
    canvas: Image.Image,
    style: dict[str, Any],
    text: str,
    x: float,
    y: float,
    context: dict[str, Any],
    warnings: list[str],
    label: str,
) -> None:
    width = max(1, round(float(style["width"])))
    height = max(1, round(float(style["height"])))
    left = round(float(x))
    top = round(float(y))
    size = max(1, round(float(style.get("fontSize", 48))))
    weight = int(style.get("fontWeight", 400))
    line_height = max(0.1, float(style.get("lineHeight", 1.2))) * size
    font = _font(size, weight)
    formatted = _format_text(str(text), context)
    color = parse_color(style.get("color", "#17324d"))
    align = style.get("align", "left")

    lines = _wrap_text(formatted, font, width)
    max_lines = max(0, int(height // line_height))
    overflow = len(lines) > max_lines
    if overflow:
        lines = lines[:max_lines]
        warnings.append(f"text {label} clipped to its height")
    layer_image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow = style.get("shadow")
    if shadow:
        shadow_color = parse_color(shadow.get("color", "rgba(0,0,0,0.35)"), (0, 0, 0, 90))
        shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        offset_x = round(float(shadow.get("offsetX", 0)))
        offset_y = round(float(shadow.get("offsetY", 0)))
        for index, (line, line_width) in enumerate(lines):
            if not line:
                continue
            line_left = _aligned_left(align, width, line_width)
            shadow_draw.text(
                (line_left + offset_x, index * line_height + offset_y),
                line,
                font=font,
                fill=shadow_color,
            )
        blur = float(shadow.get("blur", 0) or 0)
        if blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
        layer_image = Image.alpha_composite(layer_image, shadow_layer)

    draw = ImageDraw.Draw(layer_image)
    for index, (line, line_width) in enumerate(lines):
        if not line:
            continue
        line_left = _aligned_left(align, width, line_width)
        draw.text((line_left, index * line_height), line, font=font, fill=color)
    canvas.alpha_composite(layer_image, (left, top))


def _draw_flame(
    canvas: Image.Image,
    style: dict[str, Any],
    position: dict[str, Any],
    *,
    template_dir: Path,
    warnings: list[str],
    grayscale: bool = False,
) -> None:
    path = template_dir / "flame.png"
    if not path.is_file():
        warnings.append("flame asset is missing: flame.png")
        return
    try:
        source = _open_rgba(path)
    except RenderError as exc:
        warnings.append(f"flame skipped: {exc}")
        return
    visible = source.getchannel("A").getbbox()
    if visible:
        source = source.crop(visible)
    box_w = max(1, round(float(style["width"])))
    box_h = max(1, round(float(style["height"])))
    ratio = min(box_w / source.width, box_h / source.height) * FLAME_VISIBLE_SCALE
    width = max(1, round(source.width * ratio))
    height = max(1, round(source.height * ratio))
    source = source.resize((width, height), Image.Resampling.LANCZOS)
    if grayscale:
        source = _grayscale(source)
    opacity = max(0.0, min(1.0, float(style.get("opacity", 1))))
    if opacity < 1:
        alpha = source.getchannel("A").point(lambda value: round(value * opacity))
        source.putalpha(alpha)
    x = round(float(position["x"])) + (box_w - width) // 2
    y = round(float(position["y"])) + (box_h - height) // 2
    canvas.alpha_composite(source, (x, y))


def _pick_text(background: dict[str, Any], text_id: str | None) -> dict[str, Any]:
    texts = background.get("layout", {}).get("texts") or []
    if not texts:
        raise RenderError("background has no text variants")
    if text_id is not None:
        for entry in texts:
            if entry.get("id") == text_id:
                return entry
        raise RenderError(f"unknown text variant: {text_id}")
    return random.choice(texts)


def _rounded_alpha(image: Image.Image, radius: int) -> None:
    if radius <= 0:
        return
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1), radius=radius, fill=255
    )
    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))


def render_template(
    template: dict[str, Any],
    background: dict[str, Any],
    context: dict[str, Any],
    *,
    template_dir: Path,
    web_root: Path,
    text_id: str | None = None,
) -> tuple[bytes, list[str], str]:
    canvas_spec = template.get("canvas", {})
    width = int(canvas_spec.get("width", 1536))
    height = int(canvas_spec.get("height", 914))
    radius = int(canvas_spec.get("radius", 128))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    warnings: list[str] = []

    background_path = resolve_src(
        background["src"], template_dir=template_dir, web_root=web_root
    )
    if not background_path.is_file():
        raise RenderError(f"background asset is missing: {background['src']}")
    _paste_background(canvas, _open_rgba(background_path), background)

    styles = template.get("styles") or {}
    layout = background.get("layout") or {}
    completed_today = context.get("completed_today") is not False
    streak_style = styles["streak"]
    if not completed_today:
        streak_style = dict(streak_style)
        streak_style["color"] = INCOMPLETE_STREAK_COLOR
        shadow = dict(streak_style.get("shadow") or {})
        shadow["color"] = INCOMPLETE_STREAK_SHADOW
        streak_style["shadow"] = shadow
    chosen = _pick_text(background, text_id)
    _draw_text_box(
        canvas,
        styles["label"],
        chosen.get("text", ""),
        chosen["x"],
        chosen["y"],
        context,
        warnings,
        f"text {chosen['id']}",
    )
    _draw_text_box(
        canvas,
        streak_style,
        "{streak}",
        layout["streak"]["x"],
        layout["streak"]["y"],
        context,
        warnings,
        "streak",
    )
    _draw_flame(
        canvas,
        styles["flame"],
        layout["flame"],
        template_dir=template_dir,
        warnings=warnings,
        grayscale=not completed_today,
    )

    _rounded_alpha(canvas, radius)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue(), warnings, str(chosen["id"])


__all__ = [
    "FONT_BOLD",
    "FONT_REGULAR",
    "RenderError",
    "parse_color",
    "render_template",
]
