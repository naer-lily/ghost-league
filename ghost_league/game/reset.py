"""Safe, explicit epoch reset for ``league.db``.

This module never touches accounts, events, memberships or other live files.
The default path still refuses ``--confirm``; an operator resetting the live
``data/league/league.db`` must pass both ``--allow-live`` and
``--force-new-epoch`` after backing up ``data/``.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import calendar as cal
from .store import DEFAULT_DB_PATH, SCHEMA_VERSION, GameStore

_PROTECTED_PATHS = (
    Path("data/api/accounts.db"),
    Path("data/api/events.db"),
    Path("data/api/membership.json"),
    Path("data/league/state.json"),
    Path("data/league/weeks.json"),
)


def is_live_db(path: str | Path) -> bool:
    return Path(path).resolve() == DEFAULT_DB_PATH.resolve()


def _read_counts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "counts": {}, "active_epoch": None}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            names = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            counts: dict[str, int] = {}
            for table in sorted(names):
                if table.startswith("sqlite_"):
                    continue
                counts[table] = int(
                    conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                )
            epoch = None
            if "epochs" in names:
                row = conn.execute(
                    "SELECT * FROM epochs WHERE status = 'active' "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                epoch = dict(row) if row is not None else None
            return {"exists": True, "counts": counts, "active_epoch": epoch}
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return {
            "exists": True,
            "counts": {},
            "active_epoch": None,
            "error": str(exc),
        }


def dry_run(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    snapshot = _read_counts(target)
    return {
        "dry_run": True,
        "path": str(target),
        "live_path": is_live_db(target),
        "would_archive": snapshot,
        "would_create": {
            "schema_version": SCHEMA_VERSION,
            "epoch_reason": "reset:to-bronze",
            "tables": [
                "meta",
                "epochs",
                "players",
                "sources",
                "opponent_week_plan",
                "channel_players",
                "channel_events",
                "activity_events",
                "weeks",
                "groups",
                "group_members",
                "weekly_scores",
                "weekly_results",
                "checkins",
                "ember_ledger",
                "ember_balance",
                "streaks",
                "milestones",
                "catalog_titles",
                "catalog_items",
                "player_titles",
                "player_items",
                "loadouts",
            ],
        },
        "writes_performed": 0,
        "protected_paths_untouched": [str(path) for path in _PROTECTED_PATHS],
    }


def reset_database(
    path: str | Path,
    *,
    confirm: bool = False,
    force_new_epoch: bool = False,
    allow_live: bool = False,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    target = Path(path)
    if not confirm:
        raise ValueError("reset requires confirm=True")
    if is_live_db(target) and not (allow_live and force_new_epoch):
        raise ValueError(
            "refusing --confirm on the default live data/league/league.db; "
            "live reset requires BOTH --allow-live and --force-new-epoch "
            "after backing up data/"
        )
    local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
    previous = _read_counts(target)
    if previous["exists"] and previous["active_epoch"] and not force_new_epoch:
        return {
            "reset": False,
            "already_initialized": True,
            "path": str(target),
            "active_epoch": previous["active_epoch"],
            "counts": previous["counts"],
            "writes_performed": 0,
        }

    archived_path = None
    if target.exists():
        stamp = local_now.strftime("%Y%m%dT%H%M%S%f%z")
        archived_path = target.with_name(f"{target.name}.old-{stamp}")
        os.replace(target, archived_path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(target) + suffix)
            if sidecar.exists():
                os.replace(sidecar, Path(str(archived_path) + suffix))

    store = GameStore(
        target,
        epoch_reason="reset:to-bronze",
        epoch_started_at=local_now,
    )
    return {
        "reset": True,
        "already_initialized": False,
        "path": str(target),
        "archived_path": str(archived_path) if archived_path else None,
        "archived": previous,
        "created_epoch": store.active_epoch(),
        "counts": store.table_counts(),
        "integrity_check": store.integrity_check(),
        "writes_performed": 1,
        "protected_paths_untouched": [str(item) for item in _PROTECTED_PATHS],
    }
