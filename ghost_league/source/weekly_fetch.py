"""Source-layer alias for the paged weekly leaderboard adapter.

The implementation lives in the fetch module so existing callers keep working.
It only exposes anonymous weekly rows and has no game/competition imports.
"""

from __future__ import annotations

from ..fetch import (
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_TIMEOUT,
    LEADERBOARD_URL,
    SOURCE_NAME,
    fetch_leaderboard,
    fetch_to_cache,
    write_cache,
    write_cache_atomic,
)

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
