"""Paged WakaTime public-leaderboard fetcher.

The public leaderboard is paginated: one response is only one page of the
``last_7_days`` board.  This module walks every page, de-duplicates rows by the
public WakaTime user id, and renumbers ranks over the complete snapshot.

The cache retains only ``id``, ``rank``, ``seconds``, the public display
``name`` and a public ``avatar_url``.  Cities, e-mail addresses and other
profile fields never leave this module.  The cache is written atomically and
only after every page has been fetched successfully.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Final

from .schedule import TZ, SECONDS_PER_WEEK

LEADERBOARD_URL = "https://wakatime.com/api/v1/leaders"
SOURCE_NAME: Final = "wakatime_public_leaderboard"
DEFAULT_PAGE_SIZE: Final = 100
DEFAULT_MAX_PAGES: Final = 100
DEFAULT_RATE_LIMIT_SECONDS: Final = 0.75
DEFAULT_TIMEOUT: Final = 20.0


def _coerce_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _extract_week_start(payload: dict[str, Any], now: datetime | None = None) -> str:
    data = payload.get("data")
    nested_data = data if isinstance(data, dict) else {}
    range_block = payload.get("range")
    nested_range = range_block if isinstance(range_block, dict) else {}
    nested_data_range = nested_data.get("range")
    if not isinstance(nested_data_range, dict):
        nested_data_range = {}

    candidates = (
        nested_range.get("start"),
        range_block.get("start") if isinstance(range_block, dict) else None,
        payload.get("source_week_start"),
        payload.get("start"),
        nested_data_range.get("start"),
        nested_data.get("source_week_start"),
        nested_data.get("start"),
    )
    for candidate in candidates:
        parsed = _coerce_date(candidate)
        if parsed is not None:
            return parsed

    moment = now if isinstance(now, datetime) else datetime.now(TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ)
    local = moment.astimezone(TZ)
    return (local.date() - timedelta(days=local.weekday())).isoformat()


def _format_fetched_at(now: datetime | str | None = None) -> str:
    if isinstance(now, datetime):
        moment = now
    elif isinstance(now, str):
        try:
            moment = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except ValueError:
            moment = datetime.now(timezone.utc)
    else:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (
        moment.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    if isinstance(value, float) and value.is_integer():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _extract_total_pages(payload: dict[str, Any]) -> int | None:
    data = payload.get("data")
    nested_data = data if isinstance(data, dict) else {}
    pagination = payload.get("pagination")
    nested_pagination = pagination if isinstance(pagination, dict) else {}

    candidates = (
        payload.get("total_pages"),
        payload.get("totalPages"),
        nested_data.get("total_pages"),
        nested_data.get("totalPages"),
        nested_pagination.get("total_pages"),
        nested_pagination.get("totalPages"),
    )
    for candidate in candidates:
        parsed = _positive_int(candidate)
        if parsed is not None:
            return parsed
    return None


def _extract_entries(payload: dict[str, Any]) -> list[Any] | None:
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("leaders", "data", "users"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                return candidate
    for key in ("leaders", "users"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return candidate
    return None


def _public_name(user_block: dict[str, Any], entry: dict[str, Any]) -> str:
    """Return the public display name, never private profile fields."""

    for block in (user_block, entry):
        for key in ("display_name", "name"):
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _photo_is_private(value: object) -> bool:
    if value is False or value == 0:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no"}
    return False


def _public_avatar_url(
    user_block: dict[str, Any], entry: dict[str, Any], user_id: str
) -> str | None:
    """Resolve the public avatar, honouring ``photo_public``.

    WakaTime exposes an explicit ``photo`` when the user has uploaded one.
    Otherwise the public photo endpoint is derived from the stable user id.
    A user who opted out of a public photo gets no avatar at all.
    """

    for block in (user_block, entry):
        if "photo_public" in block and _photo_is_private(block.get("photo_public")):
            return None
    for block in (user_block, entry):
        photo = block.get("photo")
        if isinstance(photo, str) and photo.strip():
            return photo.strip()
        if isinstance(photo, dict):
            nested = photo.get("url")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return f"https://wakatime.com/photo/{user_id}"


def _extract_row(entry: object) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    user = entry.get("user")
    user_block = user if isinstance(user, dict) else {}

    raw_id = user_block.get("id") or entry.get("id")
    if raw_id is None or isinstance(raw_id, bool):
        return None
    user_id = str(raw_id).strip()
    if not user_id:
        return None

    running_total = entry.get("running_total")
    total_block = running_total if isinstance(running_total, dict) else {}
    raw_seconds = total_block.get("total_seconds")
    if raw_seconds is None:
        raw_seconds = entry.get("total_seconds")
    if isinstance(raw_seconds, bool) or raw_seconds is None:
        return None
    try:
        seconds = int(raw_seconds)
    except (TypeError, ValueError):
        return None
    if seconds < 0 or seconds > SECONDS_PER_WEEK:
        return None
    return {
        "id": user_id,
        "seconds": seconds,
        "name": _public_name(user_block, entry),
        "avatar_url": _public_avatar_url(user_block, entry, user_id),
    }


def _call_with_timeout(
    function: Callable[..., Any], target: object, timeout: float
) -> Any:
    """Call an injected opener/fetcher with a timeout when it accepts one."""

    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(target, timeout=timeout)
    parameters = signature.parameters
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return function(target, timeout=timeout)
    if "timeout" in parameters:
        return function(target, timeout=timeout)
    return function(target)


def _decode_payload_body(response: object) -> Any:
    if isinstance(response, (dict, list)):
        return response
    raw = response.read() if hasattr(response, "read") else response  # type: ignore[union-attr]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _coerce_payload(response: object) -> Any:
    if isinstance(response, (dict, list)):
        return response
    if hasattr(response, "__enter__") and hasattr(response, "__exit__"):
        with response as entered:  # type: ignore[union-attr]
            if entered is response:
                return _decode_payload_body(response)
            return _coerce_payload(entered)
    return _decode_payload_body(response)


def _read_page(
    *,
    page: int,
    url: str,
    timeout: float,
    opener: Callable[..., Any] | None,
    fetch_json: Callable[..., Any] | None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ghost-league/1.0 (weekly leaderboard snapshot)",
        },
    )
    try:
        if fetch_json is not None:
            response = _call_with_timeout(fetch_json, url, timeout)
        else:
            response = _call_with_timeout(
                opener or urllib.request.urlopen, request, timeout
            )
        payload = _coerce_payload(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"could not fetch WakaTime public leaderboard page {page}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"unexpected WakaTime response on page {page}: top level is not an object"
        )
    return payload


def _build_url(
    *, page: int, page_size: int, country: str | None, language: str | None
) -> str:
    query: dict[str, str] = {"page": str(page), "limit": str(page_size)}
    if country:
        query["country_code"] = country
    if language:
        query["language"] = language
    return f"{LEADERBOARD_URL}?{urllib.parse.urlencode(query)}"


def fetch_leaderboard(
    *,
    country: str | None = None,
    language: str | None = None,
    page_size: int | None = None,
    limit: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_pages: int = DEFAULT_MAX_PAGES,
    min_interval: float = DEFAULT_RATE_LIMIT_SECONDS,
    sleep: Callable[[float], None] | None = None,
    opener: Callable[..., Any] | None = None,
    fetch_json: Callable[..., Any] | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Fetch every page of the public ``last_7_days`` leaderboard.

    ``limit`` is kept as a compatibility alias for the old fetcher and is used
    as ``page_size`` when ``page_size`` is omitted.  Tests inject ``opener`` (a
    ``urlopen``-style callable), ``fetch_json`` (a URL -> payload callable) and
    ``sleep`` so they never touch the network or wait for the rate limit.
    """

    if page_size is None:
        page_size = limit if limit is not None else DEFAULT_PAGE_SIZE
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive integer")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be a positive number")
    if (
        isinstance(min_interval, bool)
        or not isinstance(min_interval, (int, float))
        or min_interval < 0
    ):
        raise ValueError("min_interval must be a non-negative number")

    sleep_fn = sleep or time.sleep
    fetched_at = _format_fetched_at(now)
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    pages_fetched = 0
    source_week_start: str | None = None
    declared_total_pages: int | None = None
    page = 1

    while True:
        payload = _read_page(
            page=page,
            url=_build_url(
                page=page,
                page_size=page_size,
                country=country,
                language=language,
            ),
            timeout=float(timeout),
            opener=opener,
            fetch_json=fetch_json,
        )
        pages_fetched += 1
        if source_week_start is None:
            source_week_start = _extract_week_start(payload, now=now)
        if declared_total_pages is None:
            declared_total_pages = _extract_total_pages(payload)

        entries = _extract_entries(payload)
        if entries is None:
            raise RuntimeError(
                f"unexpected WakaTime response on page {page}: no leaderboard array"
            )

        new_rows = 0
        for entry in entries:
            row = _extract_row(entry)
            if row is None or row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            rows.append(row)
            new_rows += 1

        # An empty page, or a page that only repeats ids already seen, means the
        # board ended even if total_pages was optimistic.
        if not entries or (page > 1 and new_rows == 0):
            break
        if declared_total_pages is not None and page >= declared_total_pages:
            break
        if declared_total_pages is None and len(entries) < page_size:
            break
        if page >= max_pages:
            raise RuntimeError(
                "maximum page count reached before the full leaderboard was fetched "
                f"({max_pages} pages)"
            )
        sleep_fn(float(min_interval))
        page += 1

    if not rows:
        raise RuntimeError("WakaTime leaderboard contained no usable anonymous rows")

    users = [
        {
            "id": row["id"],
            "rank": index,
            "seconds": row["seconds"],
            "name": row["name"],
            "avatar_url": row["avatar_url"],
        }
        for index, row in enumerate(rows, start=1)
    ]
    return {
        "source": SOURCE_NAME,
        "source_week_start": source_week_start
        or _extract_week_start({}, now=now if isinstance(now, datetime) else None),
        "fetched_at": fetched_at,
        "pages": pages_fetched,
        "row_count": len(users),
        "page_size": page_size,
        "users": users,
    }


def write_cache(data: dict[str, Any], out_path: str | Path) -> Path:
    """Atomically replace the cache after a complete successful fetch."""

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return path


# Explicit alias for callers that want the atomic guarantee in the name.
write_cache_atomic = write_cache


def fetch_to_cache(
    out_path: str | Path,
    *,
    dry_run: bool = False,
    **fetch_kwargs: Any,
) -> dict[str, Any]:
    """Fetch a complete snapshot and optionally write it atomically."""

    data = fetch_leaderboard(**fetch_kwargs)
    if not dry_run:
        write_cache(data, out_path)
    return data


__all__ = [
    "DEFAULT_MAX_PAGES",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_RATE_LIMIT_SECONDS",
    "DEFAULT_TIMEOUT",
    "LEADERBOARD_URL",
    "SOURCE_NAME",
    "fetch_leaderboard",
    "fetch_to_cache",
    "write_cache",
    "write_cache_atomic",
]
