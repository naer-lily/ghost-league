#!/usr/bin/env python3
"""Backfill diamonds for historical lifetime XP milestones.

Rule: every complete 10 lifetime XP earns 1 diamond.  ``ingest_activity``
already credits new milestones; this one-shot script catches up players whose
XP existed before that rule was wired into the wallet ledger.

The ledger row is idempotent per ``(player, target milestone)``, so running the
script again is safe and reports 0 for players already caught up.  Historical
catch-up always credits the base amount (``boost=False``); an active XP boost
is not applied retroactively.

Usage::

    python3 scripts/backfill_xp_diamonds.py --dry-run
    python3 scripts/backfill_xp_diamonds.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ghost_league.game import calendar as cal  # noqa: E402
from ghost_league.game.store import DEFAULT_DB_PATH, GameStore  # noqa: E402

XP_DIAMOND_REASON = "xp_milestone"
BACKFILL_KEY_PREFIX = "xp-diamond-backfill-v1"


def _players_with_lifetime_xp(conn) -> list[Any]:
    return conn.execute(
        "SELECT p.id AS player_id, "
        "COALESCE(SUM(w.xp), 0) AS lifetime_xp "
        "FROM weekly_scores w JOIN players p ON p.id = w.player_id "
        "GROUP BY p.id ORDER BY p.id"
    ).fetchall()


def _credited_xp_diamonds(conn, player_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) AS total FROM diamond_ledger "
        "WHERE player_id = ? AND reason = ?",
        (player_id, XP_DIAMOND_REASON),
    ).fetchone()
    return int(row["total"]) if row is not None else 0


def backfill_xp_diamonds(
    store: GameStore,
    *,
    dry_run: bool = False,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Credit the missing XP diamonds for every player with weekly scores."""

    local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
    results: list[dict[str, Any]] = []
    with store.transaction() as conn:
        for row in _players_with_lifetime_xp(conn):
            player_id = str(row["player_id"])
            lifetime_xp = int(row["lifetime_xp"])
            target = lifetime_xp // 10
            already_credited = _credited_xp_diamonds(conn, player_id)
            shortfall = target - already_credited
            entry: dict[str, Any] = {
                "player_id": player_id,
                "lifetime_xp": lifetime_xp,
                "target": target,
                "already_credited": already_credited,
                "shortfall": shortfall,
                "credited": 0,
            }
            if shortfall <= 0:
                entry["status"] = "up_to_date"
            elif dry_run:
                entry["status"] = "would_credit"
                entry["credited"] = shortfall
            else:
                credited = store._credit_diamonds_with(  # type: ignore[attr-defined]
                    conn,
                    player_id=player_id,
                    amount=shortfall,
                    reason=XP_DIAMOND_REASON,
                    ref_type="lifetime_xp",
                    ref_id=str(target),
                    idempotency_key=(
                        f"{BACKFILL_KEY_PREFIX}:{player_id}:{target}"
                    ),
                    now=local_now,
                    boost=False,
                )
                entry["status"] = "credited"
                entry["credited"] = int(credited["delta"])
            results.append(entry)
    return {
        "dry_run": dry_run,
        "credited": sum(int(entry["credited"]) for entry in results),
        "players_credited": sum(
            1 for entry in results if int(entry["credited"]) > 0
        ),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/backfill_xp_diamonds.py",
        description=(
            "Credit missing diamonds for lifetime XP milestones "
            "(10 XP = 1 diamond); idempotent per player and milestone"
        ),
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"league SQLite path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be credited without writing the ledger",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = GameStore(Path(args.db))
    result = backfill_xp_diamonds(store, dry_run=args.dry_run)
    for entry in result["results"]:
        player_id = entry["player_id"]
        target = entry["target"]
        status = entry["status"]
        if status == "would_credit":
            print(
                f"{player_id}: would credit +{entry['credited']} diamonds "
                f"(target {target})"
            )
        elif status == "credited":
            print(
                f"{player_id}: +{entry['credited']} diamonds (target {target})"
            )
        else:
            print(f"{player_id}: 0 (target {target})")
    prefix = "dry-run" if result["dry_run"] else "backfill"
    print(
        f"{prefix}: {result['credited']} diamonds to "
        f"{result['players_credited']} players"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
