"""Waka projection transport for the account-backed channel.

Waka remains a source/projection library: ``waka_channel`` reads the cached
leaderboard snapshot and projects each weekly target into completed hourly
increments.  This module only changes the transport.  Every increment is sent
to Ghost through the ordinary account API (``POST /v1/me/increments``) with the
already stored Waka event id, seconds and ``occurred_at``.

Nothing here writes Ghost's database or calls Channel ingest.  A projected
``player_ref`` is mapped to the ordinary account that already exists for it;
when that account token is missing the player is reported and skipped, never
created.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from waka_channel.projection import (
    HourlyIncrement,
    TickPlan,
    parse_at as parse_waka_at,
    parse_week_start,
    tick_increments,
)
from waka_channel.roster import rows_from_cache
from waka_channel.state import ChannelState

from .client import AIClient, AIChannelHTTPError, AIChannelTransportError
from .policy import TZ
from .store import StateStore

Output = Callable[[str], None]

WAKA_CHANNEL_ID = "waka"
CHANNEL_PLAYER_NAMESPACE = b"ghost-channel-player-v1\x00"
DEFAULT_CACHE = Path("data/cache/cn-978.json")
DEFAULT_STATE = Path("data/cache/waka-channel-state.json")


def ghost_user_id(player_ref: str) -> str:
    """Return the stable Ghost account id for one Waka ``player_ref``.

    This is the same derivation Ghost uses for ``(channel_id, player_ref)``:
    ``ch-`` + sha256(``ghost-channel-player-v1\\0waka\\0`` + ``player_ref``).
    Keeping the formula here lets the Channel address those ordinary accounts
    without importing Ghost's game store.
    """

    if not isinstance(player_ref, str) or not player_ref:
        raise ValueError("player_ref must be a non-empty string")
    digest = hashlib.sha256(
        CHANNEL_PLAYER_NAMESPACE
        + WAKA_CHANNEL_ID.encode("utf-8")
        + b"\x00"
        + player_ref.encode("utf-8")
    ).hexdigest()
    return f"ch-{digest}"


def waka_plan(
    cache: str | Path,
    *,
    at: datetime | str | None = None,
    week_start: date | str | None = None,
    cursors: Mapping[str, str] | None = None,
) -> TickPlan:
    """Plan one idempotent tick from the existing Waka cache."""

    moment = parse_waka_at(at if at is not None else datetime.now(TZ))
    week = (
        parse_week_start(week_start)
        if week_start is not None
        else parse_week_start(moment)
    )
    return tick_increments(
        rows_from_cache(cache),
        moment,
        week_start=week,
        cursors=cursors,
    )


def _token_for(store: StateStore, user_id: str) -> str | None:
    account = store.get_account(user_id, include_token=True)
    if account is None:
        return None
    token = account.get("token")
    return token if isinstance(token, str) and token else None


def waka_tick(
    client: AIClient,
    store: StateStore,
    *,
    at: datetime | str | None = None,
    cache: str | Path = DEFAULT_CACHE,
    state: ChannelState | None = None,
    state_path: str | Path = DEFAULT_STATE,
    week_start: date | str | None = None,
    out: Output = print,
) -> dict[str, Any]:
    """Send completed Waka hours through ``POST /v1/me/increments``.

    The cursor is the existing Waka weekly hour cursor, so a cutover from the
    legacy Channel push resumes exactly where it stopped.  The cursor only
    advances for players whose whole batch was accepted; a missing token or an
    HTTP failure leaves that player's cursor untouched and is safe to retry
    because Ghost deduplicates by ``event_id``.
    """

    cursor = state if state is not None else ChannelState.load(state_path)
    moment = parse_waka_at(at if at is not None else datetime.now(TZ))
    week = (
        parse_week_start(week_start)
        if week_start is not None
        else parse_week_start(moment)
    )
    plan = tick_increments(
        rows_from_cache(cache),
        moment,
        week_start=week,
        cursors=cursor.cursors(week.isoformat()),
    )

    events_by_ref: dict[str, list[HourlyIncrement]] = {}
    for event in plan.events:
        events_by_ref.setdefault(event.player_ref, []).append(event)

    missing: list[str] = []
    missing_player_refs: list[str] = []
    next_hours: dict[str, str] = {}
    tokens: dict[str, str | None] = {}
    sent = 0
    duplicates = 0
    errors = 0
    accounted = 0

    for player_ref, last_hour in plan.next_hours.items():
        user_id = ghost_user_id(player_ref)
        if user_id not in tokens:
            tokens[user_id] = _token_for(store, user_id)
        token = tokens[user_id]
        if token is None:
            missing.append(user_id)
            missing_player_refs.append(player_ref)
            out(f"{user_id}\tmissing-token\t{player_ref}")
            continue
        accounted += 1
        failed = False
        for event in events_by_ref.get(player_ref, ()):
            try:
                response = client.send_increment(
                    token,
                    event.event_id,
                    event.seconds,
                    event.occurred_at.isoformat(timespec="seconds"),
                )
            except (
                AIChannelHTTPError,
                AIChannelTransportError,
                ValueError,
                TypeError,
            ) as exc:
                errors += 1
                failed = True
                out(f"{user_id}\tincrement\t{event.event_id}\terror\t{exc}")
                break
            sent += 1
            if isinstance(response, Mapping) and response.get("duplicate"):
                duplicates += 1
        if not failed:
            next_hours[player_ref] = last_hour

    cursor.mark(plan.week_start.isoformat(), next_hours)
    cursor.save(state_path if cursor.path is None else None)

    summary: dict[str, Any] = {
        "source": WAKA_CHANNEL_ID,
        "channel": WAKA_CHANNEL_ID,
        "at": plan.at.isoformat(timespec="seconds"),
        "boundary": plan.boundary.isoformat(timespec="seconds"),
        "week_start": plan.week_start.isoformat(),
        "accounts": len(plan.next_hours),
        "events": len(plan.events),
        "players": plan.players,
        "seconds": plan.total_seconds,
        "increments": sent,
        "sent": sent,
        "duplicates": duplicates,
        "purchases": 0,
        "missing_tokens": len(missing),
        "missing": missing,
        "missing_player_refs": missing_player_refs,
        "skipped": len(missing),
        "accounted": accounted,
        "errors": errors,
    }
    out(
        "waka: "
        f"week_start={summary['week_start']} accounts={summary['accounts']} "
        f"events={summary['events']} players={summary['players']} "
        f"sent={sent} duplicates={duplicates} "
        f"missing_tokens={len(missing)} errors={errors}"
    )
    return summary


# Readable alias for callers that prefer an explicit name.
tick = waka_tick


__all__ = [
    "CHANNEL_PLAYER_NAMESPACE",
    "DEFAULT_CACHE",
    "DEFAULT_STATE",
    "WAKA_CHANNEL_ID",
    "ghost_user_id",
    "tick",
    "waka_plan",
    "waka_tick",
]
