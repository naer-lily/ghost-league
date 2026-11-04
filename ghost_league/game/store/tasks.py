"""Persistence and lifecycle for Ghost-owned daily, repair, and weekend tasks."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .. import calendar as cal
from ..tasks import (
    CHECKIN_CHEST_TIER,
    CHECKIN_TASK_DESCRIPTION,
    CHECKIN_TASK_SOURCE,
    CHECKIN_TASK_TITLE,
    CHEST_REWARD_BOOST,
    CHEST_REWARD_DIAMONDS,
    CHEST_REWARD_STAR,
    MANUAL_CHEST_POOL,
    MANUAL_CHEST_TIER,
    MAX_ACTIVE_TASK_DEFINITIONS,
    REPAIR_CHEST_TIER,
    REPAIR_LOOKBACK_DAYS,
    REPAIR_XP_THRESHOLD,
    TASK_CHEST_BOOST_CHANCE_KEY,
    TASK_CHEST_BOOST_CUTOFF_HOUR_KEY,
    TASK_CHEST_BOOST_MINUTES_KEY,
    TASK_CHEST_STAR_CHANCE_KEY,
    WEEKEND_CHEST_TIER,
    TaskLimitReached,
    TaskNotFound,
    TaskStateRejected,
    checkin_condition,
    chest_pool_config_key,
    chest_pool_fallback,
    chest_pool_for_task,
    condition_progress,
    evaluate_condition,
    missed_date_from_system_key,
    parse_chest_pool,
    repair_condition,
    repair_task_description,
    repair_task_title,
    roll_chest_reward,
    roll_chest_tier,
    weekend_condition,
)
from .boosts import DIAMOND_BOOST_MULTIPLIER_KEY

logger = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class TasksMixin:
    """Task definitions, instances, auto-completion, and chest claiming."""

    # ------------------------------------------------------------------
    # Definitions (user-authored daily manual tasks)
    # ------------------------------------------------------------------
    @staticmethod
    def _definition_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": str(item["id"]),
            "user_id": str(item["user_id"]),
            "title": str(item["title"]),
            "description": str(item["description"]),
            "difficulty": int(item["difficulty"]),
            "active": bool(item["active"]),
            "sort_order": int(item["sort_order"]),
            "created_at": str(item["created_at"]),
            "updated_at": str(item["updated_at"]),
        }

    @staticmethod
    def _validate_definition(title: str, description: str, difficulty: int) -> tuple[str, str, int]:
        if not isinstance(title, str):
            raise ValueError("title must be a string")
        title = title.strip()
        if not 1 <= len(title) <= 80:
            raise ValueError("title must be 1-80 characters")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        description = description.strip()
        if len(description) > 500:
            raise ValueError("description must be at most 500 characters")
        if isinstance(difficulty, bool) or difficulty not in (1, 2, 3):
            raise ValueError("difficulty must be 1, 2 or 3")
        return title, description, int(difficulty)

    def list_task_definitions(self, user_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM task_definitions WHERE user_id = ? AND active = 1 "
                "ORDER BY sort_order, created_at, id",
                (user_id,),
            ).fetchall()
            return [self._definition_payload(row) for row in rows]

    def create_task_definition(
        self,
        user_id: str,
        *,
        title: str,
        description: str = "",
        difficulty: int,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        title, description, difficulty = self._validate_definition(
            title, description, difficulty
        )
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        stamp = cal.iso_ts(local_now)
        with self.transaction() as conn:  # type: ignore[attr-defined]
            active = conn.execute(
                "SELECT COUNT(*) AS n FROM task_definitions "
                "WHERE user_id = ? AND active = 1",
                (user_id,),
            ).fetchone()
            if int(active["n"]) >= MAX_ACTIVE_TASK_DEFINITIONS:
                raise TaskLimitReached(
                    f"at most {MAX_ACTIVE_TASK_DEFINITIONS} active task definitions"
                )
            maximum = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS n FROM task_definitions "
                "WHERE user_id = ? AND active = 1",
                (user_id,),
            ).fetchone()
            sort_order = int(maximum["n"]) + 10
            definition_id = _new_id("td")
            conn.execute(
                "INSERT INTO task_definitions "
                "(id, user_id, title, description, difficulty, active, "
                "sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (
                    definition_id,
                    user_id,
                    title,
                    description,
                    difficulty,
                    sort_order,
                    stamp,
                    stamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM task_definitions WHERE id = ?", (definition_id,)
            ).fetchone()
            return self._definition_payload(row)

    def update_task_definition(
        self,
        user_id: str,
        definition_id: str,
        *,
        title: str,
        description: str = "",
        difficulty: int,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        title, description, difficulty = self._validate_definition(
            title, description, difficulty
        )
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        stamp = cal.iso_ts(local_now)
        with self.transaction() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM task_definitions "
                "WHERE id = ? AND user_id = ? AND active = 1",
                (definition_id, user_id),
            ).fetchone()
            if row is None:
                raise TaskNotFound("task definition not found")
            conn.execute(
                "UPDATE task_definitions SET title = ?, description = ?, "
                "difficulty = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (title, description, difficulty, stamp, definition_id, user_id),
            )
            updated = conn.execute(
                "SELECT * FROM task_definitions WHERE id = ?", (definition_id,)
            ).fetchone()
            return self._definition_payload(updated)

    def deactivate_task_definition(
        self,
        user_id: str,
        definition_id: str,
        *,
        now: datetime | str | None = None,
    ) -> None:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:  # type: ignore[attr-defined]
            cursor = conn.execute(
                "UPDATE task_definitions SET active = 0, updated_at = ? "
                "WHERE id = ? AND user_id = ? AND active = 1",
                (cal.iso_ts(local_now), definition_id, user_id),
            )
            if cursor.rowcount == 0:
                raise TaskNotFound("task definition not found")

    def reorder_task_definitions(
        self,
        user_id: str,
        ids: list[str] | tuple[str, ...],
        *,
        now: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """Persist a manual order as 10, 20, 30…

        Every supplied id must be an active definition owned by ``user_id``.
        The supplied ids come first in the given order; any other active
        definitions keep their relative order after them.  Active instances
        follow their definition immediately, while completed/expired
        instances keep their historical sort value.
        """

        if not isinstance(ids, (list, tuple)):
            raise ValueError("ids must be a list of task definition ids")
        normalized = [str(item) for item in ids]
        if any(not item for item in normalized):
            raise ValueError("task definition ids must be non-empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("task definition ids must be unique")

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        stamp = cal.iso_ts(local_now)
        with self.transaction() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM task_definitions WHERE user_id = ? AND active = 1 "
                "ORDER BY sort_order, created_at, id",
                (user_id,),
            ).fetchall()
            by_id = {str(row["id"]): row for row in rows}
            for definition_id in normalized:
                if definition_id not in by_id:
                    raise TaskNotFound("task definition not found")

            listed = set(normalized)
            ordered = [by_id[definition_id] for definition_id in normalized]
            ordered.extend(
                row for row in rows if str(row["id"]) not in listed
            )
            for index, row in enumerate(ordered, start=1):
                sort_order = index * 10
                if int(row["sort_order"]) == sort_order:
                    continue
                conn.execute(
                    "UPDATE task_definitions SET sort_order = ?, updated_at = ? "
                    "WHERE id = ? AND user_id = ? AND active = 1",
                    (sort_order, stamp, row["id"], user_id),
                )

            conn.execute(
                "UPDATE task_instances SET sort_order = COALESCE(("
                "SELECT sort_order FROM task_definitions "
                "WHERE task_definitions.id = task_instances.definition_id), "
                "sort_order), updated_at = ? "
                "WHERE user_id = ? AND source = 'daily_manual' "
                "AND status = 'active' AND definition_id IS NOT NULL "
                "AND sort_order != COALESCE(("
                "SELECT sort_order FROM task_definitions "
                "WHERE task_definitions.id = task_instances.definition_id), "
                "sort_order)",
                (stamp, user_id),
            )

            updated = conn.execute(
                "SELECT * FROM task_definitions WHERE user_id = ? AND active = 1 "
                "ORDER BY sort_order, created_at, id",
                (user_id,),
            ).fetchall()
            return [self._definition_payload(row) for row in updated]

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def ensure_user_tasks(
        self,
        user_id: str,
        now: datetime | str | None = None,
    ) -> int:
        """Idempotently materialise today's instances for active definitions."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        today = local_now.date()
        starts_at = cal.iso_ts(cal.day_start_at(today))
        ends_at = cal.iso_ts(cal.day_end_at(today))
        stamp = cal.iso_ts(local_now)
        inserted = 0
        with self.transaction() as conn:  # type: ignore[attr-defined]
            condition_json = json.dumps(
                checkin_condition(), ensure_ascii=False, separators=(",", ":")
            )
            conn.execute(
                "INSERT OR IGNORE INTO task_instances "
                "(id, user_id, definition_id, source, system_key, title, "
                "description, difficulty, chest_tier, chest_pool, starts_at, "
                "ends_at, completion_mode, condition_json, status, completed_at, "
                "proof_path, proof_mime, chest_status, claimed_at, "
                "chest_amount, sort_order, created_at, updated_at) "
                "VALUES (?, ?, NULL, ?, ?, ?, ?, 1, ?, ?, ?, ?, "
                "'dsl', ?, 'active', NULL, NULL, NULL, 'none', NULL, NULL, "
                "0, ?, ?)",
                (
                    _new_id("ti"),
                    user_id,
                    CHECKIN_TASK_SOURCE,
                    f"checkin:{today.isoformat()}",
                    CHECKIN_TASK_TITLE,
                    CHECKIN_TASK_DESCRIPTION,
                    CHECKIN_CHEST_TIER,
                    chest_pool_for_task(CHECKIN_TASK_SOURCE, 1),
                    starts_at,
                    ends_at,
                    condition_json,
                    stamp,
                    stamp,
                ),
            )
            definitions = conn.execute(
                "SELECT * FROM task_definitions WHERE user_id = ? AND active = 1 "
                "ORDER BY sort_order, created_at, id",
                (user_id,),
            ).fetchall()
            for definition in definitions:
                system_key = f"daily:{definition['id']}:{today.isoformat()}"
                title = str(definition["title"])
                description = str(definition["description"])
                difficulty = int(definition["difficulty"])
                chest_tier = MANUAL_CHEST_TIER[difficulty]
                chest_pool = MANUAL_CHEST_POOL[difficulty]
                sort_order = int(definition["sort_order"])
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO task_instances "
                    "(id, user_id, definition_id, source, system_key, title, "
                    "description, difficulty, chest_tier, chest_pool, starts_at, "
                    "ends_at, completion_mode, condition_json, status, "
                    "completed_at, proof_path, proof_mime, chest_status, "
                    "claimed_at, chest_amount, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'daily_manual', ?, ?, ?, ?, ?, ?, ?, ?, "
                    "'manual', NULL, 'active', NULL, NULL, NULL, 'none', NULL, "
                    "NULL, ?, ?, ?)",
                    (
                        _new_id("ti"),
                        user_id,
                        definition["id"],
                        system_key,
                        title,
                        description,
                        difficulty,
                        chest_tier,
                        chest_pool,
                        starts_at,
                        ends_at,
                        sort_order,
                        stamp,
                        stamp,
                    ),
                )
                inserted += max(0, cursor.rowcount)
                # Edits and ordering apply to today's still-active instance.
                # Completed and expired instances keep the snapshot they were
                # earned with.
                conn.execute(
                    "UPDATE task_instances SET title = ?, description = ?, "
                    "difficulty = ?, chest_tier = ?, chest_pool = ?, "
                    "sort_order = ?, updated_at = ? "
                    "WHERE user_id = ? AND system_key = ? AND status = 'active' "
                    "AND (title != ? OR description != ? OR difficulty != ? "
                    "OR chest_tier != ? OR chest_pool != ? OR sort_order != ?)",
                    (
                        title,
                        description,
                        difficulty,
                        chest_tier,
                        chest_pool,
                        sort_order,
                        stamp,
                        user_id,
                        system_key,
                        title,
                        description,
                        difficulty,
                        chest_tier,
                        chest_pool,
                        sort_order,
                    ),
                )
        return inserted

    def ensure_repair_tasks(
        self,
        user_id: str,
        today: date | datetime | str,
        *,
        now: datetime | str | None = None,
    ) -> int:
        """Create one repair task per missed completed day in the last week.

        Today is never considered.  A day qualifies only when it has some
        activity but failed to reach 100 XP through the shared daily resolver.
        """

        today_date = cal.parse_date(today)
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        starts_at = cal.iso_ts(cal.day_start_at(today_date))
        stamp = cal.iso_ts(local_now)
        candidates: list[tuple[date, int]] = []
        for offset in range(1, REPAIR_LOOKBACK_DAYS + 1):
            missed_day = today_date - timedelta(days=offset)
            activity = self.daily_activity_on_day(user_id, missed_day)  # type: ignore[attr-defined]
            xp = int(activity["xp"])
            seconds = int(activity["seconds"])
            if seconds <= 0:
                continue
            if xp >= REPAIR_XP_THRESHOLD:
                continue
            candidates.append((missed_day, xp))

        inserted = 0
        with self.transaction() as conn:  # type: ignore[attr-defined]
            for missed_day, xp in candidates:
                ends_at = cal.iso_ts(
                    cal.day_start_at(missed_day) + timedelta(days=REPAIR_LOOKBACK_DAYS + 1)
                )
                condition_json = json.dumps(
                    repair_condition(), ensure_ascii=False, separators=(",", ":")
                )
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO task_instances "
                    "(id, user_id, definition_id, source, system_key, title, "
                    "description, difficulty, chest_tier, chest_pool, starts_at, "
                    "ends_at, completion_mode, condition_json, status, "
                    "completed_at, proof_path, proof_mime, chest_status, "
                    "claimed_at, chest_amount, created_at, updated_at) "
                    "VALUES (?, ?, NULL, 'repair', ?, ?, ?, 1, ?, ?, ?, ?, "
                    "'dsl', ?, 'active', NULL, NULL, NULL, 'none', NULL, NULL, "
                    "?, ?)",
                    (
                        _new_id("ti"),
                        user_id,
                        f"repair:{missed_day.isoformat()}",
                        repair_task_title(missed_day),
                        repair_task_description(xp),
                        REPAIR_CHEST_TIER,
                        chest_pool_for_task("repair", 1),
                        starts_at,
                        ends_at,
                        condition_json,
                        stamp,
                        stamp,
                    ),
                )
                inserted += max(0, cursor.rowcount)
        return inserted

    def ensure_weekend_tasks(
        self,
        user_id: str,
        today: date | datetime | str,
        *,
        now: datetime | str | None = None,
    ) -> int:
        """Create this weekend's task only while it is Saturday or Sunday."""

        today_date = cal.parse_date(today)
        if today_date.weekday() not in (5, 6):
            return 0
        saturday = today_date - timedelta(days=today_date.weekday() - 5)
        starts_at = cal.iso_ts(cal.day_start_at(saturday))
        ends_at = cal.iso_ts(cal.day_start_at(saturday) + timedelta(days=2))
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        stamp = cal.iso_ts(local_now)
        condition_json = json.dumps(
            weekend_condition(), ensure_ascii=False, separators=(",", ":")
        )
        with self.transaction() as conn:  # type: ignore[attr-defined]
            cursor = conn.execute(
                "INSERT OR IGNORE INTO task_instances "
                "(id, user_id, definition_id, source, system_key, title, "
                "description, difficulty, chest_tier, chest_pool, starts_at, "
                "ends_at, completion_mode, condition_json, status, completed_at, "
                "proof_path, proof_mime, chest_status, claimed_at, "
                "chest_amount, created_at, updated_at) "
                "VALUES (?, ?, NULL, 'weekend', ?, '周末 · 1000 XP', "
                "'周六周日累计 1000 XP。', 5, ?, ?, ?, ?, 'dsl', ?, 'active', "
                "NULL, NULL, NULL, 'none', NULL, NULL, ?, ?)",
                (
                    _new_id("ti"),
                    user_id,
                    f"weekend:{saturday.isoformat()}",
                    WEEKEND_CHEST_TIER,
                    chest_pool_for_task("weekend", 5),
                    starts_at,
                    ends_at,
                    condition_json,
                    stamp,
                    stamp,
                ),
            )
            return max(0, cursor.rowcount)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_task_states(
        self,
        user_id: str,
        now: datetime | str | None = None,
    ) -> None:
        """Expire finished tasks and auto-complete DSL tasks that passed."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        now_iso = cal.iso_ts(local_now)
        with self._reader() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM task_instances "
                "WHERE user_id = ? AND status = 'active' "
                "AND completion_mode = 'dsl' AND ends_at > ?",
                (user_id, now_iso),
            ).fetchall()
        completed_ids: list[str] = []
        for row in rows:
            task = dict(row)
            try:
                condition = json.loads(task["condition_json"] or "null")
            except (TypeError, ValueError):
                logger.warning("task %s has invalid condition_json", task["id"])
                continue
            if evaluate_condition(
                condition,
                store=self,
                user_id=user_id,
                task=task,
                now=local_now,
            ):
                completed_ids.append(str(task["id"]))

        with self.transaction() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE task_instances SET status = 'expired', "
                "chest_status = CASE WHEN chest_status = 'available' "
                "THEN 'forfeited' ELSE chest_status END, updated_at = ? "
                "WHERE user_id = ? AND ends_at <= ? AND status != 'expired'",
                (now_iso, user_id, now_iso),
            )
            for task_id in completed_ids:
                row = conn.execute(
                    "SELECT source, difficulty, chest_pool FROM task_instances "
                    "WHERE id = ? AND user_id = ? AND status = 'active' "
                    "AND ends_at > ?",
                    (task_id, user_id, now_iso),
                ).fetchone()
                if row is None:
                    continue
                pool = self._effective_chest_pool(
                    row["chest_pool"], row["source"], int(row["difficulty"])
                )
                tier = self._roll_task_chest_tier_with(
                    conn,
                    pool,
                    source=str(row["source"]),
                    difficulty=int(row["difficulty"]),
                )
                conn.execute(
                    "UPDATE task_instances SET status = 'completed', "
                    "completed_at = ?, chest_tier = ?, "
                    "chest_status = 'available', updated_at = ? "
                    "WHERE id = ? AND user_id = ? AND status = 'active' "
                    "AND ends_at > ?",
                    (now_iso, tier, now_iso, task_id, user_id, now_iso),
                )

    @staticmethod
    def _task_progress(
        row: dict[str, Any],
        *,
        store: Any,
        user_id: str,
        now: datetime,
    ) -> dict[str, int] | None:
        if row.get("completion_mode") != "dsl" or not row.get("condition_json"):
            return None
        try:
            condition = json.loads(str(row["condition_json"]))
        except (TypeError, ValueError):
            logger.warning("task %s has invalid condition_json", row.get("id"))
            return {"current": 0, "target": 1}
        return condition_progress(
            condition,
            store=store,
            user_id=user_id,
            task=row,
            now=now,
        )

    def _task_chest_star_payload(
        self, task: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Return the claimed star for a task, or ``None`` while unclaimed."""

        star_id = task.get("chest_star_id")
        if not star_id or str(task.get("chest_status")) != "claimed":
            return None
        with self._reader() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM player_stars WHERE id = ? AND player_id = ?",
                (star_id, task["user_id"]),
            ).fetchone()
            return None if row is None else self._star_payload(row)

    def _task_payload(
        self,
        row: sqlite3.Row | dict[str, Any],
        *,
        user_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        task = dict(row)
        task_id = str(task["id"])
        progress = self._task_progress(
            task, store=self, user_id=user_id, now=now
        )
        source = str(task["source"])
        missed = (
            missed_date_from_system_key(task.get("system_key"))
            if source == "repair"
            else None
        )
        return {
            "id": task_id,
            "source": source,
            "title": str(task["title"]),
            "description": str(task["description"]),
            "difficulty": int(task["difficulty"]),
            "chest_tier": int(task["chest_tier"]),
            "chest_pool": str(task.get("chest_pool") or ""),
            "sort_order": int(task["sort_order"]),
            "starts_at": str(task["starts_at"]),
            "ends_at": str(task["ends_at"]),
            "missed_date": missed.isoformat() if missed is not None else None,
            "status": str(task["status"]),
            "completed_at": task["completed_at"],
            "chest_status": str(task["chest_status"]),
            "chest_amount": (
                None if task["chest_amount"] is None else int(task["chest_amount"])
            ),
            "chest_reward_type": str(
                task.get("chest_reward_type") or CHEST_REWARD_DIAMONDS
            ),
            "chest_boost_minutes": (
                None
                if task.get("chest_boost_minutes") is None
                else int(task["chest_boost_minutes"])
            ),
            "chest_star": self._task_chest_star_payload(task),
            "proof_url": (
                f"/v1/me/tasks/{task_id}/proof" if task["proof_path"] else None
            ),
            "progress": progress,
        }

    def list_visible_tasks(
        self,
        user_id: str,
        now: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """Refresh then return active/completed tasks whose deadline has not passed.

        The store only guarantees a stable data order. Display ordering (for
        example sinking completed tasks whose chest was claimed) belongs to the
        UI, not to this query.
        """

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        self.refresh_task_states(user_id, local_now)
        now_iso = cal.iso_ts(local_now)
        with self._reader() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM task_instances "
                "WHERE user_id = ? AND status IN ('active', 'completed') "
                "AND starts_at <= ? AND ends_at > ? "
                "ORDER BY ends_at ASC, sort_order ASC, created_at ASC, id ASC",
                (user_id, now_iso, now_iso),
            ).fetchall()
            return [
                self._task_payload(row, user_id=user_id, now=local_now)
                for row in rows
            ]

    def get_task(
        self, user_id: str, task_id: str
    ) -> dict[str, Any] | None:
        with self._reader() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM task_instances WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
            return None if row is None else dict(row)

    def get_task_payload(
        self,
        user_id: str,
        task_id: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any] | None:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        task = self.get_task(user_id, task_id)
        if task is None:
            return None
        return self._task_payload(task, user_id=user_id, now=local_now)

    # ------------------------------------------------------------------
    # Manual completion and chests
    # ------------------------------------------------------------------
    def complete_manual_task(
        self,
        user_id: str,
        task_id: str,
        *,
        proof_path: str,
        proof_mime: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        now_iso = cal.iso_ts(local_now)
        with self.transaction() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM task_instances WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
            if row is None:
                raise TaskNotFound("task not found")
            if str(row["completion_mode"]) != "manual":
                raise TaskStateRejected("this task completes automatically")
            if str(row["status"]) != "active":
                raise TaskStateRejected("task is not active")
            if now_iso >= str(row["ends_at"]):
                raise TaskStateRejected("task has ended")
            pool = self._effective_chest_pool(
                row["chest_pool"], row["source"], int(row["difficulty"])
            )
            tier = self._roll_task_chest_tier_with(
                conn,
                pool,
                source=str(row["source"]),
                difficulty=int(row["difficulty"]),
            )
            conn.execute(
                "UPDATE task_instances SET status = 'completed', "
                "completed_at = ?, chest_status = 'available', "
                "chest_tier = ?, chest_pool = ?, proof_path = ?, "
                "proof_mime = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (
                    now_iso,
                    tier,
                    pool,
                    proof_path,
                    proof_mime,
                    now_iso,
                    task_id,
                    user_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM task_instances WHERE id = ?", (task_id,)
            ).fetchone()
            return self._task_payload(updated, user_id=user_id, now=local_now)

    @staticmethod
    def _effective_chest_pool(
        pool: Any, source: Any, difficulty: int
    ) -> str:
        """Use the stored pool, deriving one for instances created pre-pool."""

        value = str(pool or "").strip()
        return value or chest_pool_for_task(str(source or ""), difficulty)

    def _chest_pool_weights_with(
        self,
        conn: sqlite3.Connection,
        pool: str,
        *,
        source: str,
        difficulty: int,
    ) -> dict[int, int]:
        """Read one pool, failing closed to the source's conservative pool."""

        key = chest_pool_config_key(pool)
        raw = self._config_value_with(conn, key)  # type: ignore[attr-defined]
        weights = parse_chest_pool(raw)
        if weights is None:
            logger.warning(
                "chest pool %s is missing or invalid; using conservative fallback",
                pool,
            )
            weights = chest_pool_fallback(
                pool, source=source, difficulty=difficulty
            )
        return weights

    def _roll_task_chest_tier_with(
        self,
        conn: sqlite3.Connection,
        pool: str,
        *,
        source: str,
        difficulty: int,
    ) -> int:
        weights = self._chest_pool_weights_with(
            conn, pool, source=source, difficulty=difficulty
        )
        return roll_chest_tier(weights)

    def _chest_config_with(
        self, conn: sqlite3.Connection
    ) -> dict[str, int]:
        """Return validated chest config, failing closed to diamonds.

        A missing or malformed boost row disables boosts; a missing or
        malformed star row disables the star branch.  Chest claims still pay
        diamonds in either case.
        """

        def read(key: str, default: int, minimum: int) -> int:
            try:
                return self._config_int_with(  # type: ignore[attr-defined]
                    conn, key, minimum=minimum
                )
            except ValueError:
                logger.warning(
                    "task chest config %s is missing or invalid; using %s",
                    key,
                    default,
                )
                return default

        chance = read(TASK_CHEST_BOOST_CHANCE_KEY, 0, 0)
        minutes = read(TASK_CHEST_BOOST_MINUTES_KEY, 0, 1)
        cutoff = read(TASK_CHEST_BOOST_CUTOFF_HOUR_KEY, 0, 0)
        star_chance = read(TASK_CHEST_STAR_CHANCE_KEY, 0, 0)
        multiplier = read(DIAMOND_BOOST_MULTIPLIER_KEY, 0, 1)
        if chance > 100:
            logger.warning(
                "task_chest_boost_chance is out of range; paying diamonds"
            )
            chance = 0
        if star_chance > 100:
            logger.warning(
                "task_chest_star_chance is out of range; paying diamonds"
            )
            star_chance = 0
        if cutoff > 23:
            logger.warning(
                "task_chest_boost_cutoff_hour is out of range; disabling boosts"
            )
            cutoff = 0
        if multiplier < 1:
            chance, minutes, multiplier = 0, 0, 1
        return {
            "boost_chance": chance,
            "boost_minutes": minutes,
            "cutoff_hour": cutoff,
            "star_chance": star_chance,
            "multiplier": multiplier,
        }

    def _create_task_chest_star_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        acquired_at: str,
    ) -> dict[str, Any]:
        """Create the one normal star paid by a star chest."""

        rarity = self.roll_star_rarity()  # type: ignore[attr-defined]
        star_type = self.roll_star_type(rarity)  # type: ignore[attr-defined]
        visual = self.make_star_visual(  # type: ignore[attr-defined]
            star_type, rarity, None
        )
        return self._insert_player_star_with(  # type: ignore[attr-defined]
            conn,
            player_id=player_id,
            name=self.generate_star_name(),  # type: ignore[attr-defined]
            kind="normal",
            season_key=None,
            price_diamonds=0,
            acquired_at=acquired_at,
            star_type=star_type,
            rarity=rarity,
            palette=visual["palette"],
            visual_seed=int(visual["visual_seed"]),
            companion_count=int(visual["companion_count"]),
            catalog_code=self._new_catalog_code_with(  # type: ignore[attr-defined]
                conn, acquired_at
            ),
            source="task_chest",
        )

    def _task_chest_star_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        star_id: Any,
    ) -> dict[str, Any] | None:
        if not star_id:
            return None
        row = conn.execute(
            "SELECT * FROM player_stars WHERE id = ? AND player_id = ?",
            (star_id, player_id),
        ).fetchone()
        return None if row is None else self._star_payload(row)  # type: ignore[attr-defined]

    def claim_task_chest(
        self,
        user_id: str,
        task_id: str,
        *,
        now: datetime | str | None = None,
        rng: Callable[[int], int] | None = None,
    ) -> dict[str, Any]:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        now_iso = cal.iso_ts(local_now)
        key = f"task-chest:{task_id}"
        with self.transaction() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM task_instances WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
            if row is None:
                raise TaskNotFound("task not found")
            reward_type = str(
                row["chest_reward_type"] or CHEST_REWARD_DIAMONDS
            )
            stored_minutes = row["chest_boost_minutes"]
            if str(row["chest_status"]) == "claimed":
                ledger = self._ledger_by_key_with(conn, key)  # type: ignore[attr-defined]
                amount = (
                    int(row["chest_amount"])
                    if row["chest_amount"] is not None
                    else (abs(int(ledger["delta"])) if ledger is not None else 0)
                )
                if reward_type in {CHEST_REWARD_BOOST, CHEST_REWARD_STAR}:
                    amount = (
                        int(row["chest_amount"])
                        if row["chest_amount"] is not None
                        else 0
                    )
                wallet = self._sync_diamond_decay_with(  # type: ignore[attr-defined]
                    conn, user_id, local_now, create_for_unknown=False
                )
                return {
                    "amount": amount,
                    "balance": 0 if wallet is None else int(wallet["balance"]),
                    "duplicate": True,
                    "reward_type": reward_type,
                    "boost_minutes": (
                        None
                        if stored_minutes is None
                        else int(stored_minutes)
                    ),
                    "star": self._task_chest_star_with(
                        conn,
                        player_id=user_id,
                        star_id=row["chest_star_id"],
                    ),
                    "diamond_boost": self._boost_state_with(  # type: ignore[attr-defined]
                        conn, user_id, local_now
                    ),
                }
            if str(row["chest_status"]) != "available":
                raise TaskStateRejected("chest is not available")
            if str(row["status"]) != "completed":
                raise TaskStateRejected("task is not completed")
            if now_iso >= str(row["ends_at"]):
                raise TaskStateRejected("task has ended")

            config = self._chest_config_with(conn)
            reward = roll_chest_reward(
                int(row["chest_tier"]),
                boost_chance=int(config["boost_chance"]),
                boost_minutes=int(config["boost_minutes"]),
                star_chance=int(config["star_chance"]),
                boost_allowed=local_now.hour < int(config["cutoff_hour"]),
                rng=rng,
            )
            star_payload: dict[str, Any] | None = None
            stored_star_id: str | None = None
            if reward["reward_type"] == CHEST_REWARD_STAR:
                reward_type = CHEST_REWARD_STAR
                boost_minutes = None
                amount = 0
                stored_amount: int | None = 0
                star_payload = self._create_task_chest_star_with(
                    conn, player_id=user_id, acquired_at=now_iso
                )
                stored_star_id = str(star_payload["id"])
                wallet = self._sync_diamond_decay_with(  # type: ignore[attr-defined]
                    conn, user_id, local_now, create_for_unknown=False
                )
                balance = 0 if wallet is None else int(wallet["balance"])
            elif reward["reward_type"] == CHEST_REWARD_BOOST:
                reward_type = CHEST_REWARD_BOOST
                boost_minutes: int | None = int(reward["boost_minutes"])
                amount = 0
                stored_amount = None
                self._extend_diamond_boost_with(  # type: ignore[attr-defined]
                    conn,
                    player_id=user_id,
                    minutes=boost_minutes,
                    multiplier=int(config["multiplier"]),
                    now=local_now,
                    updated_at=now_iso,
                )
                wallet = self._sync_diamond_decay_with(  # type: ignore[attr-defined]
                    conn, user_id, local_now, create_for_unknown=False
                )
                balance = 0 if wallet is None else int(wallet["balance"])
            else:
                reward_type = CHEST_REWARD_DIAMONDS
                boost_minutes = None
                amount = int(reward["amount"])
                stored_amount = amount
                credit = self._credit_diamonds_with(  # type: ignore[attr-defined]
                    conn,
                    player_id=user_id,
                    amount=amount,
                    reason="task_chest",
                    ref_type="task",
                    ref_id=task_id,
                    idempotency_key=key,
                    now=local_now,
                    boost=False,
                )
                balance = int(credit["balance"])

            conn.execute(
                "UPDATE task_instances SET chest_status = 'claimed', "
                "claimed_at = ?, chest_amount = ?, chest_reward_type = ?, "
                "chest_boost_minutes = ?, chest_star_id = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    now_iso,
                    stored_amount,
                    reward_type,
                    boost_minutes,
                    stored_star_id,
                    now_iso,
                    task_id,
                    user_id,
                ),
            )
            return {
                "amount": amount,
                "balance": balance,
                "duplicate": False,
                "reward_type": reward_type,
                "boost_minutes": boost_minutes,
                "star": star_payload,
                "diamond_boost": self._boost_state_with(  # type: ignore[attr-defined]
                    conn, user_id, local_now
                ),
            }


__all__ = ["TasksMixin"]
