"""TLS-served PWA shell mounted on top of the existing API.

API routes are registered first; the static root is mounted last so a request
such as ``/v1/me/status`` or ``/avatars/current-user`` always reaches the API.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import app as api_app

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def mount_web(app: FastAPI, web_root: str | Path = WEB_ROOT) -> FastAPI:
    root = Path(web_root)
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"PWA web root is missing index.html: {root}")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(
            root / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            root / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    # Registered last: API routes win, then static assets / index.html.
    app.mount("/", StaticFiles(directory=root, html=True), name="pwa-web")
    return app


app = mount_web(api_app)


__all__ = ["app", "mount_web", "WEB_ROOT"]
