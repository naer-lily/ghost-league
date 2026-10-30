"""HTTP routes for Widget Studio and public widget PNG rendering."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ..accounts import USER_ID_PATTERN as SAFE_USER_ID
from .renderer import RenderError
from .schema import (
    MAX_FILE_BYTES,
    ValidationError,
    normalize_template,
    validate_template_id,
)
from .store import (
    AssetError,
    ConflictError,
    NotFoundError,
    StoreError,
    UploadTooLargeError,
    WidgetStore,
)

LOGGER = logging.getLogger(__name__)
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
WIDGET_NOT_FOUND = "widget not found"


class TemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, UploadTooLargeError):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, AssetError):
        return HTTPException(status_code=415, detail=str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, StoreError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RenderError):
        return HTTPException(status_code=500, detail="widget render failed")
    return HTTPException(status_code=400, detail=str(exc))


def _completed_today(status: dict[str, Any]) -> bool:
    """Read today's completion from ``status["checkin"]``.

    Local accounts expose the check-in row's ``source`` string (or ``None``).
    Older/Channel payloads may expose a boolean or a small object; when the
    field is absent or has an unknown shape, fall back to today's XP target.
    """

    if "checkin" in status:
        checkin = status.get("checkin")
        if isinstance(checkin, bool):
            return checkin
        if isinstance(checkin, str):
            return bool(checkin.strip())
        if isinstance(checkin, dict):
            for key in ("completed", "completed_today", "checked_in", "created"):
                value = checkin.get(key)
                if isinstance(value, bool):
                    return value
            source = checkin.get("source")
            if isinstance(source, str) and source.strip():
                return True
        elif checkin is None:
            return False
    today_xp = status.get("today_xp")
    required_xp = status.get("required_xp")
    if isinstance(today_xp, int) and isinstance(required_xp, int):
        return today_xp >= required_xp
    return False


def _context_from_status(
    status: dict[str, Any], now: datetime
) -> dict[str, Any]:
    streak = status.get("streak") or {}
    return {
        "hour": now.hour,
        "weekday": now.isoweekday(),
        "streak": int(streak.get("current") or 0),
        "xp": int(status.get("xp") or 0),
        "rank": status.get("rank"),
        "name": str(status.get("display_name") or ""),
        "completed_today": _completed_today(status),
        "league": str(status.get("tier") or "").lower(),
        "event": None,
    }


def build_router(
    *,
    store: WidgetStore,
    auth: Callable[..., dict[str, Any]],
    now_fn: Callable[[], datetime],
    status_for_user: Callable[[str], dict[str, Any] | None],
) -> APIRouter:
    router = APIRouter()

    # -- template JSON ------------------------------------------------
    @router.get("/v1/widget-studio/templates")
    def list_templates(_: dict[str, Any] = Depends(auth)) -> list[dict[str, Any]]:
        return store.list_templates()

    @router.post("/v1/widget-studio/templates", status_code=status.HTTP_201_CREATED)
    def create_template(
        request: TemplateCreateRequest,
        _: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return store.create_template(request.name)
        except Exception as exc:  # noqa: BLE001 - mapped to a safe HTTP status
            raise _http_error(exc) from exc

    @router.get("/v1/widget-studio/templates/{template_id}")
    def get_template(
        template_id: str,
        _: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return store.get_template(template_id)
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc

    @router.put("/v1/widget-studio/templates/{template_id}")
    def update_template(
        template_id: str,
        payload: dict[str, Any],
        _: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return store.update_template(template_id, payload)
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc

    @router.delete("/v1/widget-studio/templates/{template_id}")
    def delete_template(
        template_id: str,
        _: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            store.delete_template(template_id)
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc
        return {"deleted": template_id}

    # -- assets -------------------------------------------------------
    @router.post("/v1/widget-studio/templates/{template_id}/assets/{kind}")
    async def upload_asset(
        template_id: str,
        kind: str,
        file: UploadFile = File(...),
        bg_id: str | None = Form(default=None),
        name: str | None = Form(default=None),
        _: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        data = await file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="file exceeds the 15MB limit")
        try:
            result = store.upload_asset(
                template_id, kind, data, bg_id=bg_id, name=name
            )
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc
        return result

    @router.get(
        "/v1/widget-studio/templates/{template_id}/assets/{filename:path}",
        include_in_schema=False,
    )
    def get_asset(template_id: str, filename: str) -> FileResponse:
        try:
            path = store.asset_path(template_id, filename)
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc
        return FileResponse(
            path,
            media_type=IMAGE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
            headers={"Cache-Control": "no-store"},
        )

    @router.get(
        "/v1/widget-studio/templates/{template_id}/backgrounds/{bg_id}/thumb",
        include_in_schema=False,
    )
    def background_thumb(
        template_id: str,
        bg_id: str,
        w: int = Query(default=240, ge=16, le=1024),
    ) -> Response:
        try:
            data = store.thumbnail(template_id, bg_id, w)
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/v1/widget-studio/library")
    def ghost_library() -> list[dict[str, str]]:
        return store.library()

    # -- production PNG ----------------------------------------------
    def render_widget(user_id: str, template_id: str, *, size: str | None) -> Response:
        if not isinstance(user_id, str) or not SAFE_USER_ID.fullmatch(user_id):
            raise HTTPException(status_code=404, detail=WIDGET_NOT_FOUND)
        try:
            validate_template_id(template_id)
        except ValidationError as exc:
            raise HTTPException(status_code=404, detail=WIDGET_NOT_FOUND) from exc

        status = status_for_user(user_id)
        if status is None:
            raise HTTPException(status_code=404, detail=WIDGET_NOT_FOUND)
        context = _context_from_status(status, now_fn())
        completed_today = bool(context.get("completed_today"))
        try:
            data, bg_id, text_id = store.render(template_id, context, size=size)
        except (StoreError, ValidationError) as exc:
            # Unknown directories and corrupt JSON are indistinguishable from
            # the outside.
            raise HTTPException(status_code=404, detail=WIDGET_NOT_FOUND) from exc
        except RenderError as exc:
            LOGGER.warning("widget render failed for %s/%s: %s", user_id, template_id, exc)
            raise HTTPException(status_code=500, detail="widget render failed") from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "X-Widget-Background": bg_id,
                "X-Widget-Text": text_id,
                "X-Widget-Completed": "1" if completed_today else "0",
                "Content-Disposition": "inline",
            },
        )

    @router.get(
        "/v1/widgets/{user_id}/{template_id}-1x.png",
        include_in_schema=False,
        response_class=Response,
    )
    def widget_png_1x(user_id: str, template_id: str) -> Response:
        return render_widget(user_id, template_id, size="1x")

    @router.get(
        "/v1/widgets/{user_id}/{template_id}.png",
        include_in_schema=False,
        response_class=Response,
    )
    def widget_png(user_id: str, template_id: str) -> Response:
        return render_widget(user_id, template_id, size=None)

    return router


__all__ = ["build_router", "normalize_template", "validate_template_id"]
