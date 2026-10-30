"""Filesystem-backed Widget Studio templates.

``data/widgets/<id>/`` is the single source of truth.  Every write is an atomic
JSON/PNG replace, every production render re-reads the directory, and Ghost's
tier/frame assets are referenced in place through ``ghost:assets/...``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from .schema import (
    CANVAS_HEIGHT,
    CANVAS_RADIUS,
    CANVAS_WIDTH,
    MAX_FILE_BYTES,
    TEMPLATE_VERSION,
    ValidationError,
    normalize_template,
    resolve_src,
    slugify,
    validate_asset_id,
    validate_template_id,
)

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WIDGETS_DIR = PROJECT_ROOT / "data" / "widgets"
DEFAULT_WEB_ROOT = PROJECT_ROOT / "web"
MAX_IMAGE_PIXELS = 40_000_000

TIER_LABELS = {
    "bronze": "青铜",
    "silver": "白银",
    "gold": "黄金",
    "sapphire": "蓝宝石",
    "ruby": "红宝石",
    "emerald": "翡翠",
    "amethyst": "紫水晶",
    "pearl": "珍珠",
    "obsidian": "黑曜石",
    "diamond": "钻石",
}
FRAME_LABELS = {
    "frame_ember": "余烬边框",
    "frame_clown": "小丑边框",
}
DEFAULT_STYLES: dict[str, Any] = {
    "label": {
        "width": 520,
        "height": 100,
        "fontSize": 64,
        "fontWeight": 400,
        "color": "#17324d",
        "align": "left",
        "lineHeight": 1.15,
        "shadow": {
            "color": "rgba(255,255,255,0.65)",
            "blur": 0,
            "offsetX": 0,
            "offsetY": 2,
        },
    },
    "streak": {
        "width": 360,
        "height": 180,
        "fontSize": 132,
        "fontWeight": 400,
        "color": "#ffb020",
        "align": "left",
        "lineHeight": 1,
        "shadow": {
            "color": "rgba(255,255,255,0.75)",
            "blur": 0,
            "offsetX": 0,
            "offsetY": 3,
        },
    },
    "flame": {"width": 120, "height": 140, "opacity": 1},
}
DEFAULT_LAYOUT: dict[str, Any] = {
    "texts": [{"id": "text-1", "text": "连续学习", "x": 760, "y": 540}],
    "streak": {"x": 760, "y": 300},
    "flame": {"x": 660, "y": 280},
}


def _default_styles() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_STYLES))


def _default_layout() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_LAYOUT))


class StoreError(Exception):
    """Base class for store errors that map to HTTP 4xx responses."""


class NotFoundError(StoreError):
    pass


class ConflictError(StoreError):
    pass


class AssetError(StoreError):
    pass


class UploadTooLargeError(StoreError):
    pass


def _now_iso(now_fn: Callable[[], datetime]) -> str:
    return now_fn().isoformat(timespec="seconds")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_bytes(path, body.encode("utf-8"))


def _default_background_png(width: int, height: int) -> bytes:
    """Generate a friendly local fallback so a new template renders immediately."""

    image = Image.new("RGBA", (width, height), (255, 248, 235, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    top = (255, 246, 228)
    bottom = (255, 206, 140)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=(*color, 255))
    draw.ellipse(
        (width * 0.58, -height * 0.28, width * 1.08, height * 0.72),
        fill=(255, 255, 255, 62),
    )
    draw.ellipse(
        (width * 0.04, height * 0.6, width * 0.54, height * 1.35),
        fill=(255, 167, 66, 42),
    )
    draw.rounded_rectangle(
        (width * 0.045, height * 0.08, width * 0.3, height * 0.92),
        radius=width // 24,
        fill=(255, 255, 255, 30),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _normalize_upload(data: bytes) -> Image.Image:
    if not data:
        raise AssetError("uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise UploadTooLargeError("file exceeds the 15MB limit")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AssetError("uploaded file is not a readable image") from exc
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise AssetError("image dimensions are too large")
    image = ImageOps.exif_transpose(image)
    return image.convert("RGBA")


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class WidgetStore:
    def __init__(
        self,
        root: str | Path = DEFAULT_WIDGETS_DIR,
        *,
        web_root: str | Path = DEFAULT_WEB_ROOT,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self.web_root = Path(web_root)
        self._now_fn = now_fn or datetime.now
        self._lock = threading.RLock()

    def now(self) -> datetime:
        return self._now_fn()

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------
    def template_dir(self, template_id: str) -> Path:
        validate_template_id(template_id)
        return self.root / template_id

    def _template_path(self, template_id: str) -> Path:
        return self.template_dir(template_id) / "template.json"

    def _asset_path(self, template_id: str, relative: str) -> Path:
        template_dir = self.template_dir(template_id)
        return resolve_src(
            relative, template_dir=template_dir, web_root=self.web_root
        )

    # -- read ----------------------------------------------------------
    def _read_template(self, template_id: str) -> dict[str, Any]:
        path = self._template_path(template_id)
        if not path.is_file():
            raise NotFoundError(f"template {template_id!r} not found")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssetError(f"template {template_id!r} has invalid JSON") from exc
        normalized = normalize_template(
            raw,
            template_dir=path.parent,
            web_root=self.web_root,
            expected_id=template_id,
        )
        if "render_token" not in normalized:
            raise AssetError(f"template {template_id!r} is missing render_token")
        return normalized

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._lock:
            return self._read_template(template_id)

    def list_templates(self) -> list[dict[str, Any]]:
        self.initialize()
        summaries: list[dict[str, Any]] = []
        for child in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not child.is_dir() or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", child.name):
                continue
            try:
                template = self._read_template(child.name)
            except (StoreError, ValidationError) as exc:
                LOGGER.warning("skipping widget template %s: %s", child.name, exc)
                continue
            summaries.append(
                {
                    "id": template["id"],
                    "name": template["name"],
                    "updated_at": template.get("updated_at"),
                    "background_count": len(template["backgrounds"]),
                    "text_count": sum(
                        len(background["layout"]["texts"])
                        for background in template["backgrounds"]
                    ),
                }
            )
        summaries.sort(key=lambda item: (item["name"].lower(), item["id"]))
        return summaries

    # -- write ---------------------------------------------------------
    def _write_template(self, template: dict[str, Any]) -> None:
        template_dir = self.template_dir(template["id"])
        template_dir.mkdir(parents=True, exist_ok=True)
        normalized = normalize_template(
            template,
            template_dir=template_dir,
            web_root=self.web_root,
            expected_id=template["id"],
        )
        self._assert_assets_exist(normalized, template_dir)
        _atomic_write_json(template_dir / "template.json", normalized)

    def _assert_assets_exist(
        self, template: dict[str, Any], template_dir: Path
    ) -> None:
        for background in template["backgrounds"]:
            resolved = resolve_src(
                background["src"], template_dir=template_dir, web_root=self.web_root
            )
            if not resolved.is_file():
                raise ValidationError(f"asset is missing: {background['src']}")

    def _unique_template_id(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        suffix = 1
        while (self.root / candidate).exists():
            suffix += 1
            candidate = f"{base}-{suffix}"
            if len(candidate) > 64:
                candidate = f"{base[:60]}-{suffix}"
        return candidate

    def create_template(self, name: str) -> dict[str, Any]:
        if not isinstance(name, str):
            raise ValidationError("name must be a string")
        cleaned = name.strip()
        if not 1 <= len(cleaned) <= 80:
            raise ValidationError("name must be 1-80 characters")
        self.initialize()
        with self._lock:
            template_id = self._unique_template_id(cleaned)
            template_dir = self.template_dir(template_id)
            (template_dir / "backgrounds").mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(
                template_dir / "backgrounds" / "bg-default.png",
                _default_background_png(CANVAS_WIDTH, CANVAS_HEIGHT),
            )
            template = {
                "version": TEMPLATE_VERSION,
                "id": template_id,
                "name": cleaned,
                "updated_at": _now_iso(self._now_fn),
                "render_token": secrets.token_hex(16),
                "canvas": {
                    "width": CANVAS_WIDTH,
                    "height": CANVAS_HEIGHT,
                    "radius": CANVAS_RADIUS,
                },
                "styles": _default_styles(),
                "backgrounds": [
                    {
                        "id": "bg-default",
                        "name": "默认",
                        "src": "backgrounds/bg-default.png",
                        "when": {},
                        "priority": 0,
                        "fit": "cover",
                        "offsetX": 0,
                        "offsetY": 0,
                        "scale": 1,
                        "layout": _default_layout(),
                    }
                ],
            }
            self._write_template(template)
            return self._read_template(template_id)

    def update_template(self, template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        validate_template_id(template_id)
        if not isinstance(payload, dict):
            raise ValidationError("template must be a JSON object")
        with self._lock:
            existing = self._read_template(template_id)
            updated = dict(payload)
            updated["id"] = template_id
            # Render tokens are minted once per template and never changed by PUT.
            updated["render_token"] = existing["render_token"]
            updated["updated_at"] = _now_iso(self._now_fn)
            self._write_template(updated)
            return self._read_template(template_id)

    def delete_template(self, template_id: str) -> None:
        validate_template_id(template_id)
        with self._lock:
            template_dir = self.template_dir(template_id)
            if not template_dir.is_dir():
                raise NotFoundError(f"template {template_id!r} not found")
            shutil.rmtree(template_dir)

    # -- assets --------------------------------------------------------
    def upload_asset(
        self,
        template_id: str,
        kind: str,
        data: bytes,
        *,
        bg_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"background", "flame"}:
            raise AssetError("kind must be background or flame")
        image = _normalize_upload(data)
        with self._lock:
            # Uploads only write the file.  They never mutate template.json;
            # the editor adds the asset to its in-memory template and persists
            # it later through an explicit save.
            self._read_template(template_id)
            template_dir = self.template_dir(template_id)
            if kind == "background":
                if not bg_id:
                    raise AssetError("bg_id is required for background uploads")
                bg_id = validate_asset_id(bg_id)
                relative = f"backgrounds/{bg_id}.png"
                target = template_dir / "backgrounds" / f"{bg_id}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_bytes(target, _png_bytes(image))
                return {"src": relative}
            relative = "flame.png"
            _atomic_write_bytes(template_dir / "flame.png", _png_bytes(image))
            return {"src": relative}

    def asset_path(self, template_id: str, filename: str) -> Path:
        validate_template_id(template_id)
        if not isinstance(filename, str) or not filename or len(filename) > 300:
            raise NotFoundError("asset not found")
        if "\\" in filename or filename.startswith("/"):
            raise NotFoundError("asset not found")
        parts = Path(filename).parts
        if ".." in parts or "." in parts:
            raise NotFoundError("asset not found")
        template_dir = self.template_dir(template_id)
        candidate = (template_dir / Path(*parts)).resolve()
        if not candidate.is_relative_to(template_dir.resolve()):
            raise NotFoundError("asset not found")
        if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise NotFoundError("asset not found")
        if not candidate.is_file():
            raise NotFoundError("asset not found")
        return candidate

    def thumbnail(self, template_id: str, bg_id: str, width: int = 240) -> bytes:
        validate_asset_id(bg_id)
        if not isinstance(width, int) or isinstance(width, bool) or not 16 <= width <= 1024:
            raise AssetError("thumbnail width must be 16-1024")
        with self._lock:
            template = self._read_template(template_id)
            background = next(
                (item for item in template["backgrounds"] if item["id"] == bg_id),
                None,
            )
            if background is None:
                raise NotFoundError(f"background {bg_id!r} not found")
            path = self._asset_path(template_id, background["src"])
            if not path.is_file():
                raise NotFoundError("background asset not found")
            try:
                with Image.open(path) as source:
                    source.load()
                    image = source.convert("RGBA")
            except (UnidentifiedImageError, OSError) as exc:
                raise AssetError("background asset is not a readable image") from exc
            height = max(1, round(image.height * width / max(1, image.width)))
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            return _png_bytes(image)

    # -- Ghost library -------------------------------------------------
    def library(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        groups = (
            ("tiers/card", "段位卡"),
            ("frames", "头像框"),
        )
        for relative_dir, group_label in groups:
            directory = self.web_root / "assets" / relative_dir
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.png"), key=lambda item: item.name):
                stem = path.stem
                if relative_dir == "tiers/card":
                    label = f"{TIER_LABELS.get(stem, stem)} · 段位卡"
                    item_id = f"tiers/card/{stem}"
                else:
                    label = f"{FRAME_LABELS.get(stem, stem)} · 头像框"
                    item_id = f"frames/{stem}"
                items.append(
                    {
                        "id": item_id,
                        "label": label,
                        "url": f"/assets/{relative_dir}/{path.name}",
                        "src": f"ghost:assets/{relative_dir}/{path.name}",
                        "group": group_label,
                    }
                )
        return items

    # -- production rendering -----------------------------------------
    def render(
        self,
        template_id: str,
        token: str,
        context: dict[str, Any],
        *,
        size: str | None = None,
        bg_id: str | None = None,
        text_id: str | None = None,
    ) -> tuple[bytes, str, str]:
        # Imported lazily so validation/store tests do not need the renderer.
        from .renderer import render_template

        validate_template_id(template_id)
        with self._lock:
            template = self._read_template(template_id)
            expected = template.get("render_token", "")
            if not isinstance(token, str) or not secrets.compare_digest(token, expected):
                raise NotFoundError("widget not found")
            if bg_id:
                validate_asset_id(bg_id)
                selected = next(
                    (item for item in template["backgrounds"] if item["id"] == bg_id),
                    None,
                )
                if selected is None:
                    raise NotFoundError("background not found")
            else:
                from .schema import select_background

                selected, _ = select_background(template, context)
            if text_id is not None and not any(
                entry.get("id") == text_id
                for entry in selected["layout"]["texts"]
            ):
                raise NotFoundError("text variant not found")
            data, warnings, used_text = render_template(
                template,
                selected,
                context,
                template_dir=self.template_dir(template_id),
                web_root=self.web_root,
                text_id=text_id,
            )
            if size == "1x":
                from PIL import Image as PILImage

                with PILImage.open(io.BytesIO(data)) as image:
                    resized = image.convert("RGBA").resize(
                        (368, 219), PILImage.Resampling.LANCZOS
                    )
                    buffer = io.BytesIO()
                    resized.save(buffer, format="PNG")
                    data = buffer.getvalue()
            for warning in warnings:
                LOGGER.warning("widget %s: %s", template_id, warning)
            return data, selected["id"], used_text


__all__ = [
    "AssetError",
    "ConflictError",
    "DEFAULT_WEB_ROOT",
    "DEFAULT_WIDGETS_DIR",
    "NotFoundError",
    "PROJECT_ROOT",
    "StoreError",
    "UploadTooLargeError",
    "WidgetStore",
]
