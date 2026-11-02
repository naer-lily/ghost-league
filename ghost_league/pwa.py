"""TLS-served PWA shell mounted on top of the existing API.

API routes are registered first; the static root is mounted last so a request
such as ``/v1/me/status`` or ``/avatars/current-user`` always reaches the API.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import create_app

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"

# Production deployment points this at the next build; local tests keep using
# the legacy ``web/`` root unless the environment explicitly overrides it.
_configured_root = os.environ.get("GHOST_LEAGUE_WEB_ROOT", "").strip()
ACTIVE_WEB_ROOT = Path(_configured_root).expanduser() if _configured_root else WEB_ROOT

STATIC_PREFIXES = frozenset({"v1", "avatars", "assets", "icons"})


def mount_web(app: FastAPI, web_root: str | Path = WEB_ROOT) -> FastAPI:
    root = Path(web_root).resolve()
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

    # Widget Studio remains at its documented URL while the main app advances.
    # Its static files live in the legacy ``web/`` tree, so keep serving them
    # from there instead of rewriting the editor into the React build.
    widget_root = (WEB_ROOT / "widget-studio").resolve()
    if widget_root.is_dir():
        app.mount(
            "/widget-studio",
            StaticFiles(directory=widget_root, html=True),
            name="widget-studio",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """Serve real files and fall back to ``index.html`` for SPA deep links.

        API/static prefixes keep their normal 404s so a missing asset never
        turns into the HTML shell. Real files are served before the mounted
        static handler because this catch-all is registered first.
        """

        candidate = (root / full_path).resolve() if full_path else index
        if candidate != root and root not in candidate.parents:
            raise HTTPException(status_code=404, detail="Not Found")
        if candidate.is_file():
            return FileResponse(candidate)
        if candidate.is_dir():
            directory_index = candidate / "index.html"
            if directory_index.is_file():
                return FileResponse(directory_index, media_type="text/html")

        prefix = full_path.split("/", 1)[0]
        if prefix in STATIC_PREFIXES or Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, media_type="text/html")

    # Registered last: API routes win, then the SPA fallback and static files.
    app.mount("/", StaticFiles(directory=root, html=True), name="pwa-web")
    return app


app = mount_web(create_app(start_scheduler=False), ACTIVE_WEB_ROOT)


__all__ = ["ACTIVE_WEB_ROOT", "app", "mount_web", "WEB_ROOT"]
