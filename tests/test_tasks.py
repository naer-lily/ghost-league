from __future__ import annotations

import io
import json
import random
import sqlite3
import stat
import struct
import tempfile
import unittest
import zlib
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from ghost_league.game.store import SOURCE_HUMAN, GameStore
from ghost_league.game.tasks import (
    CHEST_TIERS,
    TaskNotFound,
    TaskStateRejected,
    chest_amount_range,
    checkin_condition,
    evaluate_condition,
    parse_chest_pool,
    parse_weekly_chain_config,
    repair_condition,
    roll_chest_amount,
    roll_chest_reward,
    roll_chest_tier,
    weekend_condition,
    weekly_chain_condition,
)
from ghost_league.schedule import TZ
from tests.test_api import APITestBase, auth, image_bytes

TOKEN = "test-token-only"


def ts(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def visible_tasks(store, user_id: str, now: datetime) -> list[dict]:
    """Task-list helpers from before check-in existed ignore that daily row."""

    return [
        task
        for task in store.list_visible_tasks(user_id, now)
        if task["source"] != "checkin"
    ]


def api_tasks(client, token: str = TOKEN) -> list[dict]:
    """Legacy task assertions ignore the always-on Ghost system rows."""

    return [
        task
        for task in client.get(
            "/v1/me/tasks", headers=auth(token)
        ).json()["tasks"]
        if task["source"] not in {"checkin", "weekly_chain"}
    ]


def api_all_tasks(client, token: str = TOKEN) -> list[dict]:
    return client.get("/v1/me/tasks", headers=auth(token)).json()["tasks"]


def heic_bytes(size: tuple[int, int] = (320, 180)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (40, 120, 200)).save(
        buffer, format="HEIF", quality=90
    )
    return buffer.getvalue()


def large_noise_bytes(
    fmt: str = "JPEG",
    size: tuple[int, int] = (1400, 1000),
    quality: int = 95,
) -> bytes:
    """Deterministic noisy photo that stays over 1MB after normal encoding."""

    rng = random.Random(11)
    image = Image.frombytes("RGB", size, rng.randbytes(size[0] * size[1] * 3))
    buffer = io.BytesIO()
    if fmt == "PNG":
        image.save(buffer, format=fmt)
    else:
        image.save(buffer, format=fmt, quality=quality)
    return buffer.getvalue()


def oversized_png_bytes() -> bytes:
    data = bytearray(image_bytes())
    struct.pack_into(">II", data, 16, 8001, 5001)
    crc = zlib.crc32(data[12:29]) & 0xFFFFFFFF
    struct.pack_into(">I", data, 29, crc)
    return bytes(data)


class TaskStoreBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GameStore(Path(self.temp.name) / "league.db")
        self.now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TZ)
        self.store.create_player(
            "u", kind="human", display_name="U", joined_week="2026-10-19", now=self.now
        )
        # Keep most lifecycle tests independent of the balance pools.  Pool
        # sampling itself is covered by the dedicated chest-pool tests.
        for pool, tier in (
            ("daily_1", 1),
            ("daily_2", 2),
            ("daily_3", 3),
            ("checkin", 1),
            ("repair", 1),
            ("weekend", 5),
        ):
            self.store.set_game_config(
                f"task_chest_pool_{pool}",
                json.dumps({str(i): 100 if i == tier else 0 for i in range(1, 6)}),
                now=self.now,
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
        tasks = visible_tasks(self.store, "u", self.now)
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
        before = visible_tasks(self.store, "u", self.now)[0]

        self.store.update_task_definition(
            "u",
            definition["id"],
            title="5 个 ghosting shape",
            description="只要有笔有纸就能做！",
            difficulty=3,
            now=self.now,
        )
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 0)
        after = visible_tasks(self.store, "u", self.now)[0]

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
        task = visible_tasks(self.store, "u", self.now)[0]
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
        after = visible_tasks(self.store, "u", self.now)[0]

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
            for task in visible_tasks(self.store, "u", self.now)
        }
        self.assertEqual(tiers, {1: 1, 2: 2, 3: 3})

    def test_reorder_controls_daily_order_ahead_of_repair_and_persists(self) -> None:
        first = self.store.create_task_definition(
            "u", title="A", difficulty=1, now=self.now
        )
        second = self.store.create_task_definition(
            "u", title="B", difficulty=1, now=self.now
        )
        self.assertEqual(first["sort_order"], 10)
        self.assertEqual(second["sort_order"], 20)
        self.store.ensure_user_tasks("u", self.now)
        self.assertEqual(
            [task["title"] for task in visible_tasks(self.store, "u", self.now)],
            ["A", "B"],
        )

        reordered = self.store.reorder_task_definitions(
            "u", [second["id"], first["id"]], now=self.now
        )
        self.assertEqual([row["title"] for row in reordered], ["B", "A"])
        self.assertEqual([row["sort_order"] for row in reordered], [10, 20])
        self.assertEqual(
            [row["title"] for row in visible_tasks(self.store, "u", self.now)],
            ["B", "A"],
        )

        self.add_activity("2026-10-29", 444)
        self.store.ensure_repair_tasks("u", self.now.date(), now=self.now)
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 0)
        tasks = visible_tasks(self.store, "u", self.now)
        self.assertEqual(
            [(task["title"], task["ends_at"]) for task in tasks],
            [
                ("B", "2026-11-05T00:00:00+08:00"),
                ("A", "2026-11-05T00:00:00+08:00"),
                ("补断联 · 10/29", "2026-11-06T00:00:00+08:00"),
            ],
        )

        reopened = GameStore(self.store.path)
        self.assertEqual(
            [row["title"] for row in reopened.list_task_definitions("u")],
            ["B", "A"],
        )
        self.assertEqual(
            [task["title"] for task in visible_tasks(reopened, "u", self.now)],
            ["B", "A", "补断联 · 10/29"],
        )

    def test_list_visible_tasks_keeps_stable_order_without_ui_grouping(self) -> None:
        for title in ("A", "B", "C", "D"):
            self.store.create_task_definition(
                "u", title=title, difficulty=1, now=self.now
            )
        self.store.ensure_user_tasks("u", self.now)
        tasks = {
            task["title"]: task
            for task in visible_tasks(self.store, "u", self.now)
        }

        self.store.complete_manual_task(
            "u",
            tasks["B"]["id"],
            proof_path="task-proofs/u/b.png",
            proof_mime="image/png",
            now=self.now,
        )
        self.store.claim_task_chest("u", tasks["B"]["id"], now=self.now)
        self.store.complete_manual_task(
            "u",
            tasks["D"]["id"],
            proof_path="task-proofs/u/d.png",
            proof_mime="image/png",
            now=self.now,
        )

        visible = visible_tasks(self.store, "u", self.now)
        self.assertEqual(
            [
                (
                    task["title"],
                    task["status"],
                    task["chest_status"],
                    task["sort_order"],
                )
                for task in visible
            ],
            [
                ("A", "active", "none", 10),
                ("B", "completed", "claimed", 20),
                ("C", "active", "none", 30),
                ("D", "completed", "available", 40),
            ],
        )

        self.add_activity("2026-10-29", 444)
        self.store.ensure_repair_tasks("u", self.now.date(), now=self.now)
        visible = visible_tasks(self.store, "u", self.now)
        self.assertEqual(
            [(task["title"], task["ends_at"], task["sort_order"]) for task in visible],
            [
                ("A", "2026-11-05T00:00:00+08:00", 10),
                ("B", "2026-11-05T00:00:00+08:00", 20),
                ("C", "2026-11-05T00:00:00+08:00", 30),
                ("D", "2026-11-05T00:00:00+08:00", 40),
                ("补断联 · 10/29", "2026-11-06T00:00:00+08:00", 0),
            ],
        )

    def test_completed_instance_keeps_title_and_sort_order(self) -> None:
        second = self.store.create_task_definition(
            "u", title="B", difficulty=1, now=self.now
        )
        first = self.store.create_task_definition(
            "u", title="A", difficulty=1, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        completed = self.store.get_task(
            "u",
            next(
                task["id"]
                for task in visible_tasks(self.store, "u", self.now)
                if task["title"] == "A"
            ),
        )
        self.store.complete_manual_task(
            "u",
            completed["id"],
            proof_path="task-proofs/u/a.png",
            proof_mime="image/png",
            now=self.now,
        )
        self.store.update_task_definition(
            "u",
            first["id"],
            title="A 新标题",
            description="新描述",
            difficulty=3,
            now=self.now,
        )
        self.store.reorder_task_definitions(
            "u", [first["id"], second["id"]], now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)

        stored = self.store.get_task("u", completed["id"])
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["title"], "A")
        self.assertEqual(stored["description"], "")
        self.assertEqual(stored["sort_order"], 20)

    def test_next_day_generates_new_instance(self) -> None:
        self.store.create_task_definition(
            "u", title="画一张", difficulty=1, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        tomorrow = self.now + timedelta(days=1)
        self.assertEqual(self.store.ensure_user_tasks("u", tomorrow), 1)
        tasks = visible_tasks(self.store, "u", tomorrow)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["starts_at"], "2026-11-05T00:00:00+08:00")
        self.assertEqual(tasks[0]["ends_at"], "2026-11-06T00:00:00+08:00")

    def test_completed_task_hides_and_forfeits_after_deadline(self) -> None:
        self.store.create_task_definition(
            "u", title="画一张", difficulty=2, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        task = visible_tasks(self.store, "u", self.now)[0]
        self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="task-proofs/u/x.png",
            proof_mime="image/png",
            now=self.now,
        )
        later = self.now + timedelta(days=1)
        self.assertEqual(visible_tasks(self.store, "u", later), [])
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
        self.assertEqual(len(visible_tasks(self.store, "u", self.now)), 1)
        tomorrow = self.now + timedelta(days=1)
        self.store.ensure_user_tasks("u", tomorrow)
        self.assertEqual(len(visible_tasks(self.store, "u", tomorrow)), 0)


