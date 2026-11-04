"""Persistence and lifecycle for Ghost-owned daily, repair, and weekend tasks."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from .. import calendar as cal
from ..tasks import (
    MANUAL_CHEST_TIER,
    MAX_ACTIVE_TASK_DEFINITIONS,
    REPAIR_CHEST_TIER,
    REPAIR_LOOKBACK_DAYS,
    REPAIR_XP_THRESHOLD,
    WEEKEND_CHEST_TIER,
    TaskLimitReached,
    TaskNotFound,
    TaskStateRejected,
    condition_progress,
    evaluate_condition,
    missed_date_from_system_key,
    repair_condition,
    repair_task_description,
    repair_task_title,
    roll_chest_amount,
    weekend_condition,
)

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
                sort_order = int(definition["sort_order"])
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO task_instances "
                    "(id, user_id, definition_id, source, system_key, title, "
                    "description, difficulty, chest_tier, starts_at, ends_at, "
                    "completion_mode, condition_json, status, completed_at, "
                    "proof_path, proof_mime, chest_status, claimed_at, "
                    "chest_amount, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'daily_manual', ?, ?, ?, ?, ?, ?, ?, "
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
                    "difficulty = ?, chest_tier = ?, sort_order = ?, "
                    "updated_at = ? "
                    "WHERE user_id = ? AND system_key = ? AND status = 'active' "
                    "AND (title != ? OR description != ? OR difficulty != ? "
                    "OR chest_tier != ? OR sort_order != ?)",
                    (
                        title,
                        description,
                        difficulty,
                        chest_tier,
                        sort_order,
                        stamp,
                        user_id,
                        system_key,
                        title,
                        description,
                        difficulty,
                        chest_tier,
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
                    "description, difficulty, chest_tier, starts_at, ends_at, "
                    "completion_mode, condition_json, status, completed_at, "
                    "proof_path, proof_mime, chest_status, claimed_at, "
                    "chest_amount, created_at, updated_at) "
                    "VALUES (?, ?, NULL, 'repair', ?, ?, ?, 1, ?, ?, ?, "
                    "'dsl', ?, 'active', NULL, NULL, NULL, 'none', NULL, NULL, "
                    "?, ?)",
                    (
                        _new_id("ti"),
                        user_id,
                        f"repair:{missed_day.isoformat()}",
                        repair_task_title(missed_day),
                        repair_task_description(xp),
                        REPAIR_CHEST_TIER,
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
                "description, difficulty, chest_tier, starts_at, ends_at, "
                "completion_mode, condition_json, status, completed_at, "
                "proof_path, proof_mime, chest_status, claimed_at, "
                "chest_amount, created_at, updated_at) "
                "VALUES (?, ?, NULL, 'weekend', ?, '周末 · 1000 XP', "
                "'周六周日累计 1000 XP。', 5, ?, ?, ?, 'dsl', ?, 'active', "
                "NULL, NULL, NULL, 'none', NULL, NULL, ?, ?)",
                (
                    _new_id("ti"),
                    user_id,
                    f"weekend:{saturday.isoformat()}",
                    WEEKEND_CHEST_TIER,
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
                conn.execute(
                    "UPDATE task_instances SET status = 'completed', "
                    "completed_at = ?, chest_status = 'available', updated_at = ? "
                    "WHERE id = ? AND user_id = ? AND status = 'active' "
                    "AND ends_at > ?",
                    (now_iso, now_iso, task_id, user_id, now_iso),
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
            conn.execute(
                "UPDATE task_instances SET status = 'completed', "
                "completed_at = ?, chest_status = 'available', proof_path = ?, "
                "proof_mime = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (now_iso, proof_path, proof_mime, now_iso, task_id, user_id),
            )
            updated = conn.execute(
                "SELECT * FROM task_instances WHERE id = ?", (task_id,)
            ).fetchone()
            return self._task_payload(updated, user_id=user_id, now=local_now)

    def claim_task_chest(
        self,
        user_id: str,
        task_id: str,
        *,
        now: datetime | str | None = None,
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
            if str(row["chest_status"]) == "claimed":
                ledger = self._ledger_by_key_with(conn, key)  # type: ignore[attr-defined]
                amount = (
                    int(row["chest_amount"])
                    if row["chest_amount"] is not None
                    else (abs(int(ledger["delta"])) if ledger is not None else 0)
                )
                wallet = self._sync_diamond_decay_with(  # type: ignore[attr-defined]
                    conn, user_id, local_now, create_for_unknown=False
                )
                return {
                    "amount": amount,
                    "balance": 0 if wallet is None else int(wallet["balance"]),
                    "duplicate": True,
                }
            if str(row["chest_status"]) != "available":
                raise TaskStateRejected("chest is not available")
            if str(row["status"]) != "completed":
                raise TaskStateRejected("task is not completed")
            if now_iso >= str(row["ends_at"]):
                raise TaskStateRejected("task has ended")
            amount = roll_chest_amount(int(row["chest_tier"]))
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
            conn.execute(
                "UPDATE task_instances SET chest_status = 'claimed', "
                "claimed_at = ?, chest_amount = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (now_iso, amount, now_iso, task_id, user_id),
            )
            return {
                "amount": amount,
                "balance": int(credit["balance"]),
                "duplicate": False,
            }


__all__ = ["TasksMixin"]
