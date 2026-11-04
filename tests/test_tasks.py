from __future__ import annotations

import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from ghost_league.game.store import SOURCE_HUMAN, GameStore
from ghost_league.game.tasks import (
    CHEST_TIERS,
    TaskNotFound,
    TaskStateRejected,
    chest_amount_range,
    evaluate_condition,
    repair_condition,
    roll_chest_amount,
    weekend_condition,
)
from ghost_league.schedule import TZ
from tests.test_api import APITestBase, auth, image_bytes

TOKEN = "test-token-only"


def ts(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


class TaskStoreBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GameStore(Path(self.temp.name) / "league.db")
        self.now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TZ)
        self.store.create_player(
            "u", kind="human", display_name="U", joined_week="2026-10-19", now=self.now
        )

    def add_activity(self, day: str, seconds: int, *, event_id: str | None = None) -> None:
        self.store.ingest_activity(
            "u",
            event_id=event_id or f"event-{day}-{seconds}",
            seconds=seconds,
            occurred_at=datetime.fromisoformat(f"{day}T12:00:00+08:00"),
            source=SOURCE_HUMAN,
            now=self.now,
        )

    def grant_embers(self, balance: int = 3) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ember_balance "
                "(player_id, balance, week_earned, week_start, updated_at) "
                "VALUES ('u', ?, 0, '2026-11-02', ?)",
                (balance, ts(self.now)),
            )


