"""Small data models shared by the schedule projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HourPoint:
    """One hour of a projected week."""

    hour_index: int
    starts_at: str
    seconds: int
    cumulative_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "hour_index": self.hour_index,
            "starts_at": self.starts_at,
            "seconds": self.seconds,
            "cumulative_seconds": self.cumulative_seconds,
        }