class CheckinTaskTests(TaskStoreBase):
    def test_checkin_task_is_created_before_manual_and_auto_completes(self) -> None:
        self.store.create_task_definition(
            "u", title="画一张", difficulty=1, now=self.now
        )
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 1)
        tasks = self.store.list_visible_tasks("u", self.now)
        self.assertEqual([task["title"] for task in tasks], ["每日打卡", "画一张"])
        checkin = tasks[0]
        self.assertEqual(checkin["source"], "checkin")
        self.assertEqual(checkin["description"], "画满 10 分钟，开个小宝箱。")
        self.assertEqual(checkin["difficulty"], 1)
        self.assertEqual(checkin["chest_tier"], 1)
        self.assertEqual(checkin["sort_order"], 0)
        self.assertEqual(checkin["starts_at"], "2026-11-04T00:00:00+08:00")
        self.assertEqual(checkin["ends_at"], "2026-11-05T00:00:00+08:00")
        self.assertEqual(checkin["status"], "active")
        self.assertEqual(checkin["chest_status"], "none")
        self.assertEqual(checkin["progress"], {"current": 0, "target": 1})

        stored = self.store.get_task("u", checkin["id"])
        self.assertIsNone(stored["definition_id"])
        self.assertEqual(stored["system_key"], "checkin:2026-11-04")
        self.assertEqual(stored["completion_mode"], "dsl")
        self.assertEqual(
            json.loads(stored["condition_json"]), checkin_condition()
        )

        self.add_activity("2026-11-04", 600)
        completed = self.store.list_visible_tasks("u", self.now)[0]
        self.assertEqual(completed["id"], checkin["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["chest_status"], "available")
        self.assertEqual(completed["progress"], {"current": 1, "target": 1})

    def test_already_checked_in_user_sees_completed_after_deploy(self) -> None:
        self.add_activity("2026-11-04", 600)
        self.store.ensure_user_tasks("u", self.now)
        tasks = self.store.list_visible_tasks("u", self.now)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["source"], "checkin")
        self.assertEqual(tasks[0]["status"], "completed")
        self.assertEqual(tasks[0]["chest_status"], "available")

    def test_checkin_generation_is_idempotent_per_day(self) -> None:
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 0)
        self.assertEqual(self.store.ensure_user_tasks("u", self.now), 0)
        tomorrow = self.now + timedelta(days=1)
        self.assertEqual(self.store.ensure_user_tasks("u", tomorrow), 0)
        with self.store._reader() as conn:
            keys = [
                row["system_key"]
                for row in conn.execute(
                    "SELECT system_key FROM task_instances "
                    "WHERE source = 'checkin' ORDER BY system_key"
                )
            ]
        self.assertEqual(keys, ["checkin:2026-11-04", "checkin:2026-11-05"])

    def test_checkin_requires_verified_not_repaired(self) -> None:
        self.add_activity("2026-11-03", 444)
        self.grant_embers()
        self.store.repair_checkin(
            "u", "2026-11-03", idempotency_key="repair-1", now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        checkin = self.store.list_visible_tasks("u", self.now)[0]
        self.assertEqual(checkin["source"], "checkin")
        self.assertEqual(checkin["status"], "active")


class ManualChestTests(TaskStoreBase):
    def _completed_task(self) -> dict:
        self.store.create_task_definition("u", title="画一张", difficulty=2, now=self.now)
        self.store.ensure_user_tasks("u", self.now)
        task = visible_tasks(self.store, "u", self.now)[0]
        self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="task-proofs/u/x.png",
            proof_mime="image/png",
            now=self.now,
        )
        return visible_tasks(self.store, "u", self.now)[0]

    def test_completion_makes_chest_available(self) -> None:
        task = self._completed_task()
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["chest_status"], "available")
        self.assertIsNotNone(task["completed_at"])
        self.assertEqual(task["proof_url"], f"/v1/me/tasks/{task['id']}/proof")

    def test_chest_credits_diamonds_and_is_idempotent(self) -> None:
        self.store.set_game_config("task_chest_boost_chance", "0", now=self.now)
        task = self._completed_task()
        first = self.store.claim_task_chest("u", task["id"], now=self.now)
        low, high = chest_amount_range(2)
        self.assertIn(first["amount"], range(low, high + 1))
        self.assertFalse(first["duplicate"])
        self.assertEqual(first["balance"], 1000 + first["amount"])
        duplicate = self.store.claim_task_chest("u", task["id"], now=self.now)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["amount"], first["amount"])
        visible = visible_tasks(self.store, "u", self.now)
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
        task = visible_tasks(self.store, "u", self.now)[0]
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
        task = visible_tasks(self.store, "u", self.now)[0]
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
            [(1, 3, 6), (2, 8, 14), (3, 18, 30), (4, 45, 70), (5, 100, 100)],
        )
        ranges = [set(range(row["min"], row["max"] + 1)) for row in CHEST_TIERS]
        for index, current in enumerate(ranges):
            for other in ranges[index + 1 :]:
                self.assertFalse(current & other)
        self.assertEqual(roll_chest_amount(5, rng=lambda span: 0), 100)
        self.assertEqual(roll_chest_amount(5, rng=lambda span: span - 1), 100)


