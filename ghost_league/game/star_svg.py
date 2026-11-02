"""Deterministic, self-contained SVG for one collected star.

The renderer only reads the persisted star fields: ``star_type``, ``rarity``,
``palette``, ``visual_seed``, ``companion_count``, and ``catalog_code``.  It
never reads the player's name, never fetches an external resource, and never
includes a script, font, or remote URL.  The same record always serializes to
exactly the same bytes.
"""

from __future__ import annotations

import hashlib
import html
import math
from typing import Any

from .stars import (
    TYPE_PALETTES,
    RARITY_BY_TYPE,
    catalog_code_is_valid,
    companion_count_for,
    parse_palette_json,
)

_CANVAS = 512
_CENTER = 256.0
_MASK_63 = (1 << 63) - 1


def _seed(star: dict[str, Any]) -> int:
    try:
        value = int(star.get("visual_seed") or 0)
    except (TypeError, ValueError):
        value = 0
    value &= _MASK_63
    return value or 1


def _pick(seed: int, label: str, low: int, high: int) -> int:
    """Stable integer in ``[low, high]`` derived from the visual seed."""

    if high <= low:
        return low
    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).digest()
    return low + int.from_bytes(digest[:8], "big") % (high - low + 1)


def _f(value: float) -> str:
    return f"{value:.2f}"


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    dx = x - _CENTER
    dy = y - _CENTER
    return (
        _CENTER + dx * cos_angle - dy * sin_angle,
        _CENTER + dx * sin_angle + dy * cos_angle,
    )


def _defs(seed: int, palette: list[str], glow_radius: int) -> str:
    return (
        "<defs>"
        f'<radialGradient id="glow-{seed}" cx="50%" cy="50%" r="50%">'
        f'<stop offset="0%" stop-color="{palette[0]}" stop-opacity="0.88"/>'
        f'<stop offset="55%" stop-color="{palette[0]}" stop-opacity="0.22"/>'
        f'<stop offset="100%" stop-color="{palette[2]}" stop-opacity="0"/>'
        "</radialGradient>"
        f'<radialGradient id="core-{seed}" cx="42%" cy="38%" r="65%">'
        f'<stop offset="0%" stop-color="{palette[1]}"/>'
        f'<stop offset="52%" stop-color="{palette[0]}"/>'
        f'<stop offset="100%" stop-color="{palette[2]}"/>'
        "</radialGradient>"
        f'<linearGradient id="beam-{seed}" x1="0%" y1="0%" x2="100%" y2="0%">'
        f'<stop offset="0%" stop-color="{palette[1]}" stop-opacity="0"/>'
        f'<stop offset="50%" stop-color="{palette[1]}" stop-opacity="0.9"/>'
        f'<stop offset="100%" stop-color="{palette[0]}" stop-opacity="0"/>'
        "</linearGradient>"
        f'<clipPath id="clip-{seed}">'
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" r="{glow_radius}"/>'
        "</clipPath>"
        "</defs>"
    )


def _dust(seed: int, palette: list[str], amount: int, spread: int) -> list[str]:
    parts: list[str] = []
    count = _pick(seed, "dust-count", 6, amount)
    for index in range(count):
        radius = _pick(seed, f"dust-radius-{index}", 70, spread)
        angle = _pick(seed, f"dust-angle-{index}", 0, 359)
        size = _pick(seed, f"dust-size-{index}", 1, 4) / 1.4
        color = palette[1] if index % 3 else palette[0]
        opacity = _pick(seed, f"dust-opacity-{index}", 20, 75) / 100
        radians = math.radians(angle)
        x = _CENTER + radius * math.cos(radians)
        y = _CENTER + radius * math.sin(radians) * 0.92
        parts.append(
            f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(size)}" '
            f'fill="{color}" fill-opacity="{opacity:.2f}"/>'
        )
    return parts


