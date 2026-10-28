"""Stable anonymous identity for WakaChannel roster rows.

Ghost never needs to know the WakaTime user id.  The Channel derives a
deterministic UUIDv5 from a fixed Channel namespace and the source row id, so a
source row keeps the same ``player_ref`` across processes, restarts and display
name changes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Final

CHANNEL_ID: Final = "waka"

# A fixed UUIDv5 namespace, itself derived from the URL namespace.  Keep this
# value stable: changing it would rename every WakaTime player in Ghost.
CHANNEL_NAMESPACE: Final = uuid.uuid5(
    uuid.NAMESPACE_URL, "ghost-league/channels/waka"
)


def player_ref(source_id: str) -> str:
    """Return the stable UUIDv5 ``player_ref`` for one source row id."""

    if not isinstance(source_id, str):
        raise TypeError("source_id must be a string")
    value = source_id.strip()
    if not value:
        raise ValueError("source_id must be a non-empty string")
    return str(uuid.uuid5(CHANNEL_NAMESPACE, value))


def player_refs(source_ids: Iterable[str]) -> list[str]:
    """Return stable refs for an iterable of source ids, preserving order."""

    return [player_ref(source_id) for source_id in source_ids]


# Readable aliases used by callers/tests that prefer a more explicit name.
stable_player_ref = player_ref
source_id_to_player_ref = player_ref


__all__ = [
    "CHANNEL_ID",
    "CHANNEL_NAMESPACE",
    "player_ref",
    "player_refs",
    "source_id_to_player_ref",
    "stable_player_ref",
]
