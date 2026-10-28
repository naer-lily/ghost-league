"""Weekly lock/settlement service wrapper."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .store import GameStore


def settle_week(
    store: GameStore,
    week,
    *,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    return store.settle_week(week, now=now)