def _single_star(seed: int, palette: list[str], glow_radius: int) -> list[str]:
    core_radius = _pick(seed, "core-radius", 44, 68)
    ray_count = (4, 6, 8)[_pick(seed, "ray-count", 0, 2)]
    rotation = _pick(seed, "ray-rotation", 0, 89)
    parts = [
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{glow_radius}" fill="url(#glow-{seed})"/>'
    ]
    for index in range(ray_count):
        angle = rotation + (360 / ray_count) * index
        radians = math.radians(angle)
        inner = core_radius + _pick(seed, f"ray-inner-{index}", 18, 34)
        outer = inner + _pick(seed, f"ray-length-{index}", 55, 130)
        width = _pick(seed, f"ray-width-{index}", 2, 5)
        opacity = _pick(seed, f"ray-opacity-{index}", 45, 90) / 100
        x1 = _CENTER + inner * math.cos(radians)
        y1 = _CENTER + inner * math.sin(radians)
        x2 = _CENTER + outer * math.cos(radians)
        y2 = _CENTER + outer * math.sin(radians)
        parts.append(
            f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" '
            f'y2="{_f(y2)}" stroke="{palette[1]}" stroke-width="{width}" '
            f'stroke-opacity="{opacity:.2f}" stroke-linecap="round"/>'
        )
    parts.append(
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{core_radius}" fill="url(#core-{seed})"/>'
    )
    parts.append(
        f'<circle cx="{_f(_CENTER - core_radius * 0.18)}" '
        f'cy="{_f(_CENTER - core_radius * 0.2)}" '
        f'r="{_f(core_radius * 0.32)}" fill="{palette[1]}" '
        f'fill-opacity="0.42"/>'
    )
    parts.extend(_dust(seed, palette, amount=16, spread=225))
    return parts


def _companion_star(
    seed: int,
    palette: list[str],
    glow_radius: int,
    companion_count: int,
) -> list[str]:
    core_radius = _pick(seed, "main-radius", 42, 58)
    orbit_tilt = _pick(seed, "orbit-tilt", -35, 35)
    orbit_flat = _pick(seed, "orbit-flat", 45, 68) / 100
    parts = [
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{glow_radius}" fill="url(#glow-{seed})"/>'
    ]
    companion_centers: list[tuple[float, float, int]] = []
    for index in range(companion_count):
        orbit_radius = _pick(seed, f"orbit-radius-{index}", 135, 185)
        start_angle = -55 + _pick(seed, "orbit-start", 0, 40)
        end_angle = 205 + _pick(seed, "orbit-end", 0, 35)
        start_radians = math.radians(start_angle)
        end_radians = math.radians(end_angle)
        x1 = _CENTER + orbit_radius * math.cos(start_radians)
        y1 = _CENTER + orbit_radius * orbit_flat * math.sin(start_radians)
        x2 = _CENTER + orbit_radius * math.cos(end_radians)
        y2 = _CENTER + orbit_radius * orbit_flat * math.sin(end_radians)
        parts.append(
            f'<path d="M {_f(x1)} {_f(y1)} A {_f(orbit_radius)} '
            f'{_f(orbit_radius * orbit_flat)} 0 1 1 {_f(x2)} {_f(y2)}" '
            f'transform="rotate({orbit_tilt} {_f(_CENTER)} {_f(_CENTER)})" '
            f'fill="none" stroke="{palette[2]}" stroke-width="2" '
            f'stroke-opacity="0.55" stroke-dasharray="7 11"/>'
        )
        angle = start_angle + (end_angle - start_angle) * (
            0.25 + 0.5 * _pick(seed, f"orbit-position-{index}", 0, 100) / 100
        )
        radians = math.radians(angle)
        raw_x = _CENTER + orbit_radius * math.cos(radians)
        raw_y = _CENTER + orbit_radius * orbit_flat * math.sin(radians)
        x, y = _rotate(raw_x, raw_y, orbit_tilt)
        companion_radius = _pick(seed, f"companion-size-{index}", 17, 28)
        companion_centers.append((x, y, companion_radius))
    parts.append(
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{core_radius}" fill="url(#core-{seed})"/>'
    )
    for index, (x, y, radius) in enumerate(companion_centers):
        parts.append(
            f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{radius + 12}" '
            f'fill="url(#glow-{seed})" fill-opacity="0.8"/>'
        )
        parts.append(
            f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{radius}" '
            f'fill="url(#core-{seed})"/>'
        )
        parts.append(
            f'<circle cx="{_f(x - radius * 0.2)}" '
            f'cy="{_f(y - radius * 0.22)}" r="{_f(radius * 0.3)}" '
            f'fill="{palette[1]}" fill-opacity="0.4"/>'
        )
    parts.extend(_dust(seed, palette, amount=12, spread=235))
    return parts


def _beam_star(seed: int, palette: list[str], glow_radius: int) -> list[str]:
    core_radius = _pick(seed, "beam-core-radius", 13, 24)
    tilt = _pick(seed, "beam-tilt", -40, 40)
    length = _pick(seed, "beam-length", 190, 245)
    width = _pick(seed, "beam-width", 9, 19)
    radians = math.radians(tilt)
    dx = math.cos(radians) * length
    dy = math.sin(radians) * length
    parts = [
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{glow_radius}" fill="url(#glow-{seed})"/>',
        f'<line x1="{_f(_CENTER - dx)}" y1="{_f(_CENTER - dy)}" '
        f'x2="{_f(_CENTER + dx)}" y2="{_f(_CENTER + dy)}" '
        f'stroke="{palette[1]}" stroke-width="{width}" '
        f'stroke-opacity="0.36" stroke-linecap="round"/>',
        f'<line x1="{_f(_CENTER - dx * 0.82)}" y1="{_f(_CENTER - dy * 0.82)}" '
        f'x2="{_f(_CENTER + dx * 0.82)}" y2="{_f(_CENTER + dy * 0.82)}" '
        f'stroke="{palette[0]}" stroke-width="{max(2, width // 2)}" '
        f'stroke-opacity="0.82" stroke-linecap="round"/>',
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{glow_radius * 0.42}" fill="url(#glow-{seed})"/>',
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{core_radius}" fill="url(#core-{seed})"/>',
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{max(2, core_radius // 3)}" fill="{palette[1]}"/>',
    ]
    # A pair of small arcs makes pulsars read differently from plain neutron
    # stars without changing the shared thin-core/dual-beam silhouette.
    arcs = _pick(seed, "beam-arcs", 0, 1)
    for index in range(arcs):
        radius = _pick(seed, f"arc-radius-{index}", 120, 175)
        start = _pick(seed, f"arc-start-{index}", 0, 180)
        parts.append(
            f'<path d="M {_f(_CENTER + radius)} {_f(_CENTER)} '
            f'A {radius} {radius} 0 0 1 {_f(_CENTER - radius)} '
            f'{_f(_CENTER)}" transform="rotate({start} '
            f'{_f(_CENTER)} {_f(_CENTER)})" fill="none" '
            f'stroke="{palette[0]}" stroke-width="2" '
            f'stroke-opacity="0.3" stroke-dasharray="4 9"/>'
        )
    parts.extend(_dust(seed, palette, amount=10, spread=190))
    return parts


def _black_hole(seed: int, palette: list[str], glow_radius: int) -> list[str]:
    core_radius = _pick(seed, "relic-core", 54, 76)
    ring_radius = _pick(seed, "ring-radius", 145, 195)
    ring_flat = _pick(seed, "ring-flat", 28, 48) / 100
    tilt = _pick(seed, "ring-tilt", -32, 32)
    parts = [
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{glow_radius}" fill="url(#glow-{seed})" fill-opacity="0.75"/>',
        f'<ellipse cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'rx="{ring_radius}" ry="{_f(ring_radius * ring_flat)}" '
        f'transform="rotate({tilt} {_f(_CENTER)} {_f(_CENTER)})" '
        f'fill="none" stroke="{palette[0]}" stroke-width="14" '
        f'stroke-opacity="0.78"/>',
        f'<ellipse cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'rx="{_f(ring_radius * 0.82)}" '
        f'ry="{_f(ring_radius * ring_flat * 0.82)}" '
        f'transform="rotate({tilt} {_f(_CENTER)} {_f(_CENTER)})" '
        f'fill="none" stroke="{palette[1]}" stroke-width="4" '
        f'stroke-opacity="0.9"/>',
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{core_radius}" fill="{palette[2]}"/>',
        f'<circle cx="{_f(_CENTER)}" cy="{_f(_CENTER)}" '
        f'r="{core_radius}" fill="none" stroke="{palette[0]}" '
        f'stroke-width="2" stroke-opacity="0.7"/>',
    ]
    sparks = _pick(seed, "ring-sparks", 3, 8)
    for index in range(sparks):
        angle = math.radians(_pick(seed, f"spark-angle-{index}", 0, 359))
        radius = ring_radius * (0.92 + _pick(seed, f"spark-offset-{index}", 0, 12) / 100)
        x = _CENTER + radius * math.cos(angle)
        y = _CENTER + radius * ring_flat * math.sin(angle)
        x, y = _rotate(x, y, tilt)
        size = _pick(seed, f"spark-size-{index}", 1, 3) / 1.2
        parts.append(
            f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(size)}" '
            f'fill="{palette[1]}" fill-opacity="0.8"/>'
        )
    parts.extend(_dust(seed, palette, amount=9, spread=175))
    return parts


def render_star_svg(star: dict[str, Any]) -> str:
    """Render one star record to a complete standalone SVG document."""

    seed = _seed(star)
    raw_type = str(star.get("star_type") or "yellow_dwarf")
    star_type = raw_type if raw_type in TYPE_PALETTES else "yellow_dwarf"
    palette = parse_palette_json(
        star.get("palette") or star.get("palette_json"), star_type
    )
    raw_rarity = str(star.get("rarity") or RARITY_BY_TYPE[star_type])
    rarity = raw_rarity if raw_rarity in RARITY_BY_TYPE.values() else (
        RARITY_BY_TYPE[star_type]
    )
    expected_companions = companion_count_for(star_type)
    try:
        stored_companions = int(star.get("companion_count") or 0)
    except (TypeError, ValueError):
        stored_companions = expected_companions
    companion_count = expected_companions if expected_companions else max(
        0, min(2, stored_companions)
    )

    glow_radius = _pick(seed, "glow-radius", 118, 182)
    defs = _defs(seed, palette, glow_radius)
    if star_type == "black_hole_relic":
        body = _black_hole(seed, palette, glow_radius)
    elif star_type in {"neutron_star", "pulsar"}:
        body = _beam_star(seed, palette, glow_radius)
    elif companion_count:
        body = _companion_star(seed, palette, glow_radius, companion_count)
    else:
        body = _single_star(seed, palette, glow_radius)

    header = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_CANVAS} {_CANVAS}" width="{_CANVAS}" '
        f'height="{_CANVAS}" role="img" '
        f'data-visual-seed="{seed}" data-star-type="{star_type}" '
        f'data-rarity="{rarity}">'
    )
    catalog = star.get("catalog_code")
    title = ""
    if catalog_code_is_valid(catalog):
        title = f"<title>{html.escape(str(catalog))}</title>"
    return (
        header
        + title
        + defs
        + '<g clip-path="url(#clip-'
        + str(seed)
        + ')">'
        + "".join(body)
        + "</g></svg>"
    )
