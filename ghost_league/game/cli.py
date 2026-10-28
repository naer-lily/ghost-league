"""Internal command line interface for the game store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .reset import dry_run, reset_database
from .roster import DEFAULT_CACHE_PATH, seed_roster
from .rules import GameError, PlayerNotFound
from .store import DEFAULT_DB_PATH, GameStore


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str, sort_keys=False))


def _store(args: argparse.Namespace) -> GameStore:
    return GameStore(Path(args.db))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ghost_league.game.cli",
        description="Ghost League game core",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    reset = sub.add_parser("reset", help="initialize a new epoch at Bronze")
    reset.add_argument("--db", default=str(DEFAULT_DB_PATH))
    reset.add_argument("--to-bronze", action="store_true", required=True)
    mode = reset.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")
    reset.add_argument("--force-new-epoch", action="store_true")
    reset.add_argument(
        "--allow-live",
        action="store_true",
        help="allow resetting the default live data/league/league.db",
    )
    reset.add_argument("--at")

    seed = sub.add_parser("seed-roster", help="bind AI players to cached anchors")
    seed.add_argument("--db", default=str(DEFAULT_DB_PATH))
    seed.add_argument("--week", required=True)
    seed.add_argument("--count", type=int, default=14)
    seed.add_argument("--cache", default=str(DEFAULT_CACHE_PATH))
    seed.add_argument("--at")

    status = sub.add_parser("status", help="show one player's current-week state")
    status.add_argument("--db", default=str(DEFAULT_DB_PATH))
    status.add_argument("--player", required=True)
    status.add_argument("--week")
    status.add_argument("--at")

    settle = sub.add_parser("settle", help="settle one already-ended week")
    settle.add_argument("--db", default=str(DEFAULT_DB_PATH))
    settle.add_argument("--week", required=True)
    settle.add_argument("--at")

    repair = sub.add_parser("repair", help="spend one ember on a recent day")
    repair.add_argument("--db", default=str(DEFAULT_DB_PATH))
    repair.add_argument("--player", required=True)
    repair.add_argument("--date", required=True)
    repair.add_argument("--idempotency-key", required=True)
    repair.add_argument("--at")
    return parser


def _run_reset(args: argparse.Namespace) -> int:
    if args.dry_run:
        _json(dry_run(args.db))
        return 0
    try:
        result = reset_database(
            args.db,
            confirm=True,
            force_new_epoch=args.force_new_epoch,
            allow_live=args.allow_live,
            now=args.at,
        )
    except (ValueError, GameError) as exc:
        print(f"reset rejected: {exc}", file=sys.stderr)
        return 2
    _json(result)
    return 0


def _run_seed(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        result = seed_roster(
            store,
            args.week,
            count=args.count,
            cache_path=args.cache,
            at=args.at,
        )
    except (OSError, ValueError) as exc:
        print(f"seed-roster failed: {exc}", file=sys.stderr)
        return 2
    _json(result)
    return 0


def _run_status(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        _json(
            store.player_status(
                args.player,
                week=args.week,
                now=args.at,
            )
        )
    except PlayerNotFound:
        print(f"player not found: {args.player}", file=sys.stderr)
        return 2
    return 0


def _run_settle(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        result = store.settle_week(args.week, now=args.at)
    except GameError as exc:
        print(f"settle rejected: {exc}", file=sys.stderr)
        return 2
    _json(result)
    return 0


def _run_repair(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        result = store.repair_checkin(
            args.player,
            args.date,
            idempotency_key=args.idempotency_key,
            now=args.at,
        )
    except (GameError, ValueError) as exc:
        print(f"repair rejected: {exc}", file=sys.stderr)
        return 2
    _json(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "reset":
            return _run_reset(args)
        if args.command == "seed-roster":
            return _run_seed(args)
        if args.command == "status":
            return _run_status(args)
        if args.command == "settle":
            return _run_settle(args)
        if args.command == "repair":
            return _run_repair(args)
    except (GameError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
