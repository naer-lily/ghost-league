"""Widget Studio: on-disk templates, instant editor and public PNG widgets."""

from __future__ import annotations

from .renderer import RenderError, render_template
from .routes import build_router
from .schema import (
    CANVAS_HEIGHT,
    CANVAS_RADIUS,
    CANVAS_WIDTH,
    MAX_FILE_BYTES,
    ValidationError,
    select_background,
    slugify,
)
from .store import (
    DEFAULT_WEB_ROOT,
    DEFAULT_WIDGETS_DIR,
    AssetError,
    ConflictError,
    NotFoundError,
    UploadTooLargeError,
    WidgetStore,
)

__all__ = [
    "AssetError",
    "CANVAS_HEIGHT",
    "CANVAS_RADIUS",
    "CANVAS_WIDTH",
    "ConflictError",
    "DEFAULT_WEB_ROOT",
    "DEFAULT_WIDGETS_DIR",
    "MAX_FILE_BYTES",
    "NotFoundError",
    "RenderError",
    "UploadTooLargeError",
    "ValidationError",
    "WidgetStore",
    "build_router",
    "render_template",
    "select_background",
    "slugify",
]
