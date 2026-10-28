"""Independent source adapters and normalization.

Import from here when feeding external data into the league; this package does
not depend on the competition rules or player model.
"""

from .normalize import (
    NORMALIZATION_VERSION,
    P75_QUANTILE,
    SOFT_EXPONENT,
    normalize_seconds,
)
from .weekly_fetch import (
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_TIMEOUT,
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
    "NORMALIZATION_VERSION",
    "P75_QUANTILE",
    "SOFT_EXPONENT",
    "SOURCE_NAME",
    "fetch_leaderboard",
    "fetch_to_cache",
    "normalize_seconds",
    "write_cache",
    "write_cache_atomic",
]
