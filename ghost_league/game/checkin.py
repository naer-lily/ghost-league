"""Check-in and Ember repair service wrappers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .store import GameStore


def repair(
    store: GameStore,
    player_id: str,
    day: date | datetime | str,
    *,
    idempotency_key: str,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    return store.repair_checkin(
        player_id,
        day,
        idempotency_key=idempotency_key,
        now=now,
    )


def grant_daily(
    store: GameStore,
    player_id: str,
    day: date | datetime | str,
    *,
    as_of: datetime | str | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    return store.grant_daily_embers(player_id, day, as_of=as_of, now=now)