class ChestPoolTests(TaskStoreBase):
    DEFAULT_POOLS = {
        "checkin": (70, 25, 5, 0, 0),
        "daily_1": (55, 35, 10, 0, 0),
        "daily_2": (35, 35, 25, 5, 0),
        "daily_3": (20, 30, 35, 13, 2),
        "repair": (60, 30, 9, 1, 0),
        "weekend": (0, 15, 45, 30, 10),
    }

    @staticmethod
    def weights(*values: int) -> dict[int, int]:
        return {tier: values[tier - 1] for tier in range(1, 6)}

    def test_default_pools_draw_distinguishable_tiers(self) -> None:
        cases = {
            "checkin": {0: 1, 69: 1, 70: 2, 94: 2, 95: 3, 99: 3},
            "daily_1": {0: 1, 54: 1, 55: 2, 89: 2, 90: 3, 99: 3},
            "daily_2": {
                0: 1, 34: 1, 35: 2, 69: 2, 70: 3, 94: 3, 95: 4, 99: 4,
            },
            "daily_3": {
                0: 1, 19: 1, 20: 2, 49: 2, 50: 3,
                84: 3, 85: 4, 97: 4, 98: 5, 99: 5,
            },
            "repair": {0: 1, 59: 1, 60: 2, 89: 2, 90: 3, 98: 3, 99: 4},
            "weekend": {
                0: 2, 14: 2, 15: 3, 59: 3, 60: 4, 89: 4, 90: 5, 99: 5,
            },
        }
        for pool, expected in cases.items():
            weights = self.weights(*self.DEFAULT_POOLS[pool])
            self.assertEqual(sum(weights.values()), 100, pool)
            for pick, tier in expected.items():
                self.assertEqual(
                    roll_chest_tier(
                        weights, rng=lambda span, pick=pick: pick
                    ),
                    tier,
                    (pool, pick),
                )

    def test_invalid_pool_weights_are_rejected(self) -> None:
        self.assertIsNone(parse_chest_pool('{"1":50,"2":49}'))
        self.assertIsNone(parse_chest_pool('{"1":50,"2":50,"6":0}'))
        self.assertIsNone(parse_chest_pool('{"1":50,"2":50.0}'))
        self.assertIsNone(parse_chest_pool('{"1":true,"2":99}'))
        self.assertIsNone(parse_chest_pool('{"1":101,"2":-1}'))
        self.assertIsNone(parse_chest_pool("not-json"))
        self.assertIsNone(parse_chest_pool(None))
        self.assertEqual(
            parse_chest_pool('{"1":70,"2":25,"3":5}'),
            {1: 70, 2: 25, 3: 5, 4: 0, 5: 0},
        )
        with self.assertRaises(ValueError):
            roll_chest_tier({1: 50, 2: 49, 3: 0, 4: 0, 5: 0})

    def test_invalid_pool_completion_uses_conservative_fallback(self) -> None:
        self.store.set_game_config(
            "task_chest_pool_daily_2", '{"1":50,"2":49}', now=self.now
        )
        self.store.create_task_definition(
            "u", title="bad pool", difficulty=2, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        task = next(
            row
            for row in visible_tasks(self.store, "u", self.now)
            if row["title"] == "bad pool"
        )
        completed = self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="x",
            proof_mime="image/png",
            now=self.now,
        )
        self.assertEqual(completed["chest_tier"], 1)
        self.assertEqual(completed["chest_pool"], "daily_2")

    def test_completion_rolls_once_and_refresh_does_not_reroll(self) -> None:
        self.store.set_game_config(
            "task_chest_pool_daily_2",
            '{"1":0,"2":0,"3":0,"4":0,"5":100}',
            now=self.now,
        )
        self.store.create_task_definition(
            "u", title="star pool", difficulty=2, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        task = next(
            row
            for row in visible_tasks(self.store, "u", self.now)
            if row["title"] == "star pool"
        )
        completed = self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="x",
            proof_mime="image/png",
            now=self.now,
        )
        self.assertEqual(completed["chest_tier"], 5)
        self.store.set_game_config(
            "task_chest_pool_daily_2", '{"1":100,"2":0,"3":0,"4":0,"5":0}',
            now=self.now,
        )
        refreshed = next(
            row
            for row in visible_tasks(self.store, "u", self.now)
            if row["id"] == task["id"]
        )
        self.assertEqual(refreshed["chest_tier"], 5)

    def test_old_completed_instance_keeps_its_tier(self) -> None:
        self.store.create_task_definition(
            "u", title="old", difficulty=2, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        task = next(
            row
            for row in visible_tasks(self.store, "u", self.now)
            if row["title"] == "old"
        )
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE task_instances SET status = 'completed', "
                "chest_status = 'available', chest_tier = 4, "
                "chest_pool = '' WHERE id = ?",
                (task["id"],),
            )
        refreshed = next(
            row
            for row in visible_tasks(self.store, "u", self.now)
            if row["id"] == task["id"]
        )
        self.assertEqual(refreshed["chest_tier"], 4)


