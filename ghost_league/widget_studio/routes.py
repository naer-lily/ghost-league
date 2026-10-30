"""HTTP routes for Widget Studio and public widget PNG rendering."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_bool(value: str | None, field: str) -> bool:
    if value is None:
        return False
    cleaned = value.strip().lower()
    if cleaned in {"1", "true", "yes", "on", "y"}:
        return True
    if cleaned in {"0", "false", "no", "off", "n", ""}:
        return False
    raise HTTPException(status_code=422, detail=f"{field} must be a boolean")


def _context_from_query(
    *,
    now: datetime,
    streak: int | None,
    xp: int | None,
    rank: int | None,
    name: str | None,
    hour: int | None,
    weekday: int | None,
    completed: str | None,
    league: str | None,
    event: str | None,
) -> dict[str, Any]:
    resolved_hour = now.hour if hour is None else hour
    resolved_weekday = now.isoweekday() if weekday is None else weekday
    resolved_streak = 0 if streak is None else streak
    resolved_xp = 0 if xp is None else xp
    resolved_rank = 0 if rank is None else rank
    if not 0 <= resolved_hour <= 23:
        raise HTTPException(status_code=422, detail="hour must be 0-23")
    if not 1 <= resolved_weekday <= 7:
        raise HTTPException(status_code=422, detail="weekday must be 1-7")
    if resolved_streak < 0:
        raise HTTPException(status_code=422, detail="streak must be >= 0")
    if resolved_xp < 0:
        raise HTTPException(status_code=422, detail="xp must be >= 0")
    if resolved_rank < 0:
        raise HTTPException(status_code=422, detail="rank must be >= 0")
    return {
        "hour": resolved_hour,
        "weekday": resolved_weekday,
        "streak": resolved_streak,
        "xp": resolved_xp,
        "rank": resolved_rank,
        "name": name or "",
        "completed_today": _parse_bool(completed, "completed"),
        "league": (league or "").strip(),
        "event": (event or "").strip(),
    }


def build_router(
    *,
    store: WidgetStore,
    auth: Callable[..., dict[str, Any]],
    now_fn: Callable[[], datetime],
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
    @router.get(
        "/v1/widgets/{template_id}.png",
        include_in_schema=False,
        response_class=Response,
    )
    def widget_png(
        template_id: str,
        token: str | None = Query(default=None),
        streak: int | None = Query(default=None),
        xp: int | None = Query(default=None),
        rank: int | None = Query(default=None),
        name: str | None = Query(default=None),
        hour: int | None = Query(default=None),
        weekday: int | None = Query(default=None),
        completed: str | None = Query(default=None),
        league: str | None = Query(default=None),
        event: str | None = Query(default=None),
        size: str | None = Query(default=None),
        bg: str | None = Query(default=None),
        text: str | None = Query(default=None),
    ) -> Response:
        if size not in {None, "", "1x"}:
            raise HTTPException(status_code=400, detail="size must be 1x")
        context = _context_from_query(
            now=now_fn(),
            streak=streak,
            xp=xp,
            rank=rank,
            name=name,
            hour=hour,
            weekday=weekday,
            completed=completed,
            league=league,
            event=event,
        )
        try:
            data, bg_id, text_id = store.render(
                template_id,
                token or "",
                context,
                size=size or None,
                bg_id=bg or None,
                text_id=text or None,
            )
        except NotFoundError as exc:
            # Wrong or missing render tokens must not reveal template existence.
            raise HTTPException(status_code=404, detail="widget not found") from exc
        except ValidationError as exc:
            raise HTTPException(status_code=404, detail="widget not found") from exc
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "X-Widget-Background": bg_id,
                "X-Widget-Text": text_id,
                "Content-Disposition": "inline",
            },
        )

    return router


__all__ = ["build_router", "normalize_template", "validate_template_id"]
