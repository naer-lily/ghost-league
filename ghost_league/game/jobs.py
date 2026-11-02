"""Deployable weekly settlement job.

The Channel owns hourly ingest. Ghost only needs to settle the previous local
week, so this module stays a thin wrapper around the game store with explicit
skip semantics for timers that run early or twice.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import calendar as cal
from .store import DEFAULT_DB_PATH, GameStore


def run_weekly_settlement(
    db_path: str | Path,
    *,
    at: datetime | str | None = None,
) -> dict[str, Any]:
    """Settle only the week before the current local week.

    The job never pre-creates the next week and never settles older weeks. A
    week that has not ended or has no group is reported as ``skipped`` rather
    than raised, so a persistent/holiday-delayed timer remains safe to rerun.
    """

    local_now = cal.parse_datetime(at) if at is not None else cal.now_local()
    previous_week = cal.previous_week_start(local_now)
    week_iso = cal.iso_date(previous_week)

    store = GameStore(Path(db_path))
    if local_now < cal.week_end_at(previous_week):
        return {
            "status": "skipped",
            "reason": "week_not_ended",
            "skipped": True,
            "already_settled": False,
            "week_start": week_iso,
            "results": [],
        }

    result = store.settle_week(previous_week, now=local_now)
    if result.get("already_settled"):
        return {
            "status": "already_settled",
            "skipped": False,
            **result,
        }
    if not result.get("results"):
        return {
            "status": "skipped",
            "reason": "no_group",
            "skipped": True,
            "already_settled": False,
            "week_start": week_iso,
            "results": [],
        }
    return {
        "status": "settled",
        "skipped": False,
        **result,
    }


def run_power_refresh(
    db_path: str | Path,
    *,
    at: datetime | str | None = None,
) -> dict[str, Any]:
    """Refresh every player's current power without writing weekly history.

    The hourly timer may run this as often as it likes; the operation is a
    deterministic projection of ``weekly_scores`` and is safe to repeat.
    """

    local_now = cal.parse_datetime(at) if at is not None else cal.now_local()
    store = GameStore(Path(db_path))
    return store.recompute_power(now=local_now)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ghost_league.game.jobs",
        description="Run one Ghost League background job.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    settle = sub.add_parser("settle", help="settle only the previous local week")
    settle.add_argument("--db", default=str(DEFAULT_DB_PATH))
    settle.add_argument("--at")
    power = sub.add_parser(
        "power", help="refresh current player power from recent weekly XP"
    )
    power.add_argument("--db", default=str(DEFAULT_DB_PATH))
    power.add_argument("--at")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "settle":
        result = run_weekly_settlement(args.db, at=args.at)
    elif args.command == "power":
        result = run_power_refresh(args.db, at=args.at)
    else:  # pragma: no cover - argparse rejects unknown subcommands
        parser.error(f"unknown command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