class StarChestTests(TaskStoreBase):
    def _complete_daily(self, title: str = "A") -> str:
        self.store.create_task_definition(
            "u", title=title, difficulty=2, now=self.now
        )
        self.store.ensure_user_tasks("u", self.now)
        task = next(
            row
            for row in visible_tasks(self.store, "u", self.now)
            if row["title"] == title
        )
        self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path="x",
            proof_mime="image/png",
            now=self.now,
        )
        return task["id"]

    def test_star_chest_creates_one_normal_star_and_replays_it(self) -> None:
        self.store.set_game_config(
            "task_chest_pool_daily_2",
            '{"1":0,"2":0,"3":0,"4":0,"5":100}',
            now=self.now,
        )
        self.store.set_game_config("task_chest_star_chance", "100", now=self.now)
        task_id = self._complete_daily()
        first = self.store.claim_task_chest(
            "u", task_id, now=self.now, rng=lambda span: 0
        )
        self.assertEqual(first["reward_type"], "star")
        self.assertEqual(first["amount"], 0)
        self.assertIsNone(first["boost_minutes"])
        star = first["star"]
        self.assertIsNotNone(star)
        self.assertEqual(star["kind"], "normal")
        self.assertIsNone(star["season_key"])
        with self.store._reader() as conn:
            row = conn.execute(
                "SELECT source, kind, season_key, price_diamonds "
                "FROM player_stars WHERE id = ?",
                (star["id"],),
            ).fetchone()
        self.assertEqual(
            (row["source"], row["kind"], row["season_key"],
             row["price_diamonds"]),
            ("task_chest", "normal", None, 0),
        )
        duplicate = self.store.claim_task_chest(
            "u", task_id, now=self.now, rng=lambda span: 0
        )
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["reward_type"], "star")
        self.assertEqual(duplicate["star"]["id"], star["id"])
        payload = self.store.get_task_payload("u", task_id, now=self.now)
        self.assertEqual(payload["chest_reward_type"], "star")
        self.assertEqual(payload["chest_star"]["id"], star["id"])
        with self.store._reader() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM player_stars"
            ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_star_chest_miss_pays_100_diamonds(self) -> None:
        self.store.set_game_config(
            "task_chest_pool_daily_2",
            '{"1":0,"2":0,"3":0,"4":0,"5":100}',
            now=self.now,
        )
        self.store.set_game_config("task_chest_star_chance", "0", now=self.now)
        task_id = self._complete_daily()
        result = self.store.claim_task_chest(
            "u", task_id, now=self.now, rng=lambda span: 0
        )
        self.assertEqual(result["reward_type"], "diamonds")
        self.assertEqual(result["amount"], 100)
        self.assertIsNone(result["star"])


class ChestRewardTests(TaskStoreBase):
    def _complete(self, title: str, *, now: datetime | None = None) -> str:
        stamp = now or self.now
        self.store.create_task_definition(
            "u", title=title, difficulty=2, now=stamp
        )
        self.store.ensure_user_tasks("u", stamp)
        task = next(
            row
            for row in visible_tasks(self.store, "u", stamp)
            if row["title"] == title
        )
        self.store.complete_manual_task(
            "u",
            task["id"],
            proof_path=f"task-proofs/u/{task['id']}.png",
            proof_mime="image/png",
            now=stamp,
        )
        return task["id"]

    def test_roll_chest_reward_has_fixed_diamond_and_boost_branches(self) -> None:
        diamond = roll_chest_reward(
            1,
            boost_chance=20,
            boost_minutes=25,
            rng=lambda span: span - 1,
        )
        self.assertEqual(
            diamond,
            {"reward_type": "diamonds", "amount": 6, "boost_minutes": None},
        )
        boost = roll_chest_reward(
            1,
            boost_chance=100,
            boost_minutes=25,
            rng=lambda span: 0,
        )
        self.assertEqual(
            boost,
            {"reward_type": "boost", "amount": 0, "boost_minutes": 25},
        )
        self.assertEqual(
            roll_chest_reward(
                1, boost_chance=0, boost_minutes=25, rng=lambda span: 0
            )["reward_type"],
            "diamonds",
        )

    def test_high_tiers_never_roll_boost(self) -> None:
        for tier in (4, 5):
            reward = roll_chest_reward(
                tier,
                boost_chance=100,
                boost_minutes=25,
                rng=lambda span: 0,
            )
            self.assertEqual(reward["reward_type"], "diamonds")
            self.assertIsNone(reward["boost_minutes"])
        self.assertEqual(
            roll_chest_reward(5, boost_chance=100, rng=lambda span: 0)["amount"],
            100,
        )

    def test_boost_is_cut_off_after_the_local_hour(self) -> None:
        allowed = roll_chest_reward(
            2,
            boost_chance=100,
            boost_minutes=25,
            boost_allowed=True,
            rng=lambda span: 0,
        )
        blocked = roll_chest_reward(
            2,
            boost_chance=100,
            boost_minutes=25,
            boost_allowed=False,
            rng=lambda span: 0,
        )
        self.assertEqual(allowed["reward_type"], "boost")
        self.assertEqual(blocked["reward_type"], "diamonds")
        self.assertEqual(blocked["amount"], 8)

    def test_star_tier_hits_the_star_branch_with_fixed_rng(self) -> None:
        star = roll_chest_reward(
            5, star_chance=10, boost_chance=100, rng=lambda span: 0
        )
        self.assertEqual(
            star,
            {"reward_type": "star", "amount": 0, "boost_minutes": None},
        )
        miss = roll_chest_reward(
            5,
            star_chance=10,
            boost_chance=100,
            rng=lambda span: 10 if span == 100 else 0,
        )
        self.assertEqual(miss["reward_type"], "diamonds")
        self.assertEqual(miss["amount"], 100)

    def test_boost_cutoff_and_high_tiers_fail_closed_to_diamonds(self) -> None:
        self.store.set_game_config("task_chest_boost_chance", "100", now=self.now)
        self.store.set_game_config("task_chest_boost_minutes", "25", now=self.now)
        self.store.set_game_config(
            "task_chest_pool_daily_2", '{"1":0,"2":100,"3":0,"4":0,"5":0}',
            now=self.now,
        )
        early = datetime(2026, 11, 4, 20, 0, 0, tzinfo=TZ)
        early_id = self._complete("early", now=early)
        early_result = self.store.claim_task_chest(
            "u", early_id, now=early, rng=lambda span: 0
        )
        self.assertEqual(early_result["reward_type"], "boost")

        late = datetime(2026, 11, 4, 21, 0, 0, tzinfo=TZ)
        late_id = self._complete("late", now=late)
        late_result = self.store.claim_task_chest(
            "u", late_id, now=late, rng=lambda span: 0
        )
        self.assertEqual(late_result["reward_type"], "diamonds")
        self.assertIsNone(late_result["boost_minutes"])
        self.assertIn(late_result["amount"], range(8, 15))

        self.store.set_game_config(
            "task_chest_pool_daily_2", '{"1":0,"2":0,"3":0,"4":100,"5":0}',
            now=self.now,
        )
        gold_id = self._complete("gold", now=self.now)
        gold_result = self.store.claim_task_chest(
            "u", gold_id, now=self.now, rng=lambda span: 0
        )
        self.assertEqual(gold_result["reward_type"], "diamonds")
        self.assertIn(gold_result["amount"], range(45, 71))

    def test_boost_chest_extends_buff_and_never_writes_diamond_ledger(
        self,
    ) -> None:
        self.store.set_game_config("task_chest_boost_chance", "100", now=self.now)
        self.store.set_game_config("task_chest_boost_minutes", "25", now=self.now)
        first_id = self._complete("A")
        first = self.store.claim_task_chest(
            "u", first_id, now=self.now, rng=lambda span: 0
        )
        self.assertEqual(first["reward_type"], "boost")
        self.assertEqual(first["amount"], 0)
        self.assertEqual(first["boost_minutes"], 25)
        self.assertFalse(first["duplicate"])
        self.assertEqual(
            first["diamond_boost"]["expires_at"], "2026-11-04T12:25:00+08:00"
        )
        self.assertEqual(self.store.diamond_ledger("u"), [])

        later = self.now + timedelta(minutes=10)
        duplicate = self.store.claim_task_chest(
            "u", first_id, now=later, rng=lambda span: 0
        )
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["reward_type"], "boost")
        self.assertEqual(duplicate["amount"], 0)
        self.assertEqual(duplicate["boost_minutes"], 25)
        self.assertEqual(
            duplicate["diamond_boost"]["expires_at"],
            "2026-11-04T12:25:00+08:00",
        )

        second_id = self._complete("B", now=later)
        second = self.store.claim_task_chest(
            "u", second_id, now=later, rng=lambda span: 0
        )
        self.assertEqual(second["reward_type"], "boost")
        self.assertEqual(
            second["diamond_boost"]["expires_at"],
            "2026-11-04T12:50:00+08:00",
        )
        self.assertEqual(self.store.diamond_ledger("u"), [])

        stored = next(
            task
            for task in self.store.list_visible_tasks("u", later)
            if task["id"] == first_id
        )
        self.assertEqual(stored["chest_reward_type"], "boost")
        self.assertEqual(stored["chest_boost_minutes"], 25)
        self.assertIsNone(stored["chest_amount"])

    def test_boost_chest_fails_closed_when_config_is_invalid(self) -> None:
        self.store.set_game_config("task_chest_boost_chance", "bogus", now=self.now)
        task_id = self._complete("A")
        result = self.store.claim_task_chest("u", task_id, now=self.now)
        self.assertEqual(result["reward_type"], "diamonds")
        self.assertIsNone(result["boost_minutes"])
        self.assertIn(result["amount"], range(8, 15))
        self.assertEqual(len(self.store.diamond_ledger("u")), 1)

    def test_boost_chest_missing_config_fails_closed_to_diamonds(self) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM game_config "
                "WHERE key IN ('task_chest_boost_chance', "
                "'task_chest_boost_minutes')"
            )
        task_id = self._complete("A")
        result = self.store.claim_task_chest("u", task_id, now=self.now)
        self.assertEqual(result["reward_type"], "diamonds")
        self.assertIsNone(result["boost_minutes"])
        self.assertEqual(len(self.store.diamond_ledger("u")), 1)


