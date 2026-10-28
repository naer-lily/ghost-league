"""Milestones, collection, loadouts, and deterministic AI taste."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from .. import calendar as cal
from ..progression import (
    CATALOG_ITEMS,
    CATALOG_TITLES,
    ITEM_BY_ID,
    ITEM_SLOTS,
    MILESTONE_CHAMPION,
    MILESTONE_FIRST_CHECKIN,
    MILESTONE_PROMOTED,
    MILESTONE_REWARDS,
    MILESTONE_STREAK_3,
    MILESTONE_STREAK_7,
    MILESTONE_TOP_3,
    milestone_payload,
)
from ..rules import CHECKIN_XP

PROGRESSION_START_META = "progression_started_at"
_EPOCH_FLOOR = "1970-01-01T00:00:00+08:00"
_UNSET = object()


def _taste_choice(player_id: str, slot: str, ids: list[str]) -> str | None:
    """Pick one unlocked id deterministically without reading live scores."""

    if not ids:
        return None
    digest = hashlib.sha256(f"taste:{player_id}:{slot}".encode("utf-8")).digest()
    return ids[int.from_bytes(digest[:8], "big") % len(ids)]


class ProgressionMixin:
    """Idempotent milestone awards, collection reads, and display loadouts."""

    # -- milestone evaluation -----------------------------------------
    def _progression_start_iso(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (PROGRESSION_START_META,)
        ).fetchone()
        return str(row["value"]) if row is not None else _EPOCH_FLOOR

    def _grant_milestone_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        milestone_id: str,
        *,
        week_start: str,
        now: datetime,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        awarded_at = cal.iso_ts(now)
        cursor = conn.execute(
            "INSERT OR IGNORE INTO milestones "
            "(player_id, milestone_id, awarded_at, week_start, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                player_id,
                milestone_id,
                awarded_at,
                week_start,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        rewards = MILESTONE_REWARDS[milestone_id]
        for title_id in rewards["titles"]:
            conn.execute(
                "INSERT OR IGNORE INTO player_titles "
                "(player_id, title_id, awarded_at, season_id) "
                "VALUES (?, ?, ?, NULL)",
                (player_id, title_id, awarded_at),
            )
        for item_id in rewards["items"]:
            conn.execute(
                "INSERT OR IGNORE INTO player_items "
                "(player_id, item_id, awarded_at, season_id) "
                "VALUES (?, ?, ?, NULL)",
                (player_id, item_id, awarded_at),
            )
        return {
            "player_id": player_id,
            "milestone_id": milestone_id,
            "new": cursor.rowcount > 0,
            "titles": list(rewards["titles"]),
            "items": list(rewards["items"]),
        }

    def _evaluate_daily_milestones_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        *,
        now: datetime,
    ) -> list[dict[str, Any]]:
        start_iso = self._progression_start_iso(conn)
        try:
            start_day = cal.parse_datetime(start_iso).date().isoformat()
        except ValueError:
            start_day = _EPOCH_FLOOR[:10]
        rows = conn.execute(
            "SELECT date, source, xp, "
            "COALESCE(repaired_at, checked_at) AS awarded_at "
            "FROM checkins WHERE player_id = ? AND date >= ? "
            "AND COALESCE(repaired_at, checked_at) >= ? ORDER BY date",
            (player_id, start_day, start_iso),
        ).fetchall()
        if not rows:
            return []

        awards: list[dict[str, Any]] = []
        first = next(
            (
                row
                for row in rows
                if str(row["source"]) == "verified"
                and int(row["xp"]) >= CHECKIN_XP
            ),
            None,
        )
        if first is not None:
            day = date.fromisoformat(str(first["date"]))
            awards.append(
                self._grant_milestone_with(
                    conn,
                    player_id,
                    MILESTONE_FIRST_CHECKIN,
                    week_start=cal.week_start(day).isoformat(),
                    now=now,
                    payload=milestone_payload(
                        MILESTONE_FIRST_CHECKIN,
                        week_start=cal.week_start(day).isoformat(),
                        day=day.isoformat(),
                        source=str(first["source"]),
                    ),
                )
            )

        runs: list[list[date]] = []
        current: list[date] = []
        previous: date | None = None
        for row in rows:
            row_day = date.fromisoformat(str(row["date"]))
            if previous is not None and row_day == previous + timedelta(days=1):
                current.append(row_day)
            else:
                if current:
                    runs.append(current)
                current = [row_day]
            previous = row_day
        if current:
            runs.append(current)

        for milestone_id, length in (
            (MILESTONE_STREAK_3, 3),
            (MILESTONE_STREAK_7, 7),
        ):
            completed = next(
                (run for run in runs if len(run) >= length),
                None,
            )
            if completed is None:
                continue
            day = completed[length - 1]
            week_iso = cal.week_start(day).isoformat()
            awards.append(
                self._grant_milestone_with(
                    conn,
                    player_id,
                    milestone_id,
                    week_start=week_iso,
                    now=now,
                    payload=milestone_payload(
                        milestone_id,
                        week_start=week_iso,
                        day=day.isoformat(),
                        streak=length,
                    ),
                )
            )
        return awards

    def _apply_daily_progression_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        *,
        now: datetime,
    ) -> list[dict[str, Any]]:
        awards = self._evaluate_daily_milestones_with(
            conn, player_id, now=now
        )
        if any(award["new"] for award in awards):
            self._refresh_ai_loadout_with(conn, player_id, now=now)
        return awards

    def _apply_weekly_progression_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        *,
        now: datetime,
    ) -> list[dict[str, Any]]:
        awards = self._evaluate_weekly_milestones_with(
            conn, week_iso, now=now
        )
        player_ids = {
            str(row["player_id"])
            for row in conn.execute(
                "SELECT player_id FROM weekly_results WHERE week_start = ?",
                (week_iso,),
            )
        }
        for player_id in sorted(player_ids):
            self._refresh_ai_loadout_with(conn, player_id, now=now)
        return awards

    def _evaluate_weekly_milestones_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        *,
        now: datetime,
    ) -> list[dict[str, Any]]:
        epoch = conn.execute(
            "SELECT id FROM epochs WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if epoch is None:
            return []
        rows = conn.execute(
            "SELECT wr.* FROM weekly_results wr "
            "JOIN weeks w ON w.week_start = wr.week_start "
            "WHERE wr.week_start = ? AND w.epoch_id = ? "
            "ORDER BY wr.group_id, wr.rank",
            (week_iso, int(epoch["id"])),
        ).fetchall()
        awards: list[dict[str, Any]] = []
        for row in rows:
            player_id = str(row["player_id"])
            rank = int(row["rank"])
            if rank <= 3:
                awards.append(
                    self._grant_milestone_with(
                        conn,
                        player_id,
                        MILESTONE_TOP_3,
                        week_start=week_iso,
                        now=now,
                        payload=milestone_payload(
                            MILESTONE_TOP_3,
                            week_start=week_iso,
                            rank=rank,
                        ),
                    )
                )
            if rank == 1:
                awards.append(
                    self._grant_milestone_with(
                        conn,
                        player_id,
                        MILESTONE_CHAMPION,
                        week_start=week_iso,
                        now=now,
                        payload=milestone_payload(
                            MILESTONE_CHAMPION,
                            week_start=week_iso,
                            rank=rank,
                        ),
                    )
                )
            if bool(row["promoted"]):
                awards.append(
                    self._grant_milestone_with(
                        conn,
                        player_id,
                        MILESTONE_PROMOTED,
                        week_start=week_iso,
                        now=now,
                        payload=milestone_payload(
                            MILESTONE_PROMOTED,
                            week_start=week_iso,
                            rank=rank,
                            promoted=True,
                        ),
                    )
                )
        return awards

    def _refresh_ai_loadout_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        *,
        now: datetime,
    ) -> dict[str, Any] | None:
        player = self._get_player_with(conn, player_id)
        if str(player["kind"]) != "ai":
            return None
        title_rows = conn.execute(
            "SELECT pt.title_id FROM player_titles pt "
            "JOIN catalog_titles ct ON ct.id = pt.title_id "
            "WHERE pt.player_id = ? ORDER BY pt.title_id",
            (player_id,),
        ).fetchall()
        titles = [str(row["title_id"]) for row in title_rows]
        item_rows = conn.execute(
            "SELECT pi.item_id, ci.slot FROM player_items pi "
            "JOIN catalog_items ci ON ci.id = pi.item_id "
            "WHERE pi.player_id = ? ORDER BY pi.item_id",
            (player_id,),
        ).fetchall()
        by_slot: dict[str, list[str]] = {slot: [] for slot in ITEM_SLOTS}
        for row in item_rows:
            by_slot.setdefault(str(row["slot"]), []).append(str(row["item_id"]))
        chosen_title = _taste_choice(player_id, "title", titles)
        chosen = {
            slot: _taste_choice(player_id, slot, by_slot.get(slot, []))
            for slot in ITEM_SLOTS
        }
        conn.execute(
            "INSERT INTO loadouts "
            "(player_id, title_id, frame_id, backdrop_id, badge_accent_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(player_id) DO UPDATE SET "
            "title_id = excluded.title_id, frame_id = excluded.frame_id, "
            "backdrop_id = excluded.backdrop_id, "
            "badge_accent_id = excluded.badge_accent_id, "
            "updated_at = excluded.updated_at",
            (
                player_id,
                chosen_title,
                chosen["frame"],
                chosen["backdrop"],
                chosen["badge_accent"],
                cal.iso_ts(now),
            ),
        )
        return self._loadout_view_with(conn, player_id)

    def refresh_ai_loadout(self, player_id: str) -> dict[str, Any] | None:
        now = cal.now_local()
        with self.transaction() as conn:
            return self._refresh_ai_loadout_with(conn, player_id, now=now)

    # -- read models ---------------------------------------------------
    def awarded_milestones(self, player_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM milestones WHERE player_id = ? "
                "ORDER BY awarded_at, milestone_id",
                (player_id,),
            ).fetchall()
            output: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                try:
                    item["payload"] = json.loads(str(row["payload_json"]))
                except (TypeError, ValueError):
                    item["payload"] = {}
                output.append(item)
            return output

    def _loadout_view_with(
        self, conn: sqlite3.Connection, player_id: str
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT l.*, ct.name AS title_name, cf.name AS frame_name, "
            "cb.name AS backdrop_name, ca.name AS badge_accent_name "
            "FROM loadouts l "
            "LEFT JOIN catalog_titles ct ON ct.id = l.title_id "
            "LEFT JOIN catalog_items cf ON cf.id = l.frame_id "
            "LEFT JOIN catalog_items cb ON cb.id = l.backdrop_id "
            "LEFT JOIN catalog_items ca ON ca.id = l.badge_accent_id "
            "WHERE l.player_id = ?",
            (player_id,),
        ).fetchone()
        if row is None:
            return {
                "player_id": player_id,
                "title_id": None,
                "title": None,
                "frame_id": None,
                "frame": None,
                "backdrop_id": None,
                "backdrop": None,
                "badge_accent_id": None,
                "badge_accent": None,
                "updated_at": None,
            }
        return {
            "player_id": player_id,
            "title_id": row["title_id"],
            "title": row["title_name"],
            "frame_id": row["frame_id"],
            "frame": row["frame_name"],
            "backdrop_id": row["backdrop_id"],
            "backdrop": row["backdrop_name"],
            "badge_accent_id": row["badge_accent_id"],
            "badge_accent": row["badge_accent_name"],
            "updated_at": row["updated_at"],
        }

    def loadout_view(self, player_id: str) -> dict[str, Any]:
        with self._reader() as conn:
            return self._loadout_view_with(conn, player_id)

    get_loadout = loadout_view

    def collection(self, player_id: str) -> dict[str, Any]:
        with self._reader() as conn:
            self._get_player_with(conn, player_id)
            title_rows = conn.execute(
                "SELECT pt.title_id, pt.awarded_at, pt.season_id, "
                "ct.name, ct.description FROM player_titles pt "
                "JOIN catalog_titles ct ON ct.id = pt.title_id "
                "WHERE pt.player_id = ? ORDER BY pt.awarded_at, pt.title_id",
                (player_id,),
            ).fetchall()
            item_rows = conn.execute(
                "SELECT pi.item_id, pi.awarded_at, pi.season_id, "
                "ci.name, ci.slot, ci.description FROM player_items pi "
                "JOIN catalog_items ci ON ci.id = pi.item_id "
                "WHERE pi.player_id = ? ORDER BY ci.slot, pi.awarded_at, pi.item_id",
                (player_id,),
            ).fetchall()
            loadout = self._loadout_view_with(conn, player_id)
        equipped_title = loadout["title_id"]
        equipped_items = {
            loadout["frame_id"],
            loadout["backdrop_id"],
            loadout["badge_accent_id"],
        }
        return {
            "player_id": player_id,
            "titles": [
                {
                    "id": str(row["title_id"]),
                    "name": str(row["name"]),
                    "description": str(row["description"]),
                    "awarded_at": str(row["awarded_at"]),
                    "season_id": row["season_id"],
                    "equipped": str(row["title_id"]) == equipped_title,
                }
                for row in title_rows
            ],
            "items": [
                {
                    "id": str(row["item_id"]),
                    "name": str(row["name"]),
                    "slot": str(row["slot"]),
                    "description": str(row["description"]),
                    "awarded_at": str(row["awarded_at"]),
                    "season_id": row["season_id"],
                    "equipped": str(row["item_id"]) in equipped_items,
                }
                for row in item_rows
            ],
            "equipped": {
                "title_id": loadout["title_id"],
                "frame_id": loadout["frame_id"],
                "backdrop_id": loadout["backdrop_id"],
                "badge_accent_id": loadout["badge_accent_id"],
                "updated_at": loadout["updated_at"],
            },
        }

    get_collection = collection

    # -- equipment -----------------------------------------------------
    def update_loadout(
        self,
        player_id: str,
        *,
        title_id: str | None | object = _UNSET,
        frame_id: str | None | object = _UNSET,
        backdrop_id: str | None | object = _UNSET,
        badge_accent_id: str | None | object = _UNSET,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            self._get_player_with(conn, player_id)
            current = conn.execute(
                "SELECT * FROM loadouts WHERE player_id = ?", (player_id,)
            ).fetchone()
            values: dict[str, Any] = {
                "title_id": current["title_id"] if current is not None else None,
                "frame_id": current["frame_id"] if current is not None else None,
                "backdrop_id": current["backdrop_id"] if current is not None else None,
                "badge_accent_id": (
                    current["badge_accent_id"] if current is not None else None
                ),
            }
            if title_id is not _UNSET:
                if title_id is not None:
                    unlocked = conn.execute(
                        "SELECT 1 FROM player_titles "
                        "WHERE player_id = ? AND title_id = ?",
                        (player_id, str(title_id)),
                    ).fetchone()
                    if unlocked is None:
                        raise ValueError(f"title not unlocked: {title_id}")
                values["title_id"] = title_id
            for field, slot in (
                ("frame_id", "frame"),
                ("backdrop_id", "backdrop"),
                ("badge_accent_id", "badge_accent"),
            ):
                value = {
                    "frame_id": frame_id,
                    "backdrop_id": backdrop_id,
                    "badge_accent_id": badge_accent_id,
                }[field]
                if value is _UNSET:
                    continue
                if value is not None:
                    unlocked = conn.execute(
                        "SELECT ci.slot FROM player_items pi "
                        "JOIN catalog_items ci ON ci.id = pi.item_id "
                        "WHERE pi.player_id = ? AND pi.item_id = ?",
                        (player_id, str(value)),
                    ).fetchone()
                    if unlocked is None or str(unlocked["slot"]) != slot:
                        raise ValueError(f"item not unlocked: {value}")
                values[field] = value
            conn.execute(
                "INSERT INTO loadouts "
                "(player_id, title_id, frame_id, backdrop_id, badge_accent_id, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(player_id) DO UPDATE SET "
                "title_id = excluded.title_id, frame_id = excluded.frame_id, "
                "backdrop_id = excluded.backdrop_id, "
                "badge_accent_id = excluded.badge_accent_id, "
                "updated_at = excluded.updated_at",
                (
                    player_id,
                    values["title_id"],
                    values["frame_id"],
                    values["backdrop_id"],
                    values["badge_accent_id"],
                    cal.iso_ts(local_now),
                ),
            )
            return self._loadout_view_with(conn, player_id)


__all__ = [
    "CATALOG_ITEMS",
    "CATALOG_TITLES",
    "ITEM_BY_ID",
    "PROGRESSION_START_META",
    "ProgressionMixin",
]
