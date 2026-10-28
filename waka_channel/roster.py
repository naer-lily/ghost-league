"""Turn an anonymous weekly cache into a full WakaChannel roster manifest.

The cache is the existing ``scripts/source_fetch.py`` output.  Identity and
scoring use only ``id`` / ``rank`` / ``seconds``.  The public ``name`` and
``avatar_url`` are carried as an optional display profile; cities, e-mail
addresses and raw weekly totals never enter the roster manifest.  Normalization
uses Ghost's shared source-layer rule (``p75-soft-0.2-v1``) unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ghost_league.source.normalize import normalize_seconds

from .identity import player_ref

KIND: Final = "ai"


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One cache row after identity derivation and winsorization."""

    source_id: str
    player_ref: str
    rank: int | None
    raw_seconds: int
    effective_seconds: int
    display_name: str | None = None
    avatar_url: str | None = None

    @property
    def kind(self) -> str:
        return KIND

    @property
    def profile(self) -> dict[str, str]:
        profile = anonymous_profile(self.player_ref)
        if self.display_name and self.display_name.strip():
            profile["display_name"] = self.display_name.strip()
        if self.avatar_url and self.avatar_url.strip():
            profile["avatar_url"] = self.avatar_url.strip()
        return profile


def anonymous_profile(ref: str) -> dict[str, str]:
    """Return a stable anonymous display profile for one player ref."""

    code = ref.replace("-", "")[:8].upper()
    return {"display_name": f"Waka-{code}"}


def load_cache(path: str | Path) -> dict[str, Any]:
    """Read a JSON cache file.  This function never fetches the network."""

    cache_path = Path(path)
    with cache_path.open("r", encoding="utf-8") as handle:
        cache = json.load(handle)
    if not isinstance(cache, dict):
        raise ValueError("cache must be a JSON object")
    if not isinstance(cache.get("users"), list):
        raise ValueError("cache must contain a users array")
    return cache


def _users_from(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, (str, Path)):
        value = load_cache(value)
    if isinstance(value, Mapping):
        users = value.get("users")
        if not isinstance(users, list):
            raise ValueError("cache must contain a users array")
    elif isinstance(value, Iterable):
        users = list(value)
    else:
        raise TypeError("cache must be a mapping, path, or iterable of rows")

    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(users):
        if not isinstance(row, Mapping):
            raise TypeError(f"cache row {index} must be an object")
        rows.append(row)
    return rows


def _source_id(row: Mapping[str, Any], index: int) -> str:
    value = row.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"cache row {index} must contain a non-empty string id")
    return value.strip()


def rows_from_cache(cache: Any) -> list[SourceRow]:
    """Normalize all cache rows and attach stable player refs.

    Duplicate source ids are collapsed to their first occurrence.  Zero-second
    rows are kept: being on the board is what makes an AI a participant.
    """

    users = _users_from(cache)
    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(users):
        source_id = _source_id(row, index)
        if source_id in seen:
            continue
        seen.add(source_id)
        unique.append(row)

    normalized = normalize_seconds(unique)
    rows: list[SourceRow] = []
    for index, row in enumerate(unique):
        source_id = _source_id(row, index)
        rank = row.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int):
            rank = None
        display_name = row.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = row.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = None
        avatar_url = row.get("avatar_url")
        if not isinstance(avatar_url, str) or not avatar_url.strip():
            avatar_url = None
        rows.append(
            SourceRow(
                source_id=source_id,
                player_ref=player_ref(source_id),
                rank=rank,
                raw_seconds=int(normalized["raw_seconds"][index]),
                effective_seconds=int(normalized["effective_seconds"][index]),
                display_name=display_name,
                avatar_url=avatar_url,
            )
        )
    return rows


def roster_from_rows(rows: Iterable[SourceRow]) -> list[dict[str, Any]]:
    """Build the exact Ghost roster manifest: only ref, kind and profile."""

    players: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row.player_ref in seen:
            continue
        seen.add(row.player_ref)
        players.append(
            {
                "player_ref": row.player_ref,
                "kind": KIND,
                "profile": row.profile,
            }
        )
    return players


def build_roster(cache: Any) -> list[dict[str, Any]]:
    """Build a full roster manifest from a cache path or cache object."""

    return roster_from_rows(rows_from_cache(cache))


def roster_from_cache(path: str | Path) -> list[dict[str, Any]]:
    """Convenience wrapper for ``build_roster(load_cache(path))``."""

    return build_roster(path)


def effective_targets(rows: Iterable[SourceRow]) -> dict[str, int]:
    """Return ``player_ref -> effective weekly seconds``."""

    return {row.player_ref: row.effective_seconds for row in rows}


__all__ = [
    "KIND",
    "SourceRow",
    "anonymous_profile",
    "build_roster",
    "effective_targets",
    "load_cache",
    "roster_from_cache",
    "roster_from_rows",
    "rows_from_cache",
]
