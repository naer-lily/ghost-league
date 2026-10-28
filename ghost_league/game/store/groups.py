"""Group placement, membership, and weekly tier lookups."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from .. import calendar as cal
from ..rules import (
    GROUP_SIZE,
    TIERS,
    PlayerNotFound,
    balanced_group_sizes,
    next_tier,
)
from .core import SOURCE_CHANNEL, _row_to_dict

class GroupsMixin:
    """Balanced grouping and group membership queries."""

    def tier_for_player(self, player_id: str, week: date | datetime | str) -> str:
        week_iso = cal.iso_date(cal.week_start(week))
        with self._reader() as conn:
            return self._tier_for_player_with(conn, player_id, week_iso)

    def group_for_player(
        self, player_id: str, week: date | datetime | str
    ) -> dict[str, Any] | None:
        week_iso = cal.iso_date(cal.week_start(week))
        with self._reader() as conn:
            row = conn.execute(
                "SELECT g.* FROM groups g JOIN group_members gm ON gm.group_id = g.id "
                "WHERE g.week_start = ? AND gm.player_id = ? "
                "ORDER BY g.id DESC LIMIT 1",
                (week_iso, player_id),
            ).fetchone()
            return _row_to_dict(row)

    def ensure_group_for_player(
        self,
        player_id: str,
        week: date | datetime | str,
        *,
        tier: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Place one player in a current-week group without reusing opponents.

        This compatibility entry point delegates to :meth:`ensure_all_groups`,
        so a late human either joins an existing human group with room or gets
        a new group.  AI players are never copied into two groups in a week.
        """

        del tier
        week_date = cal.week_start(week)
        self.ensure_all_groups(week_date, now=now)
        group = self.group_for_player(player_id, week_date)
        if group is None:
            raise PlayerNotFound(f"no group for {player_id} {week_date.isoformat()}")
        result = dict(group)
        result["member_count"] = len(self.group_members(int(group["id"])))
        return result

    def _tier_for_player_with(
        self, conn: sqlite3.Connection, player_id: str, week_iso: str
    ) -> str:
        row = conn.execute(
            "SELECT tier, promoted, demoted FROM weekly_results "
            "WHERE player_id = ? AND week_start < ? "
            "ORDER BY week_start DESC LIMIT 1",
            (player_id, week_iso),
        ).fetchone()
        if row is None:
            return TIERS[0]
        return next_tier(
            str(row["tier"]),
            promoted=bool(row["promoted"]),
            demoted=bool(row["demoted"]),
        )

    def _load_week_groups_with(
        self, conn: sqlite3.Connection, week_iso: str
    ) -> list[dict[str, Any]]:
        groups = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM groups WHERE week_start = ? ORDER BY id",
                (week_iso,),
            )
        ]
        members: dict[int, list[dict[str, Any]]] = {}
        for row in conn.execute(
            "SELECT gm.*, p.kind, p.display_name FROM group_members gm "
            "JOIN players p ON p.id = gm.player_id "
            "JOIN groups g ON g.id = gm.group_id "
            "WHERE g.week_start = ? ORDER BY gm.group_id, gm.player_id",
            (week_iso,),
        ):
            members.setdefault(int(row["group_id"]), []).append(dict(row))
        for group in groups:
            group_members = members.get(int(group["id"]), [])
            group["members"] = group_members
            group["member_count"] = len(group_members)
        return groups

    def _insert_group_member_with(
        self,
        conn: sqlite3.Connection,
        *,
        week_iso: str,
        group_id: int,
        player_id: str,
        tier: str,
        is_human: bool,
        now: datetime,
    ) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO group_members "
            "(group_id, player_id, tier_at_start, is_human, joined_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                group_id,
                player_id,
                tier,
                1 if is_human else 0,
                cal.iso_ts(now),
            ),
        )
        self._ensure_score_row(conn, week_iso, player_id, group_id)

    def _create_group_with(
        self,
        conn: sqlite3.Connection,
        *,
        week_iso: str,
        tier: str,
        player_ids: list[str],
        human_ids: set[str],
        now: datetime,
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT COALESCE(MAX(group_no), 0) AS n FROM groups "
            "WHERE week_start = ? AND tier = ?",
            (week_iso, tier),
        ).fetchone()
        group_no = int(row["n"]) + 1
        cursor = conn.execute(
            "INSERT INTO groups (week_start, tier, group_no, created_at) "
            "VALUES (?, ?, ?, ?)",
            (week_iso, tier, group_no, cal.iso_ts(now)),
        )
        group_id = int(cursor.lastrowid)
        for player_id in player_ids:
            self._insert_group_member_with(
                conn,
                week_iso=week_iso,
                group_id=group_id,
                player_id=player_id,
                tier=tier,
                is_human=player_id in human_ids,
                now=now,
            )
        group = dict(
            conn.execute(
                "SELECT * FROM groups WHERE id = ?", (group_id,)
            ).fetchone()
        )
        group["members"] = []
        group["member_count"] = len(player_ids)
        return group

    def ensure_all_groups(
        self,
        week: date | datetime | str,
        *,
        now: datetime | None = None,
        spread_humans: bool = False,
    ) -> list[dict[str, Any]]:
        """Materialize every current-week balanced group at once.

        The group count is decided before seats are assigned: ``N`` eligible
        players form ``ceil(N / 15)`` groups with sizes ``base``/``base + 1``.
        A lone player is left unplaced instead of creating a one-person group.

        Humans are placed first and AI then fill every group to its balanced
        target.  By default humans are kept together until a group reaches its
        target size, which keeps their group full and avoids stranding them in
        a tail group.  ``spread_humans=True`` distributes them round-robin
        across the larger groups instead.  In both modes every group still
        gets its pre-computed balanced size.

        Repeating the call reconciles memberships in place.  Unchanged groups
        keep their ids; a player is never left in more than one group for the
        week.
        """

        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            self._ensure_week_with(conn, week_iso, "active")
            week_row = conn.execute(
                "SELECT * FROM weeks WHERE week_start = ?", (week_iso,)
            ).fetchone()
            if week_row is not None and week_row["status"] == "settled":
                return self._load_week_groups_with(conn, week_iso)

            # A player is eligible this week from exactly one of three
            # sources: local human identity, the legacy opponent plan, or the
            # Channel's current-week manifest.  Absence from the Channel
            # manifest is the only "not competing" signal; there is no
            # dormant/absent state to clean up.
            local_humans = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM players WHERE kind = 'human' AND is_active = 1 "
                    "AND source_kind != ? AND joined_week <= ? ORDER BY id",
                    (SOURCE_CHANNEL, week_iso),
                )
            ]
            legacy_ai = [
                dict(row)
                for row in conn.execute(
                    "SELECT p.* FROM players p "
                    "JOIN opponent_week_plan op ON op.player_id = p.id "
                    "AND op.week_start = ? "
                    "WHERE p.kind = 'ai' AND p.is_active = 1 "
                    "AND p.source_kind != ? "
                    "AND p.joined_week <= ? ORDER BY p.id",
                    (week_iso, SOURCE_CHANNEL, week_iso),
                )
            ]
            channel_players = [
                dict(row)
                for row in conn.execute(
                    "SELECT DISTINCT p.* FROM players p "
                    "JOIN channel_week_roster r ON r.player_id = p.id "
                    "WHERE r.week_start = ? AND p.is_active = 1 "
                    "AND p.joined_week <= ? ORDER BY p.id",
                    (week_iso, week_iso),
                )
            ]
            candidates: dict[str, dict[str, Any]] = {}
            for player in (*local_humans, *legacy_ai, *channel_players):
                candidates[str(player["id"])] = player
            humans = sorted(
                (player for player in candidates.values() if player["kind"] == "human"),
                key=lambda player: str(player["id"]),
            )
            ai_players = sorted(
                (player for player in candidates.values() if player["kind"] == "ai"),
                key=lambda player: str(player["id"]),
            )
            human_ids = {str(player["id"]) for player in humans}

            tier_cache: dict[str, str] = {}

            def tier_of(player_id: str) -> str:
                if player_id not in tier_cache:
                    tier_cache[player_id] = self._tier_for_player_with(
                        conn, player_id, week_iso
                    )
                return tier_cache[player_id]

            humans_by_tier: dict[str, list[str]] = {tier: [] for tier in TIERS}
            ai_by_tier: dict[str, list[str]] = {tier: [] for tier in TIERS}
            for player in humans:
                player_id = str(player["id"])
                humans_by_tier[tier_of(player_id)].append(player_id)
            for player in ai_players:
                player_id = str(player["id"])
                ai_by_tier[tier_of(player_id)].append(player_id)

            existing_groups = self._load_week_groups_with(conn, week_iso)
            existing_by_tier: dict[str, list[dict[str, Any]]] = {
                tier: [] for tier in TIERS
            }
            for group in existing_groups:
                existing_by_tier.setdefault(str(group["tier"]), []).append(group)
            for tier_groups in existing_by_tier.values():
                tier_groups.sort(key=lambda group: int(group["group_no"]))

            # Decide all target rosters before touching the database.  Humans
            # go first (together by default, or spread when requested), then
            # AI fill each group to its pre-computed balanced size.
            desired_by_tier: dict[str, list[list[str]]] = {}
            for tier in TIERS:
                tier_humans = sorted(humans_by_tier.get(tier, []))
                tier_ai = sorted(ai_by_tier.get(tier, []))
                sizes = balanced_group_sizes(len(tier_humans) + len(tier_ai))
                if not sizes:
                    desired_by_tier[tier] = []
                    continue
                rosters: list[list[str]] = [[] for _ in sizes]
                if spread_humans:
                    for index, player_id in enumerate(tier_humans):
                        rosters[index % len(sizes)].append(player_id)
                else:
                    remaining_humans = iter(tier_humans)
                    for roster, size in zip(rosters, sizes, strict=True):
                        while len(roster) < size:
                            try:
                                roster.append(next(remaining_humans))
                            except StopIteration:
                                break
                ai_iter = iter(tier_ai)
                for roster, size in zip(rosters, sizes, strict=True):
                    while len(roster) < size:
                        try:
                            roster.append(next(ai_iter))
                        except StopIteration:
                            break
                desired_by_tier[tier] = rosters

            expected_group_by_player: dict[str, int] = {}
            for tier in TIERS:
                desired = desired_by_tier[tier]
                existing = existing_by_tier.get(tier, [])

                # Drop surplus groups from a previous, larger roster.
                for group in existing[len(desired) :]:
                    conn.execute(
                        "DELETE FROM group_members WHERE group_id = ?",
                        (int(group["id"]),),
                    )
                    conn.execute(
                        "DELETE FROM groups WHERE id = ?", (int(group["id"]),)
                    )

                used_existing = existing[: len(desired)]
                next_group_no = max(
                    (int(group["group_no"]) for group in used_existing),
                    default=0,
                )
                for index, roster in enumerate(desired):
                    if index < len(used_existing):
                        group_id = int(used_existing[index]["id"])
                    else:
                        next_group_no += 1
                        cursor = conn.execute(
                            "INSERT INTO groups "
                            "(week_start, tier, group_no, created_at) "
                            "VALUES (?, ?, ?, ?)",
                            (week_iso, tier, next_group_no, cal.iso_ts(local_now)),
                        )
                        group_id = int(cursor.lastrowid)
                    for player_id in roster:
                        expected_group_by_player[player_id] = group_id

            # Remove memberships that are stale or in the wrong group before
            # inserting the new allocation.  This also enforces one group per
            # player for the week.
            for row in conn.execute(
                "SELECT gm.group_id, gm.player_id FROM group_members gm "
                "JOIN groups g ON g.id = gm.group_id "
                "WHERE g.week_start = ?",
                (week_iso,),
            ).fetchall():
                player_id = str(row["player_id"])
                if expected_group_by_player.get(player_id) != int(row["group_id"]):
                    conn.execute(
                        "DELETE FROM group_members "
                        "WHERE group_id = ? AND player_id = ?",
                        (int(row["group_id"]), player_id),
                    )

            for player_id, group_id in expected_group_by_player.items():
                self._insert_group_member_with(
                    conn,
                    week_iso=week_iso,
                    group_id=group_id,
                    player_id=player_id,
                    tier=tier_of(player_id),
                    is_human=player_id in human_ids,
                    now=local_now,
                )

            return self._load_week_groups_with(conn, week_iso)

    def create_group(
        self,
        week: date | datetime | str,
        *,
        tier: str,
        player_ids: list[str],
        group_no: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Create an explicit group with the given members.

        This is the deterministic building block used by tests and future
        matchmaking.  It still goes through one GameStore transaction and does
        not create any other week.
        """

        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        if tier not in TIERS:
            raise ValueError(f"unknown tier: {tier}")
        if not player_ids:
            raise ValueError("player_ids must be non-empty")
        if len(set(player_ids)) != len(player_ids):
            raise ValueError("player_ids must be unique")
        if len(player_ids) > GROUP_SIZE:
            raise ValueError(f"a group holds at most {GROUP_SIZE} players")
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            self._ensure_week_with(conn, week_iso, "active")
            if group_no is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(group_no), 0) AS n FROM groups "
                    "WHERE week_start = ? AND tier = ?",
                    (week_iso, tier),
                ).fetchone()
                group_no = int(row["n"]) + 1
            cursor = conn.execute(
                "INSERT INTO groups (week_start, tier, group_no, created_at) "
                "VALUES (?, ?, ?, ?)",
                (week_iso, tier, group_no, cal.iso_ts(local_now)),
            )
            group_id = int(cursor.lastrowid)
            for player_id in player_ids:
                player = self._get_player_with(conn, player_id)
                is_human = 1 if player["kind"] == "human" else 0
                conn.execute(
                    "INSERT OR IGNORE INTO group_members "
                    "(group_id, player_id, tier_at_start, is_human, joined_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        group_id,
                        player_id,
                        tier,
                        is_human,
                        cal.iso_ts(local_now),
                    ),
                )
                self._ensure_score_row(conn, week_iso, player_id, group_id)
            group = conn.execute(
                "SELECT * FROM groups WHERE id = ?", (group_id,)
            ).fetchone()
            result = dict(group)
            result["member_count"] = len(player_ids)
            return result

    def ensure_current_group(
        self,
        week: date | datetime | str,
        *,
        tier: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Compatibility wrapper for the full current-week grouping pass."""

        del tier
        return self.ensure_all_groups(week, now=now)

    def group_members(
        self, group_id: int
    ) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT gm.*, p.display_name, p.kind FROM group_members gm "
                "JOIN players p ON p.id = gm.player_id "
                "WHERE gm.group_id = ? ORDER BY gm.player_id",
                (group_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _ensure_score_row(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        player_id: str,
        group_id: int | None,
    ) -> None:
        conn.execute(
            "INSERT INTO weekly_scores (week_start, player_id, group_id) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(week_start, player_id) DO UPDATE SET "
            "group_id = COALESCE(excluded.group_id, weekly_scores.group_id)",
            (week_iso, player_id, group_id),
        )
