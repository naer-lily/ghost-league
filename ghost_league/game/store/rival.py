"""Weekly rival selection, deterministic auto matching, and settlement.

Rivals are a per-week, per-human pairing across groups.  They never feed the
group ranking: the week is still settled by :meth:`SettlementMixin.settle_week`,
which calls into this module so a single transaction owns the week, the rival
result, and any diamond rewards.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from .. import calendar as cal
from ..rival import (
    AUTO_POWER_BAND_MAX,
    AUTO_POWER_BAND_MIN,
    DAILY_MAX_PAID_STAKE,
    FREE_BET_STAKE,
    GROUP_TARGET_RANK,
    MAX_PAID_STAKE,
    MIN_PAID_STAKE,
    RivalNotFound,
    RivalSelectionRejected,
    RivalWindowClosed,
    auto_select_at,
    daily_bet_locks_at,
    daily_bet_settles_at,
    daily_distribution_parameters,
    daily_power_distribution,
    daily_target_options,
    odds_reference,
    projected_week_xp,
    rival_outcome,
    rival_reward,
    selection_window_open,
    target_options,
    target_upper_bound,
    week_lock_display,
)
from ..rules import PlayerNotFound
from .core import _row_to_dict

_GROUP_VIEW_SQL = (
    "SELECT gm.player_id AS player_id, g.id AS group_id, "
    "g.group_no AS group_no, g.tier AS tier "
    "FROM group_members gm JOIN groups g ON g.id = gm.group_id "
    "WHERE g.week_start = ?"
)


class RivalMixin:
    """Rival assignments, candidates, automatic matching, and results."""

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _public_rival_player(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if not key.startswith("_")
        }

    def _rival_player_row_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        player_id: str,
        day_iso: str,
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT p.id AS user_id, p.display_name, p.power, p.kind, "
            "COALESCE(ws.xp, 0) AS week_xp, "
            "COALESCE(ws.seconds, 0) AS week_seconds, "
            "grp.group_id AS group_id, grp.group_no AS group_no, "
            "grp.tier AS tier, COALESCE(ci.xp, 0) AS today_xp "
            "FROM players p "
            "LEFT JOIN weekly_scores ws "
            "ON ws.week_start = ? AND ws.player_id = p.id "
            f"LEFT JOIN ({_GROUP_VIEW_SQL}) grp ON grp.player_id = p.id "
            "LEFT JOIN checkins ci "
            "ON ci.player_id = p.id AND ci.date = ? "
            "WHERE p.id = ?",
            (week_iso, week_iso, day_iso, player_id),
        ).fetchone()
        if row is None:
            raise PlayerNotFound(player_id)
        tier = row["tier"]
        if tier is None:
            tier = self._tier_for_player_with(  # type: ignore[attr-defined]
                conn, player_id, week_iso
            )
        return {
            "user_id": str(row["user_id"]),
            "display_name": str(row["display_name"]),
            "group_no": (
                int(row["group_no"]) if row["group_no"] is not None else None
            ),
            "tier": str(tier),
            "power": int(row["power"]) if row["power"] is not None else 0,
            "week_xp": int(row["week_xp"]),
            "today_xp": int(row["today_xp"]),
            "_group_id": (
                int(row["group_id"]) if row["group_id"] is not None else None
            ),
            "_kind": str(row["kind"]),
        }

    def _candidate_rows_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        player_id: str,
        my_group_id: int | None,
        day_iso: str,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT p.id AS user_id, p.display_name, p.power, p.kind, "
            "ws.xp AS week_xp, ws.seconds AS week_seconds, "
            "grp.group_id AS group_id, grp.group_no AS group_no, "
            "grp.tier AS tier, COALESCE(ci.xp, 0) AS today_xp "
            "FROM players p "
            "JOIN weekly_scores ws "
            "ON ws.week_start = ? AND ws.player_id = p.id "
            f"LEFT JOIN ({_GROUP_VIEW_SQL}) grp ON grp.player_id = p.id "
            "LEFT JOIN checkins ci "
            "ON ci.player_id = p.id AND ci.date = ? "
            "WHERE p.is_active = 1 AND p.id != ? "
            "ORDER BY p.id",
            (week_iso, week_iso, day_iso, player_id),
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        if my_group_id is None:
            return candidates
        seen: set[str] = set()
        for row in rows:
            user_id = str(row["user_id"])
            if user_id in seen:
                continue
            group_id = (
                int(row["group_id"]) if row["group_id"] is not None else None
            )
            if group_id is None or group_id == my_group_id:
                continue
            seen.add(user_id)
            tier = row["tier"]
            if tier is None:
                tier = self._tier_for_player_with(  # type: ignore[attr-defined]
                    conn, user_id, week_iso
                )
            candidates.append(
                {
                    "user_id": user_id,
                    "display_name": str(row["display_name"]),
                    "group_no": (
                        int(row["group_no"])
                        if row["group_no"] is not None
                        else None
                    ),
                    "tier": str(tier),
                    "power": (
                        int(row["power"]) if row["power"] is not None else 0
                    ),
                    "week_xp": int(row["week_xp"]),
                    "today_xp": int(row["today_xp"]),
                    "_group_id": group_id,
                    "_kind": str(row["kind"]),
                }
            )
        my_power = self._my_power_with(
            conn, week_iso, player_id, day_iso
        )
        candidates.sort(
            key=lambda item: (
                abs(int(item["power"]) - my_power),
                -int(item["power"]),
                str(item["user_id"]),
            )
        )
        return candidates

    def _my_power_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        player_id: str,
        day_iso: str,
    ) -> int:
        row = self._rival_player_row_with(
            conn, week_iso, player_id, day_iso
        )
        return int(row["power"])

    @staticmethod
    def _assignment_with(
        conn: sqlite3.Connection, week_iso: str, player_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM rival_assignments "
            "WHERE week_start = ? AND player_id = ?",
            (week_iso, player_id),
        ).fetchone()
        return _row_to_dict(row)

    @staticmethod
    def _result_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        return {
            "week_start": str(data["week_start"]),
            "rival_id": str(data["rival_id"]),
            "my_xp": int(data["my_xp"]),
            "rival_xp": int(data["rival_xp"]),
            "outcome": str(data["outcome"]),
            "reward_diamonds": int(data["reward_diamonds"]),
            "settled_at": str(data["settled_at"]),
        }

    @staticmethod
    def _bet_windows(now: datetime) -> dict[str, str]:
        week_date = cal.week_start(now)
        day = now.date()
        return {
            "weekly_locks_at": cal.iso_ts(week_lock_display(week_date)),
            "daily_locks_at": cal.iso_ts(daily_bet_locks_at(day)),
            "daily_settles_at": cal.iso_ts(daily_bet_settles_at(day)),
        }

    @staticmethod
    def _daily_distribution_with(
        my_power: int,
        rival_power: int,
    ) -> dict[str, Any]:
        """Return the day's power-priced distribution, parameters, and tiers.

        Daily pricing is deliberately stateless: both means are the players'
        powers and both spreads scale from those powers.  No check-in history
        and no power-band prior is read.
        """

        mu_me, sd_me, mu_rival, sd_rival = daily_power_distribution(
            my_power, rival_power
        )
        mu_me = round(mu_me, 2)
        sd_me = round(sd_me, 2)
        mu_rival = round(mu_rival, 2)
        sd_rival = round(sd_rival, 2)
        mu_diff, sigma_diff = daily_distribution_parameters(
            mu_me, sd_me, mu_rival, sd_rival
        )
        mu_diff = round(mu_diff, 2)
        sigma_diff = round(sigma_diff, 2)
        options = daily_target_options(mu_me, sd_me, mu_rival, sd_rival)
        return {
            "daily_mu_me": mu_me,
            "daily_sd_me": sd_me,
            "daily_mu_rival": mu_rival,
            "daily_sd_rival": sd_rival,
            "daily_mu_diff": mu_diff,
            "daily_sigma_diff": sigma_diff,
            "daily_target_margins": [
                int(option["margin"]) for option in options
            ],
        }

    def _projection_with(
        self,
        conn: sqlite3.Connection,
        me: dict[str, Any],
        rival: dict[str, Any] | None,
        day_iso: str,
    ) -> dict[str, Any] | None:
        """Estimate the lines shown on the betting screen.

        The weekly line still uses the settled-week percentile.  The daily line
        is pure power: each player's expected daily XP equals their power and
        the spread is proportional to it, with a floor.  Settlement keeps using
        the actual final XP, never this projection.
        """

        if rival is None:
            return None
        settled = conn.execute(
            "SELECT week_start FROM weeks WHERE status = 'settled' "
            "ORDER BY week_start DESC LIMIT 1"
        ).fetchone()
        settled_xps: list[int] = []
        if settled is not None:
            settled_xps = [
                int(row["xp"])
                for row in conn.execute(
                    "SELECT xp FROM weekly_scores WHERE week_start = ? "
                    "ORDER BY player_id",
                    (str(settled["week_start"]),),
                )
            ]
        week_estimate = projected_week_xp(
            int(rival["power"]),
            settled_xps,
            int(rival["week_xp"]),
        )
        daily = self._daily_distribution_with(
            int(me.get("power") or 0),
            int(rival["power"]),
        )
        return {
            "rival_week_estimate": week_estimate,
            "weekly_target_max": target_upper_bound(
                "weekly", rival_week_estimate=week_estimate
            ),
            **daily,
        }

    @staticmethod
    def _bet_options_with(
        me: dict[str, Any],
        rival: dict[str, Any] | None,
        projection: dict[str, Any] | None,
        group_markets: list[dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any] | None]:
        """Build render-ready target/stake options for the betting screen.

        Weekly and daily options only exist once a rival is assigned.  Group
        options only exist once the caller has a group; every group market
        (``top3`` / ``promote`` / ``no_demote``) carries its server-computed
        odds and eligibility.
        """

        weekly: dict[str, Any] | None = None
        daily: dict[str, Any] | None = None
        if rival is not None and projection is not None:
            my_power = int(me["power"])
            rival_power = int(rival["power"])
            week_estimate = int(projection["rival_week_estimate"])
            daily_options = daily_target_options(
                float(projection["daily_mu_me"]),
                float(projection["daily_sd_me"]),
                float(projection["daily_mu_rival"]),
                float(projection["daily_sd_rival"]),
            )
            daily_margins = [
                int(option["margin"]) for option in daily_options
            ]
            common = {
                "min_paid_stake": MIN_PAID_STAKE,
                "free_stake": FREE_BET_STAKE,
            }
            weekly = {
                **common,
                "max_paid_stake": MAX_PAID_STAKE,
                "reference": odds_reference(
                    "weekly", rival_week_estimate=week_estimate
                ),
                "min_target_margin": 0,
                "max_target_margin": target_upper_bound(
                    "weekly", rival_week_estimate=week_estimate
                ),
                "target_options": target_options(
                    "weekly",
                    week_estimate,
                    my_power=my_power,
                    rival_power=rival_power,
                ),
            }
            daily = {
                **common,
                "max_paid_stake": DAILY_MAX_PAID_STAKE,
                "reference": int(
                    round(float(projection["daily_mu_diff"]))
                ),
                "min_target_margin": min(daily_margins),
                "max_target_margin": max(daily_margins),
                "target_options": daily_options,
            }
        markets = list(group_markets or [])
        top3 = next(
            (entry for entry in markets if entry.get("market") == "top3"),
            None,
        )
        group = (
            {
                "target_rank": GROUP_TARGET_RANK,
                "target_margin": 0,
                "min_paid_stake": MIN_PAID_STAKE,
                "max_paid_stake": MAX_PAID_STAKE,
                "free_stake": FREE_BET_STAKE,
                "odds": top3["odds"] if top3 is not None else None,
                "markets": markets,
            }
            if me.get("_group_id") is not None
            else None
        )
        return {"weekly": weekly, "daily": daily, "group": group}

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------
    def rival_candidates(
        self,
        player_id: str,
        now: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """Return eligible rivals sorted by how close their power is to mine.

        Same-group players, the caller, inactive players, and players without a
        current-week ``weekly_scores`` row are excluded.
        """

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        week_iso = cal.iso_date(cal.week_start(local_now))
        day_iso = local_now.date().isoformat()
        with self._reader() as conn:
            me = self._rival_player_row_with(
                conn, week_iso, player_id, day_iso
            )
            candidates = self._candidate_rows_with(
                conn,
                week_iso,
                player_id,
                me["_group_id"],
                day_iso,
            )
        return [
            self._public_rival_player(candidate) for candidate in candidates
        ]

    def rival_state(
        self,
        player_id: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Return the caller's current-week rival, bets, and last result."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        week_date = cal.week_start(local_now)
        week_iso = week_date.isoformat()
        day_iso = local_now.date().isoformat()
        with self._reader() as conn:
            me = self._rival_player_row_with(
                conn, week_iso, player_id, day_iso
            )
            assignment = self._assignment_with(conn, week_iso, player_id)
            rival = (
                self._rival_player_row_with(
                    conn, week_iso, str(assignment["rival_id"]), day_iso
                )
                if assignment is not None
                else None
            )
            result_row = conn.execute(
                "SELECT * FROM rival_results WHERE player_id = ? "
                "ORDER BY week_start DESC LIMIT 1",
                (player_id,),
            ).fetchone()
            projection = self._projection_with(
                conn, me, rival, day_iso
            )

        locked = bool(assignment and assignment["locked_at"])
        selection_open = selection_window_open(local_now, week_date) and not locked
        selection = {
            "open": selection_open,
            "locks_at": cal.iso_ts(week_lock_display(week_date)),
            "auto_select_at": cal.iso_ts(auto_select_at(week_date)),
            "mode": (
                str(assignment["selection_mode"])
                if assignment is not None
                else None
            ),
        }
        bets = self.bets_for(player_id, now=local_now)
        return {
            "week_start": week_iso,
            "selection": selection,
            "me": self._public_rival_player(me),
            "rival": (
                self._public_rival_player(rival)
                if rival is not None
                else None
            ),
            "result": (
                self._result_payload(result_row)
                if result_row is not None
                else None
            ),
            "bets": bets,
            "bet_options": self._bet_options_with(
                me, rival, projection, bets.get("groups")
            ),
            "projection": projection,
            "bet_windows": self._bet_windows(local_now),
        }

    # ------------------------------------------------------------------
    # Manual selection
    # ------------------------------------------------------------------
    def select_rival(
        self,
        player_id: str,
        rival_id: str,
        now: datetime | str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Choose or replace this week's rival before the Monday lock."""

        if not isinstance(rival_id, str) or not rival_id.strip():
            raise RivalSelectionRejected("invalid_rival", "请选择一个有效的宿敌")
        if request_id is not None and not str(request_id).strip():
            raise ValueError("request_id must be non-empty")
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        week_date = cal.week_start(local_now)
        week_iso = week_date.isoformat()
        day_iso = local_now.date().isoformat()

        with self.transaction() as conn:
            me = self._rival_player_row_with(
                conn, week_iso, player_id, day_iso
            )
            if me["_kind"] != "human":
                raise RivalSelectionRejected(
                    "human_only", "只有真人可以选择宿敌"
                )
            if rival_id == player_id:
                raise RivalSelectionRejected(
                    "cannot_select_self", "不能选择自己"
                )
            if not selection_window_open(local_now, week_date):
                raise RivalWindowClosed()
            existing = self._assignment_with(conn, week_iso, player_id)
            if existing is not None and existing["locked_at"]:
                raise RivalWindowClosed()
            candidates = self._candidate_rows_with(
                conn,
                week_iso,
                player_id,
                me["_group_id"],
                day_iso,
            )
            target = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate["user_id"] == rival_id
                ),
                None,
            )
            if target is None:
                raise RivalNotFound()

            self._ensure_week_with(conn, week_iso, "active")
            now_iso = cal.iso_ts(local_now)
            created = (
                cal.iso_ts(cal.parse_datetime(str(existing["created_at"])))
                if existing is not None
                else now_iso
            )
            conn.execute(
                "INSERT INTO rival_assignments "
                "(week_start, player_id, rival_id, selection_mode, "
                "selected_at, locked_at, created_at, updated_at) "
                "VALUES (?, ?, ?, 'manual', ?, NULL, ?, ?) "
                "ON CONFLICT(week_start, player_id) DO UPDATE SET "
                "rival_id = excluded.rival_id, "
                "selection_mode = 'manual', "
                "selected_at = excluded.selected_at, "
                "locked_at = NULL, "
                "updated_at = excluded.updated_at",
                (
                    week_iso,
                    player_id,
                    rival_id,
                    now_iso,
                    created,
                    now_iso,
                ),
            )
            assignment = self._assignment_with(conn, week_iso, player_id)
        return {
            "week_start": week_iso,
            "assignment": assignment,
            "rival": self._public_rival_player(target),
        }

    # ------------------------------------------------------------------
    # Automatic selection
    # ------------------------------------------------------------------
    def auto_assign_rivals(
        self,
        week: date | datetime | str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Match every human without a rival, starting Tuesday 00:00.

        The pass is deterministic: candidate preference is (power band,
        avoid last week's rival, nearest gap, player id).  A player with no
        eligible candidate is left without a rival rather than paired against
        a fabricated opponent.
        """

        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        auto_at = auto_select_at(week_date)
        if local_now < auto_at:
            return {
                "week_start": week_iso,
                "status": "skipped",
                "reason": "auto_select_not_open",
                "assigned": 0,
                "locked": 0,
                "no_candidate": 0,
                "already": 0,
            }

        day_iso = local_now.date().isoformat()
        auto_iso = cal.iso_ts(auto_at)
        now_iso = cal.iso_ts(local_now)
        assigned = 0
        locked = 0
        no_candidate = 0
        already = 0

        with self.transaction() as conn:
            week_row = conn.execute(
                "SELECT status FROM weeks WHERE week_start = ?", (week_iso,)
            ).fetchone()
            if week_row is not None and week_row["status"] == "settled":
                return {
                    "week_start": week_iso,
                    "status": "skipped",
                    "reason": "week_already_settled",
                    "assigned": 0,
                    "locked": 0,
                    "no_candidate": 0,
                    "already": 0,
                }
            # Manual picks stop being editable once Tuesday starts.
            cursor = conn.execute(
                "UPDATE rival_assignments "
                "SET locked_at = ?, updated_at = ? "
                "WHERE week_start = ? AND locked_at IS NULL",
                (auto_iso, now_iso, week_iso),
            )
            locked = max(0, int(cursor.rowcount))

            previous_week = cal.iso_date(cal.previous_week_start(week_date))
            previous = {
                str(row["player_id"]): str(row["rival_id"])
                for row in conn.execute(
                    "SELECT player_id, rival_id FROM rival_assignments "
                    "WHERE week_start = ?",
                    (previous_week,),
                )
            }

            humans = conn.execute(
                "SELECT id FROM players WHERE kind = 'human' "
                "AND is_active = 1 ORDER BY id"
            ).fetchall()
            for human in humans:
                player_id = str(human["id"])
                if self._assignment_with(conn, week_iso, player_id) is not None:
                    already += 1
                    continue
                me = self._rival_player_row_with(
                    conn, week_iso, player_id, day_iso
                )
                candidates = self._candidate_rows_with(
                    conn,
                    week_iso,
                    player_id,
                    me["_group_id"],
                    day_iso,
                )
                if not candidates:
                    no_candidate += 1
                    continue
                previous_rival = previous.get(player_id)
                my_power = int(me["power"])

                def preference(
                    candidate: dict[str, Any],
                    *,
                    previous_rival: str | None = previous_rival,
                    my_power: int = my_power,
                ) -> tuple[int, int, int, int, str]:
                    diff = int(candidate["power"]) - my_power
                    if AUTO_POWER_BAND_MIN <= diff <= AUTO_POWER_BAND_MAX:
                        tier = 0
                    elif diff > 0:
                        tier = 1
                    else:
                        tier = 2
                    return (
                        tier,
                        0
                        if str(candidate["user_id"]) != previous_rival
                        else 1,
                        abs(diff),
                        -int(candidate["power"]),
                        str(candidate["user_id"]),
                    )

                target = min(candidates, key=preference)
                conn.execute(
                    "INSERT INTO rival_assignments "
                    "(week_start, player_id, rival_id, selection_mode, "
                    "selected_at, locked_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'auto', ?, ?, ?, ?) "
                    "ON CONFLICT(week_start, player_id) DO NOTHING",
                    (
                        week_iso,
                        player_id,
                        str(target["user_id"]),
                        now_iso,
                        now_iso,
                        now_iso,
                        now_iso,
                    ),
                )
                assigned += 1

        return {
            "week_start": week_iso,
            "status": "ok",
            "assigned": assigned,
            "locked": locked,
            "no_candidate": no_candidate,
            "already": already,
        }

    # ------------------------------------------------------------------
    # Weekly settlement
    # ------------------------------------------------------------------
    def settle_rivals(
        self,
        week: date | datetime | str,
        now: datetime | str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Write this week's rival results and pay human rewards once."""

        week_date = cal.week_start(week)
        week_iso = week_date.isoformat()
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        if local_now < cal.week_end_at(week_date):
            return {
                "week_start": week_iso,
                "status": "skipped",
                "reason": "week_not_ended",
                "settled": 0,
                "results": [],
            }
        if conn is not None:
            return self._settle_rivals_with(conn, week_iso, local_now)
        with self.transaction() as tx:
            return self._settle_rivals_with(tx, week_iso, local_now)

    def _settle_rivals_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        local_now: datetime,
    ) -> dict[str, Any]:
        settled_at = cal.iso_ts(local_now)
        rows = conn.execute(
            "SELECT a.player_id, a.rival_id, p.kind, "
            "COALESCE(mine.xp, 0) AS my_xp, "
            "COALESCE(theirs.xp, 0) AS rival_xp "
            "FROM rival_assignments a "
            "JOIN players p ON p.id = a.player_id "
            "LEFT JOIN weekly_scores mine "
            "ON mine.week_start = a.week_start AND mine.player_id = a.player_id "
            "LEFT JOIN weekly_scores theirs "
            "ON theirs.week_start = a.week_start AND theirs.player_id = a.rival_id "
            "WHERE a.week_start = ? ORDER BY a.player_id",
            (week_iso,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        newly_settled = 0
        for row in rows:
            player_id = str(row["player_id"])
            existing = conn.execute(
                "SELECT * FROM rival_results "
                "WHERE week_start = ? AND player_id = ?",
                (week_iso, player_id),
            ).fetchone()
            if existing is not None:
                results.append(self._result_payload(existing))
                continue
            my_xp = int(row["my_xp"])
            rival_xp = int(row["rival_xp"])
            outcome = rival_outcome(my_xp, rival_xp)
            reward = rival_reward(outcome, is_human=str(row["kind"]) == "human")
            cursor = conn.execute(
                "INSERT OR IGNORE INTO rival_results "
                "(week_start, player_id, rival_id, my_xp, rival_xp, outcome, "
                "reward_diamonds, settled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    week_iso,
                    player_id,
                    str(row["rival_id"]),
                    my_xp,
                    rival_xp,
                    outcome,
                    reward,
                    settled_at,
                ),
            )
            if cursor.rowcount == 0:
                stored = conn.execute(
                    "SELECT * FROM rival_results "
                    "WHERE week_start = ? AND player_id = ?",
                    (week_iso, player_id),
                ).fetchone()
                if stored is not None:
                    results.append(self._result_payload(stored))
                continue
            if reward > 0:
                self._credit_diamonds_with(  # type: ignore[attr-defined]
                    conn,
                    player_id=player_id,
                    amount=reward,
                    reason="rival_reward",
                    ref_type="rival",
                    ref_id=f"{week_iso}:{player_id}",
                    idempotency_key=f"rival-reward:{week_iso}:{player_id}",
                    now=local_now,
                    boost=False,
                )
            newly_settled += 1
            results.append(
                {
                    "week_start": week_iso,
                    "rival_id": str(row["rival_id"]),
                    "my_xp": my_xp,
                    "rival_xp": rival_xp,
                    "outcome": outcome,
                    "reward_diamonds": reward,
                    "settled_at": settled_at,
                }
            )
        return {
            "week_start": week_iso,
            "status": "settled",
            "settled": newly_settled,
            "results": results,
        }


__all__ = ["RivalMixin"]
