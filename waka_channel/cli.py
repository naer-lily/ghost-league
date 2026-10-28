"""Command line entry points for WakaChannel.

Examples::

    python -m waka_channel.cli sync-roster --cache data/cache/cn-978.json
    python -m waka_channel.cli tick --at 2026-10-28T12:00:00+08:00

The token is read from ``GHOST_LEAGUE_CHANNEL_TOKEN`` so it never appears in
shell history or process arguments.  The cache is read-only; only the small
local cursor file is written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from ghost_league.schedule import TZ

from .client import DEFAULT_BASE_URL, ChannelClient
from .projection import parse_at, parse_week_start, tick_increments
from .roster import roster_from_rows, rows_from_cache
from .state import ChannelState

DEFAULT_CACHE = Path("data/cache/cn-978.json")
DEFAULT_STATE = Path(
    os.environ.get("WAKA_CHANNEL_STATE", "data/cache/waka-channel-state.json")
)


def sync_roster(
    client: ChannelClient,
    *,
    cache: str | Path = DEFAULT_CACHE,
) -> dict[str, Any]:
    """Read the full cache and POST one authoritative roster manifest."""

    rows = rows_from_cache(cache)
    players = roster_from_rows(rows)
    response = client.post_roster(players)
    return {
        "channel": client.channel,
        "count": len(players),
        "response": response,
    }


def tick(
    client: ChannelClient,
    *,
    at: datetime | str | None = None,
    cache: str | Path = DEFAULT_CACHE,
    state: ChannelState | None = None,
    state_path: str | Path = DEFAULT_STATE,
    week_start: str | None = None,
) -> dict[str, Any]:
    """Send only completed, not-yet-cursor-processed hourly increments."""

    moment = at if at is not None else datetime.now(TZ)
    local_moment = parse_at(moment)
    cursor = state if state is not None else ChannelState.load(state_path)
    rows = rows_from_cache(cache)
    week = (
        parse_week_start(week_start)
        if week_start is not None
        else parse_week_start(local_moment)
    )
    plan = tick_increments(
        rows,
        local_moment,
        week_start=week,
        cursors=cursor.cursors(week.isoformat()),
    )
    responses = client.send_increments(plan.events)
    cursor.mark(plan.week_start.isoformat(), plan.next_hours)
    cursor.save(state_path if cursor.path is None else None)
    return {
        "channel": client.channel,
        "at": plan.at.isoformat(timespec="seconds"),
        "boundary": plan.boundary.isoformat(timespec="seconds"),
        "week_start": plan.week_start.isoformat(),
        "events": len(plan.events),
        "players": plan.players,
        "seconds": plan.total_seconds,
        "sent": len(responses),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m waka_channel.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    roster = subparsers.add_parser(
        "sync-roster", help="POST the full anonymous weekly roster"
    )
    roster.add_argument("--cache", default=str(DEFAULT_CACHE))
    roster.add_argument("--base-url", default=DEFAULT_BASE_URL)
    roster.add_argument("--channel", default="waka")
    roster.add_argument("--timeout", type=float, default=10.0)

    tick_parser = subparsers.add_parser(
        "tick", help="POST completed hourly increments"
    )
    tick_parser.add_argument(
        "--at",
        default=None,
        help="ISO-8601 tick time in Asia/Shanghai (default: now)",
    )
    tick_parser.add_argument(
        "--week-start",
        default=None,
        help="optional ISO Monday; defaults to the week containing --at",
    )
    tick_parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    tick_parser.add_argument("--state", default=str(DEFAULT_STATE))
    tick_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    tick_parser.add_argument("--channel", default="waka")
    tick_parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = ChannelClient(
        args.base_url,
        channel=args.channel,
        timeout=args.timeout,
    )
    try:
        if args.command == "sync-roster":
            summary = sync_roster(client, cache=args.cache)
        else:
            summary = tick(
                client,
                at=args.at,
                cache=args.cache,
                state_path=args.state,
                week_start=args.week_start,
            )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"waka-channel: error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
