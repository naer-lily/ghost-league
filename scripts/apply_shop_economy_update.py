#!/usr/bin/env python3
"""Apply the one-time boost price and ember cooldown update.

This script is safe to run more than once.  It backs up the database first,
then lets ``GameStore.initialize`` run the same idempotent migration that the
API uses on startup.  Only ``diamond_boost_25_price``,
``diamond_boost_60_price``, and the legacy ``ember`` row are touched; a marker
in ``meta`` prevents later operator edits from being overwritten.

Usage::

    python3 scripts/apply_shop_economy_update.py --dry-run
    python3 scripts/apply_shop_economy_update.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ghost_league.game.store import DEFAULT_DB_PATH, GameStore  # noqa: E402
from ghost_league.game.store.core import SHOP_ECONOMY_UPDATE_KEY  # noqa: E402

DEFAULT_BACKUP_DIR = Path("data/league/backups")
LEGACY_EMBER_DESCRIPTION = "立即获得 1 枚余烬；每 72 小时最多购买一次。"
EMBER_DESCRIPTION = "立即获得 1 枚余烬；每 7 天最多购买一次。"


def _state(db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        config = {
            str(row["key"]): str(row["value"])
            for row in conn.execute(
                "SELECT key, value FROM game_config WHERE key IN (?, ?) "
                "ORDER BY key",
                ("diamond_boost_25_price", "diamond_boost_60_price"),
            )
        }
        ember = conn.execute(
            "SELECT description, cooldown_seconds FROM shop_items "
            "WHERE id = 'ember'"
        ).fetchone()
        marker = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (SHOP_ECONOMY_UPDATE_KEY,),
        ).fetchone()
        return {
            "config": config,
            "ember": None if ember is None else dict(ember),
            "marker": None if marker is None else str(marker["value"]),
        }
    finally:
        conn.close()


def _backup(db: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = backup_dir / f"league.db.bak-shop-economy-{stamp}"
    counter = 1
    while target.exists():
        target = backup_dir / f"league.db.bak-shop-economy-{stamp}-{counter}"
        counter += 1
    source = sqlite3.connect(db)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def _print_state(label: str, state: dict[str, Any]) -> None:
    print(f"{label}:")
    print(f"  game_config: {state['config']}")
    print(f"  ember: {state['ember']}")
    print(f"  marker: {state['marker']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/apply_shop_economy_update.py",
        description=(
            "Lower boost prices to 20/40, set the ember cooldown to 7 days, "
            "and back up the database first; idempotent"
        ),
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"league SQLite path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(DEFAULT_BACKUP_DIR),
        help=f"backup directory (default: {DEFAULT_BACKUP_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show current state without backing up or writing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = Path(args.db)
    if not db.exists():
        print(f"database not found: {db}", file=sys.stderr)
        return 1
    before = _state(db)
    _print_state("before", before)
    if args.dry_run:
        print("dry-run: no backup or changes written")
        return 0

    backup = _backup(db, Path(args.backup_dir))
    print(f"backup: {backup}")
    GameStore(db).initialize()
    after = _state(db)
    _print_state("after", after)
    if after == before:
        print("already applied: no values changed")
    else:
        print("applied: legacy boost/ember values updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
