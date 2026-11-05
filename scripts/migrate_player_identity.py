#!/usr/bin/env python3
"""Apply the idempotent player-identity schema migration to one league DB.

The migration itself lives in ``GameStore.initialize()``: old ``players.kind`` /
``players.controller`` and ``channel_players.kind`` columns are removed by
rebuilding the tables, preserving ids, source keys, profiles, XP and group
memberships.  A backup is written beside the database before any table is
changed.

Usage::

    PYTHONPATH=. python3 scripts/migrate_player_identity.py --db data/league/league.db

Stop the API before running this against the live database.  Re-running it on
an already migrated database is a no-op.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ghost_league.game.store import DEFAULT_DB_PATH, GameStore  # noqa: E402


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/migrate_player_identity.py",
        description=(
            "Back up and rebuild players/channel_players without the retired "
            "identity columns; idempotent"
        ),
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"league SQLite path (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args(argv)
    path = Path(args.db)
    if not path.exists():
        parser.error(f"database does not exist: {path}")

    with sqlite3.connect(path) as conn:
        before_columns = _columns(conn, "players")
        before_mappings = _columns(conn, "channel_players")
    needed = {"kind", "controller"} & set(before_columns)
    needed |= {"kind"} & set(before_mappings)

    store = GameStore(path, epoch_reason="player-identity-migration")
    backups = sorted(path.parent.glob(f"{path.name}.backup-player-identity-*"))
    with sqlite3.connect(path) as conn:
        after_columns = _columns(conn, "players")
        after_mappings = _columns(conn, "channel_players")
        report = {
            "db": str(path),
            "migration_applied": bool(needed),
            "players": _count(conn, "players"),
            "channel_players": _count(conn, "channel_players"),
            "group_members": _count(conn, "group_members"),
            "players_have_kind": "kind" in after_columns,
            "players_have_controller": "controller" in after_columns,
            "channel_players_have_kind": "kind" in after_mappings,
            "backup": str(backups[-1]) if needed and backups else None,
        }
    report["integrity_check"] = store.integrity_check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if (
        report["players_have_kind"]
        or report["players_have_controller"]
        or report["channel_players_have_kind"]
        or report["integrity_check"] != "ok"
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
