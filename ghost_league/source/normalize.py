"""Generic source-layer winsorization for public leaderboard snapshots.

The source layer only knows about external weekly row totals.  It has no
player, competition or grouping concepts: every snapshot is normalized by the
same deterministic rule, and the raw values stay available for audit.

Rule (``p75-soft-0.2-v1``)::

    p75 = sorted(seconds)[floor(0.75 * (n - 1))]
    if raw <= p75:
        effective = raw
    else:
        effective = round(p75 * (raw / p75) ** 0.20)

The transform is monotonic and order preserving.  Values at or below the 75th
percentile are untouched, while extreme rows are compressed without collapsing
all of them onto one shared value.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, Final

NORMALIZATION_VERSION: Final = "p75-soft-0.2-v1"
P75_QUANTILE: Final = 0.75
SOFT_EXPONENT: Final = 0.20

_SECONDS_KEYS: Final = ("seconds", "raw_seconds", "anchor_seconds")


def _extract_seconds(row: object, index: int) -> int:
    """Read one non-negative integer second count from a row or scalar."""

    if isinstance(row, Mapping):
        for key in _SECONDS_KEYS:
            if key in row:
                value = row[key]
                break
        else:
            raise ValueError(
                f"row {index} must contain one of {_SECONDS_KEYS}"
            )
    else:
        value = row

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"row {index} seconds must be an integer")
    if value < 0:
        raise ValueError(f"row {index} seconds must be non-negative")
    return value


def _effective_seconds(raw: int, p75: int) -> int:
    if raw <= p75:
        return raw
    if p75 == 0:
        # A zero p75 means at least three quarters of the snapshot is zero.
        # The soft-cap formula would divide by zero; keeping the positive tail
        # avoids silently erasing the only observed activity.
        return raw
    return round(p75 * (raw / p75) ** SOFT_EXPONENT)


def normalize_seconds(rows: Iterable[object]) -> dict[str, Any]:
    """Normalize one weekly snapshot's ``seconds`` list.

    ``rows`` may be a sequence of integers or a sequence of mappings containing
    ``seconds`` (``raw_seconds``/``anchor_seconds`` are also accepted).  The
    return value has the same order as the input::

        {
            "raw_seconds": [...],
            "effective_seconds": [...],
            "p75_seconds": int,
            "version": "p75-soft-0.2-v1",
        }

    An empty snapshot is valid and returns empty lists with ``p75_seconds`` 0.
    The function is pure, deterministic, offline, and performs no I/O.
    """

    if isinstance(rows, (str, bytes)):
        raise TypeError("rows must be an iterable of rows, not text")
    try:
        items = list(rows)
    except TypeError as exc:
        raise TypeError("rows must be an iterable of rows") from exc

    raw_seconds = [_extract_seconds(row, index) for index, row in enumerate(items)]
    if raw_seconds:
        ordered = sorted(raw_seconds)
        p75 = ordered[math.floor(P75_QUANTILE * (len(ordered) - 1))]
    else:
        p75 = 0
    effective_seconds = [_effective_seconds(raw, p75) for raw in raw_seconds]
    return {
        "raw_seconds": raw_seconds,
        "effective_seconds": effective_seconds,
        "p75_seconds": int(p75),
        "version": NORMALIZATION_VERSION,
    }
