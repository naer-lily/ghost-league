"""Provider-neutral Channel -> Ghost ingest contract.

Channels own provider pulls, identity mapping, hour projection and cursors.
Ghost only accepts anonymous ``player_ref`` values and small increments.  The
types here intentionally contain no provider names, source payloads or raw
weekly totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RosterPlayer:
    """One player announced by a Channel.

    ``player_ref`` is only unique inside the Channel namespace.  ``profile`` is
    a display snapshot, not game state; Ghost derives an ordinary player
    identity and does not accept any AI marker from a Channel.
    """

    player_ref: str
    profile: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class IncrementEvent:
    """One already-projected hourly activity increment.

    ``event_id`` is globally idempotent in Ghost.  ``seconds`` is an
    already-normalized increment, never a provider weekly total.
    """

    player_ref: str
    event_id: str
    seconds: int
    occurred_at: datetime


__all__ = ["IncrementEvent", "RosterPlayer"]
