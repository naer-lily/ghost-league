#!/usr/bin/env python3
"""One-shot migration from Widget Studio schema v2 to v3.

Version 3 has no global ``layers``.  Global typography/colors live in
``styles`` and every background owns its own ``layout`` (text variants, streak
position, flame position).

The service itself only accepts version 3; this script is a migration tool, not
a compatibility layer.  It is safe to run on a copy of a template JSON file and
refuses anything that is not already a version 2 document.

Usage::

    python3 scripts/migrate_widget_template_v3.py data/widgets/nijika/template.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _layer_by_role(layers: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    for layer in layers:
        if layer.get("role") == role:
            return layer
    return None


def _text_style(layer: dict[str, Any]) -> dict[str, Any]:
    return {
        "width": layer.get("w", 520),
        "height": layer.get("h", 100),
        "fontSize": layer.get("fontSize", 48),
        "fontWeight": layer.get("fontWeight", 400),
        "color": layer.get("color", "#17324d"),
        "align": layer.get("align", "left"),
        "lineHeight": layer.get("lineHeight", 1.2),
        "shadow": layer.get("shadow"),
    }


def _flame_style(layer: dict[str, Any] | None) -> dict[str, Any]:
    if layer is None:
        return {"width": 120, "height": 140, "opacity": 1}
    return {
        "width": layer.get("w", 120),
        "height": layer.get("h", 140),
        "opacity": layer.get("opacity", 1),
    }


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("version") != 2:
        raise ValueError("only version 2 templates can be migrated")
    layers = raw.get("layers")
    if not isinstance(layers, list):
        raise ValueError("version 2 template has no layers list")
    label = _layer_by_role(layers, "label") or next(
        (layer for layer in layers if layer.get("type") == "text"), None
    )
    streak = _layer_by_role(layers, "streak") or next(
        (
            layer
            for layer in layers
            if layer.get("type") == "text" and layer is not label
        ),
        None,
    )
    flame = _layer_by_role(layers, "flame") or next(
        (layer for layer in layers if layer.get("type") == "image"), None
    )
    if label is None or streak is None:
        raise ValueError("version 2 template needs a label and a streak text layer")

    migrated = {
        "version": 3,
        "id": raw["id"],
        "name": raw["name"],
        "canvas": raw.get("canvas", {"width": 1536, "height": 914, "radius": 128}),
        "styles": {
            "label": _text_style(label),
            "streak": _text_style(streak),
            "flame": _flame_style(flame),
        },
        "backgrounds": [],
    }
    if raw.get("render_token") is not None:
        migrated["render_token"] = raw["render_token"]
    if raw.get("updated_at") is not None:
        migrated["updated_at"] = raw["updated_at"]

    for background in raw.get("backgrounds", []):
        item = {
            key: background[key]
            for key in (
                "id",
                "name",
                "src",
                "when",
                "priority",
                "fit",
                "offsetX",
                "offsetY",
                "scale",
            )
            if key in background
        }
        item["layout"] = {
            "texts": [
                {
                    "id": "text-1",
                    "text": label.get("text", ""),
                    "x": label.get("x", 760),
                    "y": label.get("y", 540),
                }
            ],
            "streak": {
                "x": streak.get("x", 760),
                "y": streak.get("y", 300),
            },
            "flame": {
                "x": flame.get("x", 660) if flame else 660,
                "y": flame.get("y", 280) if flame else 280,
            },
        }
        migrated["backgrounds"].append(item)
    return migrated


def main(argv: list[str]) -> int:
    paths = [Path(argument) for argument in argv[1:]]
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        migrated = migrate(raw)
        path.write_text(
            json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"migrated {path} -> version 3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