class RepairTaskTests(TaskStoreBase):
    def test_today_is_not_a_repair_day(self) -> None:
        self.add_activity("2026-11-04", 444)
        self.assertEqual(self.store.ensure_repair_tasks("u", self.now.date(), now=self.now), 0)
        self.assertEqual(visible_tasks(self.store, "u", self.now), [])

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
        tasks = visible_tasks(self.store, "u", self.now)
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
        task = visible_tasks(self.store, "u", self.now)[0]
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
        task = visible_tasks(self.store, "u", self.now)[0]
        self.grant_embers()
        self.store.repair_checkin("u", "2026-10-29", idempotency_key="repair-1", now=self.now)
        completed = visible_tasks(self.store, "u", self.now)[0]
        self.assertEqual(completed["id"], task["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["chest_status"], "available")
        self.assertEqual(completed["progress"], {"current": 1, "target": 1})

    def test_repair_task_expires_unclaimed(self) -> None:
        self.add_activity("2026-10-29", 444)
        self.store.ensure_repair_tasks("u", self.now.date(), now=self.now)
        task = visible_tasks(self.store, "u", self.now)[0]
        self.grant_embers()
        self.store.repair_checkin("u", "2026-10-29", idempotency_key="repair-1", now=self.now)
        completed = visible_tasks(self.store, "u", self.now)[0]
        self.assertEqual(completed["chest_status"], "available")
        later = datetime(2026, 11, 6, 0, 0, 0, tzinfo=TZ)
        self.assertEqual(visible_tasks(self.store, "u", later), [])
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
        task = visible_tasks(self.store, "u", saturday)[0]
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
        task = visible_tasks(self.store, "u", sunday)[0]
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
        task = visible_tasks(self.store, "u", sunday)[0]
        self.assertEqual(task["status"], "active")
        self.assertEqual(task["progress"], {"current": 500, "target": 1000})
        self.add_activity("2026-11-01", 3000, event_id="sun")
        task = visible_tasks(self.store, "u", sunday)[0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], {"current": 1000, "target": 1000})
        monday = datetime(2026, 11, 2, 0, 0, 0, tzinfo=TZ)
        self.assertEqual(visible_tasks(self.store, "u", monday), [])
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


class WeeklyChainTaskTests(TaskStoreBase):
    def chain_tasks(self, now: datetime | None = None) -> list[dict]:
        stamp = now or self.now
        return [
            task
            for task in self.store.list_visible_tasks("u", stamp)
            if task["source"] == "weekly_chain"
        ]

    def add_weekly_xp(
        self,
        xp: int,
        *,
        day: str = "2026-11-04",
        tag: str = "a",
    ) -> None:
        self.add_activity(day, xp * 6, event_id=f"weekly-{day}-{xp}-{tag}")

    def current_chain_task(self, now: datetime | None = None) -> dict:
        tasks = self.chain_tasks(now)
        unclaimed = [
            task
            for task in tasks
            if task["status"] == "active"
            or task["chest_status"] == "available"
        ]
        self.assertEqual(len(unclaimed), 1, tasks)
        return unclaimed[0]

    def claim(self, task_id: str, now: datetime | None = None) -> dict:
        return self.store.claim_task_chest(
            "u", task_id, now=now or self.now, rng=lambda span: 0
        )

    def run_chain_to_end(self, *, week_now: datetime | None = None) -> None:
        stamp = week_now or self.now
        for step in range(1, 5):
            self.assertEqual(
                self.store.ensure_weekly_chain_tasks("u", stamp), 1, step
            )
            task = self.current_chain_task(stamp)
            self.assertEqual(
                task["title"], f"本周 {[1000, 2000, 3000, 5000][step - 1]} XP"
            )
            self.claim(task["id"], now=stamp)

    def test_stage_one_is_created_once_with_configured_fields(self) -> None:
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 1)
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 0)
        tasks = self.chain_tasks()
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["source"], "weekly_chain")
        self.assertEqual(task["title"], "本周 1000 XP")
        self.assertEqual(task["chest_pool"], "weekly_chain_1")
        self.assertEqual(task["status"], "active")
        self.assertEqual(task["progress"], {"current": 0, "target": 1000})
        self.assertEqual(task["starts_at"], "2026-11-02T00:00:00+08:00")
        self.assertEqual(task["ends_at"], "2026-11-09T00:00:00+08:00")
        self.assertIsNone(task["missed_date"])
        with self.store._reader() as conn:
            row = conn.execute(
                "SELECT system_key, completion_mode, condition_json "
                "FROM task_instances WHERE id = ?",
                (task["id"],),
            ).fetchone()
        self.assertEqual(row["system_key"], "weekly_chain:2026-11-02:1")
        self.assertEqual(row["completion_mode"], "dsl")
        self.assertEqual(
            json.loads(row["condition_json"]), weekly_chain_condition(1000)
        )

    def test_current_week_xp_backfills_and_completes_stage(self) -> None:
        self.add_weekly_xp(1000)
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 1)
        task = self.chain_tasks()[0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["chest_status"], "available")
        self.assertEqual(task["progress"], {"current": 1000, "target": 1000})

    def test_completed_unclaimed_stage_blocks_next_until_claimed(self) -> None:
        self.add_weekly_xp(1000)
        self.store.ensure_weekly_chain_tasks("u", self.now)
        first = self.chain_tasks()[0]
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["chest_status"], "available")

        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 0)
        self.assertEqual(len(self.chain_tasks()), 1)

        self.claim(first["id"])
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 1)
        tasks = self.chain_tasks()
        self.assertEqual(len(tasks), 2)
        by_step = {task["title"]: task for task in tasks}
        self.assertEqual(by_step["本周 1000 XP"]["chest_status"], "claimed")
        second = by_step["本周 2000 XP"]
        self.assertEqual(second["status"], "active")
        self.assertEqual(second["chest_pool"], "weekly_chain_2")
        self.assertEqual(second["progress"], {"current": 1000, "target": 2000})
        # One active stage only, no duplicated next stage.
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 0)
        self.assertEqual(len(self.chain_tasks()), 2)

    def test_four_stages_end_without_a_fifth(self) -> None:
        self.add_weekly_xp(5000)
        self.run_chain_to_end()
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 0)
        tasks = self.chain_tasks()
        self.assertEqual(len(tasks), 4)
        self.assertEqual(
            [task["title"] for task in tasks],
            ["本周 1000 XP", "本周 2000 XP", "本周 3000 XP", "本周 5000 XP"],
        )
        self.assertEqual({task["chest_status"] for task in tasks}, {"claimed"})
        self.assertEqual(
            {task["chest_pool"] for task in tasks},
            {
                "weekly_chain_1",
                "weekly_chain_2",
                "weekly_chain_3",
                "weekly_chain_4",
            },
        )

    def test_next_week_starts_a_fresh_chain(self) -> None:
        self.add_weekly_xp(5000)
        self.run_chain_to_end()
        next_monday = datetime(2026, 11, 9, 12, 0, 0, tzinfo=TZ)
        self.assertEqual(
            self.store.ensure_weekly_chain_tasks("u", next_monday), 1
        )
        tasks = self.chain_tasks(next_monday)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "本周 1000 XP")
        self.assertEqual(tasks[0]["status"], "active")
        self.assertEqual(tasks[0]["starts_at"], "2026-11-09T00:00:00+08:00")
        self.assertEqual(tasks[0]["ends_at"], "2026-11-16T00:00:00+08:00")
        with self.store._reader() as conn:
            keys = [
                row["system_key"]
                for row in conn.execute(
                    "SELECT system_key FROM task_instances "
                    "WHERE source = 'weekly_chain' ORDER BY system_key"
                )
            ]
        self.assertEqual(
            keys,
            [
                "weekly_chain:2026-11-02:1",
                "weekly_chain:2026-11-02:2",
                "weekly_chain:2026-11-02:3",
                "weekly_chain:2026-11-02:4",
                "weekly_chain:2026-11-09:1",
            ],
        )

    def test_config_changes_apply_to_targets_and_pools(self) -> None:
        self.store.set_game_config(
            "task_chain_weekly",
            json.dumps(
                {
                    "stages": [
                        {"target_xp": 100, "chest_pool": "weekly_chain_1"},
                        {"target_xp": 250, "chest_pool": "weekly_chain_2"},
                    ]
                }
            ),
            now=self.now,
        )
        # Star-only first pool proves the configured pool row is used.
        self.store.set_game_config(
            "task_chest_pool_weekly_chain_1",
            '{"1":0,"2":0,"3":0,"4":0,"5":100}',
            now=self.now,
        )
        self.add_weekly_xp(120)
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 1)
        first = self.chain_tasks()[0]
        self.assertEqual(first["title"], "本周 100 XP")
        self.assertEqual(first["progress"], {"current": 120, "target": 100})
        self.assertEqual(first["chest_tier"], 5)
        self.claim(first["id"])

        # The next stage is materialised from the latest stage table.
        self.store.set_game_config(
            "task_chain_weekly",
            json.dumps(
                {
                    "stages": [
                        {"target_xp": 100, "chest_pool": "weekly_chain_1"},
                        {"target_xp": 400, "chest_pool": "weekly_chain_2"},
                    ]
                }
            ),
            now=self.now,
        )
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 1)
        second = [
            task
            for task in self.chain_tasks()
            if task["chest_status"] == "none"
        ][0]
        self.assertEqual(second["title"], "本周 400 XP")
        self.assertEqual(second["chest_pool"], "weekly_chain_2")
        self.assertEqual(second["progress"], {"current": 120, "target": 400})

    def test_invalid_or_missing_config_falls_back_to_default_stages(self) -> None:
        for raw in (
            "not-json",
            "[]",
            '{"stages":[]}',
            '{"stages":[{"target_xp":0,"chest_pool":"weekly_chain_1"}]}',
            '{"stages":[{"target_xp":2000,"chest_pool":"weekly_chain_2"},'
            '{"target_xp":1000,"chest_pool":"weekly_chain_1"}]}',
            '{"stages":[{"target_xp":100,"chest_pool":" "}]}',
        ):
            stages = parse_weekly_chain_config(raw)
            self.assertEqual(
                [stage["target_xp"] for stage in stages],
                [1000, 2000, 3000, 5000],
                raw,
            )

        self.store.set_game_config(
            "task_chain_weekly", '{"stages":[]}', now=self.now
        )
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", self.now), 1)
        self.assertEqual(self.chain_tasks()[0]["title"], "本周 1000 XP")

        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM game_config WHERE key = 'task_chain_weekly'"
            )
        other = datetime(2026, 11, 10, 12, 0, 0, tzinfo=TZ)
        self.assertEqual(self.store.ensure_weekly_chain_tasks("u", other), 1)
        self.assertEqual(self.chain_tasks(other)[0]["title"], "本周 1000 XP")

    def test_missing_or_invalid_weekly_pool_fails_closed(self) -> None:
        self.store.set_game_config(
            "task_chest_pool_weekly_chain_1", '{"1":50,"2":49}', now=self.now
        )
        self.add_weekly_xp(1000)
        self.store.ensure_weekly_chain_tasks("u", self.now)
        first = self.chain_tasks()[0]
        self.assertEqual(first["chest_tier"], 1)
        self.claim(first["id"])

        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM game_config "
                "WHERE key = 'task_chest_pool_weekly_chain_1'"
            )
        self.add_activity("2026-11-10", 6000, event_id="weekly-next-week")
        other = datetime(2026, 11, 10, 12, 0, 0, tzinfo=TZ)
        self.store.ensure_weekly_chain_tasks("u", other)
        self.assertEqual(self.chain_tasks(other)[0]["chest_tier"], 1)


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
            self.assertEqual(api_tasks(client), [])
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
            tasks = api_tasks(client)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["title"], "新标题")
            self.assertEqual(tasks[0]["chest_tier"], 3)
            self.assertEqual(tasks[0]["sort_order"], 10)
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
                len(api_tasks(client)),
                1,
            )

    def test_reorder_endpoint_controls_tasks_and_survives_restart(self) -> None:
        self.clock["now"] = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TZ)
        self.add_account("friend", "Friend", "friend-token-only")
        with self.client() as client:
            first = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "A", "difficulty": 1},
            ).json()
            second = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "B", "difficulty": 1},
            ).json()
            inactive = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "C", "difficulty": 1},
            ).json()
            friend = client.post(
                "/v1/me/task-definitions",
                headers=auth("friend-token-only"),
                json={"title": "Friend", "difficulty": 1},
            ).json()
            self.assertEqual(first["sort_order"], 10)
            self.assertEqual(second["sort_order"], 20)
            self.assertEqual(
                client.delete(
                    f"/v1/me/task-definitions/{inactive['id']}",
                    headers=auth(TOKEN),
                ).status_code,
                204,
            )
            self.assertEqual(
                client.post(
                    "/v1/me/increments",
                    headers=auth(TOKEN),
                    json={
                        "event_id": "missed-order-day",
                        "seconds": 444,
                        "occurred_at": "2026-10-29T12:00:00+08:00",
                    },
                ).status_code,
                200,
            )
            before = api_tasks(client)
            self.assertEqual(
                [
                    (task["title"], task["ends_at"], task["sort_order"])
                    for task in before
                ],
                [
                    ("A", "2026-11-05T00:00:00+08:00", 10),
                    ("B", "2026-11-05T00:00:00+08:00", 20),
                    ("补断联 · 10/29", "2026-11-06T00:00:00+08:00", 0),
                ],
            )

            reordered = client.put(
                "/v1/me/task-definitions/order",
                headers=auth(TOKEN),
                json={"ids": [second["id"], first["id"]]},
            )
            self.assertEqual(reordered.status_code, 200, reordered.text)
            self.assertEqual(
                [(row["title"], row["sort_order"]) for row in reordered.json()],
                [("B", 10), ("A", 20)],
            )
            tasks = api_tasks(client)
            self.assertEqual(
                [
                    (task["title"], task["ends_at"], task["sort_order"])
                    for task in tasks
                ],
                [
                    ("B", "2026-11-05T00:00:00+08:00", 10),
                    ("A", "2026-11-05T00:00:00+08:00", 20),
                    ("补断联 · 10/29", "2026-11-06T00:00:00+08:00", 0),
                ],
            )

            for ids, expected in (
                (["td_missing"], 404),
                ([friend["id"]], 404),
                ([inactive["id"]], 404),
                ([second["id"], second["id"]], 422),
            ):
                response = client.put(
                    "/v1/me/task-definitions/order",
                    headers=auth(TOKEN),
                    json={"ids": ids},
                )
                self.assertEqual(response.status_code, expected, response.text)

        with self.client() as client:
            definitions = client.get(
                "/v1/me/task-definitions", headers=auth(TOKEN)
            ).json()
            self.assertEqual(
                [(row["title"], row["sort_order"]) for row in definitions],
                [("B", 10), ("A", 20)],
            )
            tasks = api_tasks(client)
            self.assertEqual(
                [task["title"] for task in tasks],
                ["B", "A", "补断联 · 10/29"],
            )

    def test_task_list_keeps_stable_order_after_chest_claim(self) -> None:
        self.clock["now"] = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TZ)
        with self.client() as client:
            for title in ("A", "B", "C"):
                self.assertEqual(
                    client.post(
                        "/v1/me/task-definitions",
                        headers=auth(TOKEN),
                        json={"title": title, "difficulty": 1},
                    ).status_code,
                    200,
                )
            by_title = {
                task["title"]: task
                for task in api_tasks(client)
            }
            completed = client.post(
                f"/v1/me/tasks/{by_title['B']['id']}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.png", image_bytes(), "image/png")},
            )
            self.assertEqual(completed.status_code, 200, completed.text)
            claimed = client.post(
                f"/v1/me/tasks/{by_title['B']['id']}/chest",
                headers=auth(TOKEN),
            )
            self.assertEqual(claimed.status_code, 200, claimed.text)

            visible = api_tasks(client)
            self.assertEqual(
                [
                    (
                        task["title"],
                        task["status"],
                        task["chest_status"],
                        task["sort_order"],
                    )
                    for task in visible
                ],
                [
                    ("A", "active", "none", 10),
                    ("B", "completed", "claimed", 20),
                    ("C", "active", "none", 30),
                ],
            )

    def test_weekly_chain_is_created_by_tasks_endpoint_and_advances(self) -> None:
        self.clock["now"] = datetime(2026, 11, 4, 12, 0, 0, tzinfo=TZ)
        with self.client() as client:
            increment = self.post_increment(
                client,
                event_id="weekly-chain-api",
                seconds=7200,
                occurred_at="2026-11-04T11:00:00+08:00",
            )
            self.assertEqual(increment.status_code, 200, increment.text)
            chain = [
                task for task in api_all_tasks(client)
                if task["source"] == "weekly_chain"
            ]
            self.assertEqual(len(chain), 1)
            first = chain[0]
            self.assertEqual(first["title"], "本周 1000 XP")
            self.assertEqual(first["status"], "completed")
            self.assertEqual(first["chest_status"], "available")
            self.assertEqual(
                first["progress"], {"current": 1200, "target": 1000}
            )

            claimed = client.post(
                f"/v1/me/tasks/{first['id']}/chest",
                headers=auth(TOKEN),
            )
            self.assertEqual(claimed.status_code, 200, claimed.text)

            chain = [
                task for task in api_all_tasks(client)
                if task["source"] == "weekly_chain"
            ]
            self.assertEqual(
                [task["title"] for task in chain],
                ["本周 1000 XP", "本周 2000 XP"],
            )
            self.assertEqual(chain[0]["chest_status"], "claimed")
            self.assertEqual(chain[1]["status"], "active")
            self.assertEqual(
                chain[1]["progress"], {"current": 1200, "target": 2000}
            )

    def test_manual_complete_requires_image_and_returns_task(self) -> None:
        with self.client() as client:
            client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "画一张", "difficulty": 1},
            )
            task_id = api_tasks(client)[0]["id"]
            missing = client.post(
                f"/v1/me/tasks/{task_id}/complete", headers=auth(TOKEN)
            )
            self.assertEqual(missing.status_code, 422)
            empty = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.png", b"", "image/png")},
            )
            self.assertEqual(empty.status_code, 415)
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
            oversized = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={
                    "file": ("proof.png", oversized_png_bytes(), "image/png")
                },
            )
            self.assertEqual(oversized.status_code, 415)
            source = image_bytes()
            done = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.png", source, "image/png")},
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
            self.assertEqual(stored[0].suffix, ".png")
            self.assertEqual(stored[0].read_bytes(), source)
            mode = stat.S_IMODE(stored[0].stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_manual_complete_converts_heic_to_jpeg_proof(self) -> None:
        with self.client() as client:
            created = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "拍一张", "difficulty": 1},
            )
            self.assertEqual(created.status_code, 200, created.text)
            task_id = api_tasks(client)[0]["id"]
            source = heic_bytes()
            done = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.heic", source, "image/heic")},
            )
            self.assertEqual(done.status_code, 200, done.text)
            payload = done.json()["task"]
            self.assertEqual(payload["status"], "completed")
            proof = client.get(payload["proof_url"], headers=auth(TOKEN))
            self.assertEqual(proof.status_code, 200)
            self.assertEqual(proof.headers["content-type"], "image/jpeg")

            stored = list(
                (self.api_dir / "task-proofs" / "owner").glob(f"{task_id}.*")
            )
            self.assertEqual([path.suffix for path in stored], [".jpg"])
            stored_bytes = stored[0].read_bytes()
            self.assertNotEqual(stored_bytes, source)
            with Image.open(io.BytesIO(stored_bytes)) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (320, 180))

    def test_large_proofs_are_compressed_to_one_megabyte(self) -> None:
        formats = (
            ("JPEG", "proof.jpeg", "image/jpeg"),
            ("PNG", "proof.png", "image/png"),
            ("WEBP", "proof.webp", "image/webp"),
            ("HEIF", "proof.heic", "image/heic"),
        )
        with self.client() as client:
            for fmt, filename, mime in formats:
                with self.subTest(fmt=fmt):
                    source = large_noise_bytes(fmt)
                    self.assertGreater(len(source), 1_000_000)
                    self.assertLess(len(source), 8 * 1024 * 1024)
                    title = f"大图 {fmt}"
                    created = client.post(
                        "/v1/me/task-definitions",
                        headers=auth(TOKEN),
                        json={"title": title, "difficulty": 1},
                    )
                    self.assertEqual(created.status_code, 200, created.text)
                    tasks = api_tasks(client)
                    task = next(row for row in tasks if row["title"] == title)
                    done = client.post(
                        f"/v1/me/tasks/{task['id']}/complete",
                        headers=auth(TOKEN),
                        files={"file": (filename, source, mime)},
                    )
                    self.assertEqual(done.status_code, 200, done.text)
                    proof = client.get(
                        done.json()["task"]["proof_url"], headers=auth(TOKEN)
                    )
                    self.assertEqual(proof.status_code, 200)
                    self.assertEqual(proof.headers["content-type"], "image/jpeg")
                    stored = list(
                        (self.api_dir / "task-proofs" / "owner").glob(
                            f"{task['id']}.*"
                        )
                    )
                    self.assertEqual([path.suffix for path in stored], [".jpg"])
                    stored_bytes = stored[0].read_bytes()
                    self.assertLessEqual(len(stored_bytes), 1_000_000)
                    self.assertNotEqual(stored_bytes, source)
                    with Image.open(io.BytesIO(stored_bytes)) as image:
                        self.assertEqual(image.format, "JPEG")
                        self.assertEqual(image.mode, "RGB")

    def test_manual_complete_accepts_jpeg_proof(self) -> None:
        with self.client() as client:
            client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "拍一张", "difficulty": 1},
            )
            task_id = api_tasks(client)[0]["id"]
            source = image_bytes("JPEG")
            done = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.jpeg", source, "image/jpeg")},
            )
            self.assertEqual(done.status_code, 200, done.text)
            stored = list(
                (self.api_dir / "task-proofs" / "owner").glob(f"{task_id}.*")
            )
            self.assertEqual([path.suffix for path in stored], [".jpg"])
            self.assertEqual(stored[0].read_bytes(), source)

    def test_chest_claim_and_permissions(self) -> None:
        self.add_account("friend", "Friend", "friend-token-only")
        with self.client() as client:
            with sqlite3.connect(self.game_db_path) as conn:
                conn.execute(
                    "UPDATE game_config SET value = '0' "
                    "WHERE key = 'task_chest_boost_chance'"
                )
            definition = client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "画一张", "difficulty": 2},
            ).json()
            task_id = api_tasks(client)[0]["id"]
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
            self.assertEqual(
                set(body),
                {
                    "amount",
                    "balance",
                    "duplicate",
                    "reward_type",
                    "boost_minutes",
                    "star",
                    "diamond_boost",
                },
            )
            self.assertEqual(body["reward_type"], "diamonds")
            self.assertIsNone(body["boost_minutes"])
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

    def test_star_chest_api_payload_and_idempotency(self) -> None:
        with self.client() as client:
            with sqlite3.connect(self.game_db_path) as conn:
                conn.execute(
                    "UPDATE game_config SET value = ? "
                    "WHERE key = 'task_chest_pool_daily_2'",
                    ('{"1":0,"2":0,"3":0,"4":0,"5":100}',),
                )
                conn.execute(
                    "UPDATE game_config SET value = '100' "
                    "WHERE key = 'task_chest_star_chance'"
                )
            client.post(
                "/v1/me/task-definitions",
                headers=auth(TOKEN),
                json={"title": "星箱任务", "difficulty": 2},
            )
            task_id = api_tasks(client)[0]["id"]
            done = client.post(
                f"/v1/me/tasks/{task_id}/complete",
                headers=auth(TOKEN),
                files={"file": ("proof.png", image_bytes(), "image/png")},
            )
            self.assertEqual(done.status_code, 200, done.text)
            self.assertEqual(done.json()["task"]["chest_pool"], "daily_2")
            self.assertIsNone(done.json()["task"]["chest_star"])
            claimed = client.post(
                f"/v1/me/tasks/{task_id}/chest", headers=auth(TOKEN)
            )
            self.assertEqual(claimed.status_code, 200, claimed.text)
            body = claimed.json()
            self.assertEqual(body["reward_type"], "star")
            self.assertEqual(body["amount"], 0)
            self.assertIsNone(body["boost_minutes"])
            self.assertEqual(body["star"]["kind"], "normal")
            self.assertIsNone(body["star"]["season_key"])
            again = client.post(
                f"/v1/me/tasks/{task_id}/chest", headers=auth(TOKEN)
            )
            self.assertTrue(again.json()["duplicate"])
            self.assertEqual(again.json()["star"]["id"], body["star"]["id"])
            listed = api_tasks(client)[0]
            self.assertEqual(listed["chest_reward_type"], "star")
            self.assertEqual(listed["chest_star"]["id"], body["star"]["id"])

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
            tasks = api_tasks(client)
            repair = [task for task in tasks if task["source"] == "repair"]
            self.assertEqual(len(repair), 1)
            self.assertEqual(repair[0]["title"], "补断联 · 10/25")
            self.assertEqual(repair[0]["description"], "当天只拿到 74 XP；用余烬补上。")
            self.assertEqual(repair[0]["ends_at"], "2026-11-02T00:00:00+08:00")
            self.assertEqual(repair[0]["progress"], {"current": 0, "target": 1})
            self.assertEqual(repair[0]["missed_date"], "2026-10-25")


if __name__ == "__main__":
    unittest.main()