class DailyTaskTests(TaskStoreBase):
    def test_daily_definition_generates_once_with_mapped_chest(self) -> None:
        definition = self.store.create_task_definition(
            "u", title="画一张", description="随便画", difficulty=3, now=self.now
        )
        self.assertEqual(definition["difficulty"], 3)
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 1)
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 0)
        tasks = self.store.list_visible_tasks("u", self.now)
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["source"], "daily_manual")
        self.assertEqual(task["title"], "画一张")
        self.assertEqual(task["difficulty"], 3)
        self.assertEqual(task["chest_tier"], 3)
        self.assertEqual(task["starts_at"], "2026-11-04T00:00:00+08:00")
        self.assertEqual(task["ends_at"], "2026-11-05T00:00:00+08:00")
        self.assertIsNone(task["progress"])
        self.assertIsNone(task["missed_date"])

    def test_definition_edit_syncs_active_instance(self) -> None:
        definition = self.store.create_task_definition(
            "u",
            title="画五个 ghosting shape",
            description="旧描述",
            difficulty=1,
            now=self.now,
        )
        self.store.ensure_user_tasks("u", self.now)
        before = self.store.list_visible_tasks("u", self.now)[0]

        self.store.update_task_definition(
            "u",
            definition["id"],
            title="5 个 ghosting shape",
            description="只要有笔有纸就能做！",
            difficulty=3,
            now=self.now,
        )
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 0)
        after = self.store.list_visible_tasks("u", self.now)[0]

        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["title"], "5 个 ghosting shape")
        self.assertEqual(after["description"], "只要有笔有纸就能做！")
        self.assertEqual(after["difficulty"], 3)
        self.assertEqual(after["chest_tier"], 3)
        self.assertEqual(after["starts_at"], before["starts_at"])
        self.assertEqual(after["ends_at"], before["ends_at"])

    def test_definition_edit_keeps_completed_snapshot(self) -> None:
        definition = self.store.create_task_definition(
            "u",
            title="画一张",
            description="旧描述",
            difficulty=1,
            now=self.now,
        )
        self.store.ensure_user_tasks("u", self.now)
        task = self.store.list_visible_tasks("u", self.now)[0]
        completed = self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="task-proofs/u/x.png",
            proof_mime="image/png",
            now=self.now,
        )

        self.store.update_task_definition(
            "u",
            definition["id"],
            title="新的标题",
            description="新的描述",
            difficulty=3,
            now=self.now,
        )
        self.store.ensure_user_tasks("u", self.now)
        after = self.store.list_visible_tasks("u", self.now)[0]

        self.assertEqual(after["id"], completed["id"])
        self.assertEqual(after["status"], "completed")
        self.assertEqual(after["title"], "画一张")
        self.assertEqual(after["description"], "旧描述")
        self.assertEqual(after["difficulty"], 1)
        self.assertEqual(after["chest_tier"], 1)
        self.assertEqual(after["completed_at"], completed["completed_at"])

    def test_difficulty_maps_to_wood_copper_silver(self) -> None:
        for difficulty, tier in ((1, 1), (2, 2), (3, 3)):
            self.store.create_task_definition(
                "u",
                title=f"任务{difficulty}",
                difficulty=difficulty,
                now=self.now,
            )
        self.store.ensure_user_tasks("u", self.now)
        tiers = {
            task["difficulty"]: task["chest_tier"]
            for task in self.store.list_visible_tasks("u", self.now)
        }
        self.assertEqual(tiers, {1: 1, 2: 2, 3: 3})

    def test_next_day_generates_new_instance(self) -> None:
        self.store.create_task_definition(
            "u", title="画一张", difficulty=1, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        tomorrow = self.now + timedelta(days=1)
        self.assertEqual(self.store.ensure_user_tasks("u", tomorrow), 1)
        tasks = self.store.list_visible_tasks("u", tomorrow)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["starts_at"], "2026-11-05T00:00:00+08:00")
        self.assertEqual(tasks[0]["ends_at"], "2026-11-06T00:00:00+08:00")

    def test_completed_task_hides_and_forfeits_after_deadline(self) -> None:
        self.store.create_task_definition(
            "u", title="画一张", difficulty=2, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        task = self.store.list_visible_tasks("u", self.now)[0]
        self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="task-proofs/u/x.png",
            proof_mime="image/png",
            now=self.now,
        )
        later = self.now + timedelta(days=1)
        self.assertEqual(self.store.list_visible_tasks("u", later), [])
        stored = self.store.get_task("u", task["id"])
        self.assertEqual(stored["status"], "expired")
        self.assertEqual(stored["chest_status"], "forfeited")

    def test_definition_stop_does_not_touch_existing_instance(self) -> None:
        definition = self.store.create_task_definition(
            "u", title="画一张", difficulty=1, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        self.store.deactivate_task_definition("u", definition["id"], now=self.now)
        self.assertEqual(self.store.list_task_definitions("u"), [])
        self.assertEqual(len(self.store.list_visible_tasks("u", self.now)), 1)
        tomorrow = self.now + timedelta(days=1)
        self.store.ensure_user_tasks("u", tomorrow)
        self.assertEqual(len(self.store.list_visible_tasks("u", tomorrow)), 0)


class ManualChestTests(TaskStoreBase):
    def _completed_task(self) -> dict:
        self.store.create_task_definition("u", title="画一张", difficulty=2, now=self.now)
        self.store.ensure_user_tasks("u", self.now)
        task = self.store.list_visible_tasks("u", self.now)[0]
        self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="task-proofs/u/x.png",
            proof_mime="image/png",
            now=self.now,
        )
        return self.store.list_visible_tasks("u", self.now)[0]

    def test_completion_makes_chest_available(self) -> None:
        task = self._completed_task()
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["chest_status"], "available")
        self.assertIsNotNone(task["completed_at"])
        self.assertEqual(task["proof_url"], f"/v1/me/tasks/{task['id']}/proof")

    def test_chest_credits_diamonds_and_is_idempotent(self) -> None:
        task = self._completed_task()
        first = self.store.claim_task_chest("u", task["id"], now=self.now)
        low, high = chest_amount_range(2)
        self.assertIn(first["amount"], range(low, high + 1))
        self.assertFalse(first["duplicate"])
        self.assertEqual(first["balance"], 1000 + first["amount"])
        duplicate = self.store.claim_task_chest("u", task["id"], now=self.now)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["amount"], first["amount"])
        visible = self.store.list_visible_tasks("u", self.now)
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["chest_status"], "claimed")
        self.assertEqual(visible[0]["chest_amount"], first["amount"])
        ledger = self.store.diamond_ledger("u")
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["reason"], "task_chest")
        self.assertEqual(ledger[0]["ref_type"], "task")
        self.assertEqual(ledger[0]["ref_id"], task["id"])
        self.assertEqual(ledger[0]["idempotency_key"], f"task-chest:{task['id']}")

    def test_claim_requires_completion(self) -> None:
        self.store.create_task_definition("u", title="画一张", difficulty=1, now=self.now)
        self.store.ensure_user_tasks("u", self.now)
        task = self.store.list_visible_tasks("u", self.now)[0]
        with self.assertRaises(TaskStateRejected):
            self.store.claim_task_chest("u", task["id"], now=self.now)

    def test_claim_after_deadline_is_rejected(self) -> None:
        task = self._completed_task()
        with self.assertRaises(TaskStateRejected):
            self.store.claim_task_chest(
                "u", task["id"], now=self.now + timedelta(days=1)
            )

    def test_other_owner_is_not_found(self) -> None:
        self.store.create_task_definition("u", title="画一张", difficulty=1, now=self.now)
        self.store.ensure_user_tasks("u", self.now)
        task = self.store.list_visible_tasks("u", self.now)[0]
        with self.assertRaises(TaskNotFound):
            self.store.complete_manual_task(
                "other",
                task["id"],
                proof_path="x",
                proof_mime="image/png",
                now=self.now,
            )

    def test_chest_tiers_have_the_documented_ranges(self) -> None:
        self.assertEqual(
            [(row["tier"], row["min"], row["max"]) for row in CHEST_TIERS],
            [(1, 3, 6), (2, 6, 10), (3, 10, 16), (4, 18, 28), (5, 30, 48)],
        )
        draws = {roll_chest_amount(5, rng=lambda span: 0) for _ in range(3)}
        self.assertEqual(draws, {30})
        self.assertEqual(roll_chest_amount(5, rng=lambda span: span - 1), 48)


