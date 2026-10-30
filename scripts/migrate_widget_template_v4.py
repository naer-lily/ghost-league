#!/usr/bin/env python3
"""Idempotent migration from Widget Studio schema v3 to v4.

Version 4 removes the global ``styles`` block.  Every background owns a full
``styles`` copy (``label`` plus the joined ``counter`` component), and
``layout`` keeps only the counter anchor and the text variants.  The counter
gains ``scale``/``gap``; label text gains ``letterSpacing``, ``strokeWidth`` and
``strokeColor``.

The service only accepts version 4.  This script is a migration tool, not a
runtime compatibility layer: running it on an already-v4 file leaves the
document unchanged.

Usage::

    python3 scripts/migrate_widget_template_v4.py data/widgets/*/template.json
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

VERSION = 4
DEFAULT_GAP = 30
DEFAULT_SCALE = 1.0


def _label_style(raw: dict[str, Any]) -> dict[str, Any]:
    label = copy.deepcopy(raw)
    color = label.get("color", "#17324d")
    label.setdefault("letterSpacing", 0)
    label.setdefault("strokeWidth", 0)
    label.setdefault("strokeColor", color)
    return label


def _counter_style(raw: dict[str, Any]) -> dict[str, Any]:
    flame = copy.deepcopy(raw.get("flame") or {"width": 120, "height": 140, "opacity": 1})
    number = copy.deepcopy(
        raw.get("streak")
        or {
            "width": 360,
            "height": 180,
            "fontSize": 132,
            "fontWeight": 400,
            "color": "#ffb020",
            "align": "left",
            "lineHeight": 1,
            "shadow": None,
        }
    )
    return {
        "scale": DEFAULT_SCALE,
        "gap": DEFAULT_GAP,
        "flame": flame,
        "number": number,
    }


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("template must be a JSON object")
    version = raw.get("version")
    if version == VERSION:
        return copy.deepcopy(raw)
    if version != 3:
        raise ValueError(
            f"only version 3 templates can be migrated to v{VERSION} "
            f"(got version {version!r}); run migrate_widget_template_v3.py first"
        )

    styles = raw.get("styles")
    if not isinstance(styles, dict):
        raise ValueError("version 3 template has no styles object")
    backgrounds = raw.get("backgrounds")
    if not isinstance(backgrounds, list):
        raise ValueError("version 3 template has no backgrounds list")

    migrated: dict[str, Any] = {
        "version": VERSION,
        "id": raw["id"],
        "name": raw["name"],
        "canvas": copy.deepcopy(
            raw.get("canvas", {"width": 1536, "height": 914, "radius": 128})
        ),
        "backgrounds": [],
    }
    if raw.get("updated_at") is not None:
        migrated["updated_at"] = raw["updated_at"]

    for index, background in enumerate(backgrounds):
        old_layout = background.get("layout")
        if not isinstance(old_layout, dict):
            raise ValueError(f"backgrounds[{index}] has no layout object")
        old_flame = old_layout.get("flame") or {}
        texts = copy.deepcopy(old_layout.get("texts") or [])
        if not texts:
            raise ValueError(f"backgrounds[{index}] has no text variants")
        item: dict[str, Any] = {
            key: copy.deepcopy(background[key])
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
        item["styles"] = {
            "label": _label_style(styles["label"]),
            "counter": _counter_style(styles),
        }
        item["layout"] = {
            "counter": {
                "x": old_flame.get("x", 660),
                "y": old_flame.get("y", 280),
            },
            "texts": texts,
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
        if raw.get("version") == VERSION:
            print(f"already version {VERSION}: {path}")
            continue
        migrated = migrate(raw)
        path.write_text(
            json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"migrated {path} -> version {VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
