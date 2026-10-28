"""Small local cursor for WakaChannel hourly ticks.

Ghost already deduplicates by global ``event_id``.  This cursor is an
additional Channel-side guard so repeating the same tick does not even resend
the same hours.  State is keyed by ISO week and anonymous ``player_ref`` only;
it never stores provider rows, tokens or Ghost history.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from .projection import parse_week_start

STATE_VERSION: Final = 1


class ChannelState:
    """Week-scoped processed-hour cursor backed by a small JSON file."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self._weeks: dict[str, dict[str, str]] = {}
        if data is not None:
            self._load_data(data)

    @classmethod
    def load(cls, path: str | Path) -> ChannelState:
        state_path = Path(path)
        if not state_path.exists():
            return cls(state_path)
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("state must be a JSON object")
        return cls(state_path, data=data)

    def _load_data(self, data: Mapping[str, Any]) -> None:
        version = data.get("version", STATE_VERSION)
        if version != STATE_VERSION:
            raise ValueError(f"unsupported state version: {version!r}")
        weeks = data.get("weeks", {})
        if not isinstance(weeks, Mapping):
            raise ValueError("state weeks must be an object")
        loaded: dict[str, dict[str, str]] = {}
        for week, cursors in weeks.items():
            week_iso = parse_week_start(str(week)).isoformat()
            if not isinstance(cursors, Mapping):
                raise ValueError("state week cursors must be an object")
            loaded[week_iso] = {
                str(ref): str(hour)
                for ref, hour in cursors.items()
                if isinstance(ref, str) and isinstance(hour, str)
            }
        self._weeks = loaded

    def cursors(self, week_start: str) -> dict[str, str]:
        week = parse_week_start(week_start).isoformat()
        return dict(self._weeks.get(week, {}))

    def last_hour(self, week_start: str, player_ref: str) -> str | None:
        week = parse_week_start(week_start).isoformat()
        return self._weeks.get(week, {}).get(player_ref)

    def mark(self, week_start: str, next_hours: Mapping[str, str]) -> None:
        """Record each ref's last processed hour start for one week."""

        week = parse_week_start(week_start).isoformat()
        bucket = self._weeks.setdefault(week, {})
        for ref, hour in next_hours.items():
            if not isinstance(ref, str) or not ref:
                raise ValueError("state player_ref must be a non-empty string")
            if not isinstance(hour, str) or not hour:
                raise ValueError("state hour must be a non-empty ISO timestamp")
            bucket[ref] = hour

    def mark_hour(self, week_start: str, player_ref: str, hour: str) -> None:
        self.mark(week_start, {player_ref: hour})

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "weeks": {
                week: dict(sorted(cursors.items()))
                for week, cursors in sorted(self._weeks.items())
            },
        }

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("state path is required to save cursors")
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        return target


def load_state(path: str | Path) -> ChannelState:
    return ChannelState.load(path)


__all__ = ["STATE_VERSION", "ChannelState", "load_state"]