class RepairTaskTests(TaskStoreBase):
    def test_today_is_not_a_repair_day(self) -> None:
        self.add_activity("2026-11-04", 444)
        self.assertEqual(self.store.ensure_repair_tasks("u", self.now.date(), now=self.now), 0)
        self.assertEqual(self.store.list_visible_tasks("u", self.now), [])

    def test_yesterday_and_seven_days_ago_qualify_but_eight_days_does_not(self) -> None:
        # 2026-10-27 is eight days before 2026-11-04 and must not qualify.
        self.add_activity("2026-10-27", 444)
        self.add_activity("2026-11-03", 444)
        self.assertEqual(
            self.store.ensure_repair_tasks("u", self.now.date(), now=self.now), 1
        )
        self.add_activity("2026-10-28", 444)
        self.assertEqual(
            self.store.ensure_repair_tasks("u", self.now.date(), now=self.now), 1
        )
        tasks = self.store.list_visible_tasks("u", self.now)
        self.assertEqual(
            {task["title"] for task in tasks},
            {"补断联 · 10/28", "补断联 · 11/03"},
        )
        self.assertEqual(
            self.store.ensure_repair_tasks("u", self.now.date(), now=self.now), 0
        )

    def test_zero_and_full_days_do_not_generate(self) -> None:
        self.add_activity("2026-11-03", 0)
        self.add_activity("2026-11-02", 600)
        self.assertEqual(self.store.ensure_repair_tasks("u", self.now.date(), now=self.now), 0)

    def test_repair_task_fields_and_deadline(self) -> None:
        self.add_activity("2026-10-29", 444)
        self.assertEqual(self.store.ensure_repair_tasks("u", self.now.date(), now=self.now), 1)
        task = self.store.list_visible_tasks("u", self.now)[0]
        self.assertEqual(task["source"], "repair")
        self.assertEqual(task["difficulty"], 1)
        self.assertEqual(task["chest_tier"], 1)
        self.assertEqual(task["title"], "补断联 · 10/29")
        self.assertEqual(task["description"], "当天只拿到 74 XP；用余烬补上。")
        self.assertEqual(task["starts_at"], "2026-11-04T00:00:00+08:00")
        self.assertEqual(task["ends_at"], "2026-11-06T00:00:00+08:00")
        self.assertEqual(task["progress"], {"current": 0, "target": 1})
        self.assertEqual(task["missed_date"], "2026-10-29")

    def test_repaired_checkin_auto_completes(self) -> None:
        self.add_activity("2026-10-29", 444)
        self.store.ensure_repair_tasks("u", self.now.date(), now=self.now)
        task = self.store.list_visible_tasks("u", self.now)[0]
        self.grant_embers()
        self.store.repair_checkin("u", "2026-10-29", idempotency_key="repair-1", now=self.now)
        completed = self.store.list_visible_tasks("u", self.now)[0]
        self.assertEqual(completed["id"], task["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["chest_status"], "available")
        self.assertEqual(completed["progress"], {"current": 1, "target": 1})

    def test_repair_task_expires_unclaimed(self) -> None:
        self.add_activity("2026-10-29", 444)
        self.store.ensure_repair_tasks("u", self.now.date(), now=self.now)
        task = self.store.list_visible_tasks("u", self.now)[0]
        self.grant_embers()
        self.store.repair_checkin("u", "2026-10-29", idempotency_key="repair-1", now=self.now)
        completed = self.store.list_visible_tasks("u", self.now)[0]
        self.assertEqual(completed["chest_status"], "available")
        later = datetime(2026, 11, 6, 0, 0, 0, tzinfo=TZ)
        self.assertEqual(self.store.list_visible_tasks("u", later), [])
        stored = self.store.get_task("u", task["id"])
        self.assertEqual(stored["status"], "expired")
        self.assertEqual(stored["chest_status"], "forfeited")


class WeekendTaskTests(TaskStoreBase):
    def test_generated_only_on_weekend_and_idempotent(self) -> None:
        friday = datetime(2026, 10, 30, 12, 0, 0, tzinfo=TZ)
        self.assertEqual(self.store.ensure_weekend_tasks("u", friday.date(), now=friday), 0)
        saturday = datetime(2026, 10, 31, 12, 0, 0, tzinfo=TZ)
        self.assertEqual(self.store.ensure_weekend_tasks("u", saturday.date(), now=saturday), 1)
        self.assertEqual(self.store.ensure_weekend_tasks("u", saturday.date(), now=saturday), 0)
        task = self.store.list_visible_tasks("u", saturday)[0]
        self.assertEqual(task["source"], "weekend")
        self.assertEqual(task["difficulty"], 5)
        self.assertEqual(task["chest_tier"], 5)
        self.assertEqual(task["title"], "周末 · 1000 XP")
        self.assertEqual(task["description"], "周六周日累计 1000 XP。")
        self.assertEqual(task["starts_at"], "2026-10-31T00:00:00+08:00")
        self.assertEqual(task["ends_at"], "2026-11-02T00:00:00+08:00")
        self.assertEqual(task["progress"], {"current": 0, "target": 1000})
        self.assertIsNone(task["missed_date"])

    def test_sunday_generates_the_same_weekend_instance(self) -> None:
        sunday = datetime(2026, 11, 1, 12, 0, 0, tzinfo=TZ)
        self.assertEqual(
            self.store.ensure_weekend_tasks("u", sunday.date(), now=sunday), 1
        )
        task = self.store.list_visible_tasks("u", sunday)[0]
        self.assertEqual(task["starts_at"], "2026-10-31T00:00:00+08:00")
        self.assertEqual(task["ends_at"], "2026-11-02T00:00:00+08:00")
        self.assertEqual(
            self.store.ensure_weekend_tasks("u", sunday.date(), now=sunday), 0
        )

    def test_saturday_plus_sunday_completes_and_monday_expires(self) -> None:
        saturday = datetime(2026, 10, 31, 12, 0, 0, tzinfo=TZ)
        sunday = datetime(2026, 11, 1, 12, 0, 0, tzinfo=TZ)
        self.store.ensure_weekend_tasks("u", saturday.date(), now=saturday)
        self.add_activity("2026-10-31", 3000, event_id="sat")
        task = self.store.list_visible_tasks("u", sunday)[0]
        self.assertEqual(task["status"], "active")
        self.assertEqual(task["progress"], {"current": 500, "target": 1000})
        self.add_activity("2026-11-01", 3000, event_id="sun")
        task = self.store.list_visible_tasks("u", sunday)[0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], {"current": 1000, "target": 1000})
        monday = datetime(2026, 11, 2, 0, 0, 0, tzinfo=TZ)
        self.assertEqual(self.store.list_visible_tasks("u", monday), [])
        stored = self.store.get_task("u", task["id"])
        self.assertEqual(stored["status"], "expired")
        self.assertEqual(stored["chest_status"], "forfeited")

    def test_next_weekend_creates_a_new_instance(self) -> None:
        first = datetime(2026, 10, 31, 12, 0, 0, tzinfo=TZ)
        second = datetime(2026, 11, 7, 12, 0, 0, tzinfo=TZ)
        self.store.ensure_weekend_tasks("u", first.date(), now=first)
        self.store.ensure_weekend_tasks("u", second.date(), now=second)
        with self.store._reader() as conn:
            keys = [
                row["system_key"]
                for row in conn.execute(
                    "SELECT system_key FROM task_instances ORDER BY system_key"
                )
            ]
        self.assertEqual(keys, ["weekend:2026-10-31", "weekend:2026-11-07"])


class DslTests(TaskStoreBase):
    def _condition(self, condition, task=None, now=None):
        return evaluate_condition(
            condition,
            store=self.store,
            user_id="u",
            task=task
            or {
                "starts_at": "2026-10-31T00:00:00+08:00",
                "ends_at": "2026-11-02T00:00:00+08:00",
                "system_key": "weekend:2026-10-31",
            },
            now=now or self.now,
        )

    def test_xp_between_and_comparisons(self) -> None:
        self.add_activity("2026-10-31", 3000, event_id="sat")
        self.add_activity("2026-11-01", 3000, event_id="sun")
        self.assertTrue(self._condition(weekend_condition()))
        self.assertFalse(
            self._condition(
                {
                    "op": "gt",
                    "left": 1,
                    "right": 0,
                }
            )
        )
        self.assertTrue(self._condition({"op": "lte", "left": 2, "right": 3}))

    def test_and_or_not(self) -> None:
        self.assertTrue(
            self._condition(
                {
                    "op": "and",
                    "args": [
                        {"op": "gte", "left": 3, "right": 1},
                        {"op": "not", "arg": {"op": "eq", "left": 1, "right": 2}},
                    ],
                }
            )
        )
        self.assertTrue(
            self._condition(
                {
                    "op": "or",
                    "args": [
                        {"op": "eq", "left": 1, "right": 2},
                        {"op": "eq", "left": "x", "right": "x"},
                    ],
                }
            )
        )

    def test_checkin_source(self) -> None:
        self.add_activity("2026-10-29", 444)
        self.grant_embers()
        self.store.repair_checkin("u", "2026-10-29", idempotency_key="repair-1", now=self.now)
        task = {
            "starts_at": "2026-11-04T00:00:00+08:00",
            "ends_at": "2026-11-06T00:00:00+08:00",
            "system_key": "repair:2026-10-29",
        }
        self.assertTrue(self._condition(repair_condition(), task=task))
        self.assertFalse(
            self._condition(
                {"op": "eq", "left": {"fn": "checkin_source", "args": ["2026-10-30"]}, "right": "repaired"}
            )
        )

    def test_unknown_fields_and_operations_fail_closed(self) -> None:
        self.assertFalse(self._condition({"var": "task.unknown"}))
        self.assertFalse(self._condition({"op": "add", "left": 1, "right": 2}))
        self.assertFalse(self._condition({"fn": "today_xp", "args": []}))
        self.assertFalse(
            self._condition({"op": "eq", "left": 1, "right": 1, "extra": True})
        )

    def test_depth_and_node_limits_fail_closed(self) -> None:
        deep = {"op": "gte", "left": 1, "right": 0}
        for _ in range(70):
            deep = {"op": "not", "arg": deep}
        self.assertFalse(self._condition(deep))
        wide = {
            "op": "and",
            "args": [{"op": "gte", "left": 1, "right": 0} for _ in range(40)],
        }
        self.assertFalse(self._condition(wide))


class TaskApiTests(APITestBase):
    def test_tasks_and_definition_crud(self) -> None:
        with self.client() as client:
            empty = client.get("/v1/me/tasks", headers=auth(TOKEN))
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.json()["tasks"], [])
            created = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "画一张", "description": "随便画", "difficulty": 2},
            )
            self.assertEqual(created.status_code, 200, created.text)
            definition = created.json()
            self.assertEqual(definition["difficulty"], 2)
            listed = client.get("/v1/me/task-definitions", headers=auth(TOKEN))
            self.assertEqual([row["id"] for row in listed.json()], [definition["id"]])
            patched = client.patch(
                f"/v1/me/task-definitions/{definition['id']}",
                headers=auth(TOKEN),
                json={"title": "新标题", "description": "", "difficulty": 3},
            )
            self.assertEqual(patched.status_code, 200, patched.text)
            self.assertEqual(patched.json()["title"], "新标题")
            tasks = client.get("/v1/me/tasks", headers=auth(TOKEN)).json()["tasks"]
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["title"], "新标题")
            self.assertEqual(tasks[0]["chest_tier"], 3)
            deleted = client.delete(
                f"/v1/me/task-definitions/{definition['id']}",
                headers=auth(TOKEN),
            )
            self.assertEqual(deleted.status_code, 204)
            self.assertEqual(
                client.get("/v1/me/task-definitions", headers=auth(TOKEN)).json(),
                [],
            )
            self.assertEqual(
                len(client.get("/v1/me/tasks", headers=auth(TOKEN)).json()["tasks"]),
                1,
            )

    def test_manual_complete_requires_image_and_returns_task(self) -> None:
        with self.client() as client:
            client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "画一张", "difficulty": 1},
            )
            task_id = client.get("/v1/me/tasks", headers=auth(TOKEN)).json()["tasks"][0]["id"]
            missing = client.post(
                f"/v1/me/tasks/{task_id}/complete", headers=auth(TOKEN)
            )
            self.assertEqual(missing.status_code, 422)
            wrong = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.txt", b"not an image", "text/plain")},
            )
            self.assertEqual(wrong.status_code, 415)
            huge = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.png", b"x" * (8 * 1024 * 1024 + 1), "image/png")},
            )
            self.assertEqual(huge.status_code, 413)
            done = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.png", image_bytes(), "image/png")},
            )
            self.assertEqual(done.status_code, 200, done.text)
            payload = done.json()["task"]
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["chest_status"], "available")
            self.assertIsNotNone(payload["proof_url"])
            proof = client.get(payload["proof_url"], headers=auth(TOKEN))
            self.assertEqual(proof.status_code, 200)
            self.assertEqual(proof.headers["cache-control"], "private, no-store")
            stored = list(
                (self.api_dir / "task-proofs" / "owner").glob(f"{task_id}.*")
            )
            self.assertEqual(len(stored), 1)
            mode = stat.S_IMODE(stored[0].stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_chest_claim_and_permissions(self) -> None:
        self.add_account("friend", "Friend", "friend-token-only")
        with self.client() as client:
            definition = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "画一张", "difficulty": 2},
            ).json()
            task_id = client.get("/v1/me/tasks", headers=auth(TOKEN)).json()["tasks"][0]["id"]
            done = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.webp", image_bytes("WEBP"), "image/webp")},
            )
            self.assertEqual(done.status_code, 200, done.text)
            claimed = client.post(
                f"/v1/me/tasks/{task_id}/chest", headers=auth(TOKEN)
            )
            self.assertEqual(claimed.status_code, 200, claimed.text)
            body = claimed.json()
            self.assertEqual(set(body), {"amount", "balance", "duplicate"})
            self.assertFalse(body["duplicate"])
            again = client.post(f"/v1/me/tasks/{task_id}/chest", headers=auth(TOKEN))
            self.assertTrue(again.json()["duplicate"])
            self.assertEqual(again.json()["amount"], body["amount"])
            with sqlite3.connect(self.game_db_path) as conn:
                row = conn.execute(
                    "SELECT reason, ref_type, ref_id, idempotency_key "
                    "FROM diamond_ledger ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(row, ("task_chest", "task", task_id, f"task-chest:{task_id}"))

            self.assertEqual(
                client.get(
                    f"/v1/me/tasks/{task_id}/proof",
                    headers=auth("friend-token-only"),
                ).status_code,
                404,
            )
            self.assertEqual(
                client.post(
                    f"/v1/me/tasks/{task_id}/chest",
                    headers=auth("friend-token-only"),
                ).status_code,
                404,
            )
            self.assertEqual(
                client.post(
                    f"/v1/me/tasks/{task_id}/complete",
                    headers=auth("friend-token-only"),
                    files={"file": ("proof.png", image_bytes(), "image/png")},
                ).status_code,
                404,
            )
            self.assertEqual(
                client.patch(
                    f"/v1/me/task-definitions/{definition['id']}",
                    headers=auth("friend-token-only"),
                    json={"title": "抢", "difficulty": 1},
                ).status_code,
                404,
            )
            self.assertEqual(
                client.delete(
                    f"/v1/me/task-definitions/{definition['id']}",
                    headers=auth("friend-token-only"),
                ).status_code,
                404,
            )

    def test_definition_validation_and_limit(self) -> None:
        with self.client() as client:
            bad = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "", "difficulty": 4},
            )
            self.assertEqual(bad.status_code, 422)
            for index in range(20):
                response = client.post(
                    "/v1/me/task-definitions",
                    headers=auth(TOKEN),
                    json={"title": f"任务 {index}", "difficulty": 1},
                )
                self.assertEqual(response.status_code, 200, response.text)
            over = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "多余", "difficulty": 1},
            )
            self.assertEqual(over.status_code, 422)

    def test_repair_task_appears_from_real_increment(self) -> None:
        with self.client() as client:
            response = client.post(
                "/v1/me/increments",
                headers=auth(TOKEN),
                json={
                    "event_id": "missed-day",
                    "seconds": 444,
                    "occurred_at": "2026-10-25T12:00:00+08:00",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            tasks = client.get("/v1/me/tasks", headers=auth(TOKEN)).json()["tasks"]
            repair = [task for task in tasks if task["source"] == "repair"]
            self.assertEqual(len(repair), 1)
            self.assertEqual(repair[0]["title"], "补断联 · 10/25")
            self.assertEqual(repair[0]["description"], "当天只拿到 74 XP；用余烬补上。")
            self.assertEqual(repair[0]["ends_at"], "2026-11-02T00:00:00+08:00")
            self.assertEqual(repair[0]["progress"], {"current": 0, "target": 1})
            self.assertEqual(repair[0]["missed_date"], "2026-10-25")


if __name__ == "__main__":
    unittest.main()
