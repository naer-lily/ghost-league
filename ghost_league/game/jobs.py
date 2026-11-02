"""Reusable background job entry points.

The Channel owns hourly ingest. Ghost only needs to settle the previous local
week, so this module stays a thin wrapper around the game store with explicit
skip semantics when a job runs early or twice.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
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
    than raised, so a delayed or repeated scheduler pass remains safe.
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

    The scheduler may run this as often as it likes; the operation is a
    deterministic projection of ``weekly_scores`` and is safe to repeat.
    """

    local_now = cal.parse_datetime(at) if at is not None else cal.now_local()
    store = GameStore(Path(db_path))
    return store.recompute_power(now=local_now)


def run_grant_diamonds(
    db_path: str | Path,
    *,
    player_id: str,
    amount: int,
    reason: str = "test",
    idempotency_key: str | None = None,
    at: datetime | str | None = None,
) -> dict[str, Any]:
    """Local/operator-only diamond grant; never exposed as an HTTP route."""

    local_now = cal.parse_datetime(at) if at is not None else cal.now_local()
    store = GameStore(Path(db_path))
    result = store.credit_diamonds(
        player_id,
        amount,
        reason,
        ref_type="manual_grant",
        ref_id=reason,
        idempotency_key=idempotency_key,
        now=local_now,
    )
    return {
        "status": "credited",
        "player_id": player_id,
        "amount": amount,
        "reason": reason,
        **result,
    }


def run_diamond_decay(
    db_path: str | Path,
    *,
    at: datetime | str | None = None,
) -> dict[str, Any]:
    """Apply the hourly soft-cap decay to every existing wallet.

    The operation uses the same pure function as lazy wallet reads, so an
    offline server catches up at the next scheduler pass or read without
    double-charging a complete hour.
    """

    local_now = cal.parse_datetime(at) if at is not None else cal.now_local()
    store = GameStore(Path(db_path))
    result = store.apply_all_diamond_decay(now=local_now)
    return {
        "status": "decayed" if result["decayed"] else "ok",
        **result,
    }


def run_auto_assign_rivals(
    db_path: str | Path,
    *,
    at: datetime | str | None = None,
) -> dict[str, Any]:
    """Pair every human without a rival from Tuesday 00:00 onward.

    Running early is a harmless skip, and repeated runs never replace an
    existing assignment.
    """

    local_now = cal.parse_datetime(at) if at is not None else cal.now_local()
    week = cal.week_start(local_now)
    store = GameStore(Path(db_path))
    result = store.auto_assign_rivals(week, now=local_now)
    return {
        "status": result.get("status", "ok"),
        **result,
    }


def run_daily_bets(
    db_path: str | Path,
    *,
    day: date | str | None = None,
    at: datetime | str | None = None,
) -> dict[str, Any]:
    """Settle one day's daily bets once its 10:30 cutoff has passed.

    ``day`` defaults to the local date of ``at``.  The scheduler passes an
    explicit date when catching up a missed day.
    """

    local_now = cal.parse_datetime(at) if at is not None else cal.now_local()
    target_day = cal.parse_date(day) if day is not None else local_now.date()
    store = GameStore(Path(db_path))
    result = store.settle_daily_bets(target_day, now=local_now)
    return {
        "status": result.get("status", "settled"),
        **result,
    }


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
    grant = sub.add_parser(
        "grant-diamonds",
        help="local-only diamond credit for testing or future rewards",
    )
    grant.add_argument("--db", default=str(DEFAULT_DB_PATH))
    grant.add_argument("--player", dest="player_id", required=True)
    grant.add_argument("--amount", type=int, required=True)
    grant.add_argument("--reason", default="test")
    grant.add_argument("--idempotency-key")
    grant.add_argument("--at")
    decay = sub.add_parser(
        "diamond-decay", help="apply hourly soft-cap decay to every wallet"
    )
    decay.add_argument("--db", default=str(DEFAULT_DB_PATH))
    decay.add_argument("--at")
    rival_auto = sub.add_parser(
        "rival-auto", help="auto-select rivals for humans without one"
    )
    rival_auto.add_argument("--db", default=str(DEFAULT_DB_PATH))
    rival_auto.add_argument("--at")
    daily_bets = sub.add_parser(
        "daily-bets", help="settle one day's daily bets at 10:30"
    )
    daily_bets.add_argument("--db", default=str(DEFAULT_DB_PATH))
    daily_bets.add_argument(
        "--day", help="ISO date to settle (default: the local date of --at)"
    )
    daily_bets.add_argument("--at")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "settle":
        result = run_weekly_settlement(args.db, at=args.at)
    elif args.command == "power":
        result = run_power_refresh(args.db, at=args.at)
    elif args.command == "grant-diamonds":
        result = run_grant_diamonds(
            args.db,
            player_id=args.player_id,
            amount=args.amount,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
            at=args.at,
        )
    elif args.command == "diamond-decay":
        result = run_diamond_decay(args.db, at=args.at)
    elif args.command == "rival-auto":
        result = run_auto_assign_rivals(args.db, at=args.at)
    elif args.command == "daily-bets":
        result = run_daily_bets(args.db, day=args.day, at=args.at)
    else:  # pragma: no cover - argparse rejects unknown subcommands
        parser.error(f"unknown command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
