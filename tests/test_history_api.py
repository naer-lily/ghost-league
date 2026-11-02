from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_api_game import GameAPITestBase, auth  # noqa: E402

from ghost_league.schedule import TZ  # noqa: E402


def at(year: int, month: int, day: int, hour: int = 10) -> str:
    return datetime(year, month, day, hour, tzinfo=TZ).isoformat(timespec="seconds")


def unix_at(year: int, month: int, day: int, hour: int = 10) -> int:
    return int(datetime(year, month, day, hour, tzinfo=TZ).timestamp())


class HistoryAPITests(GameAPITestBase):
    def seed_history(self) -> dict[str, int]:
        with sqlite3.connect(self.game_db_path) as conn:
            conn.execute(
                "INSERT INTO checkins "
                "(player_id, date, source, seconds, xp, checked_at, repaired_at, "
                "repair_cost, status, created_at, domain, content) "
                "VALUES ('owner', '2026-10-20', 'verified', 8040, 1340, ?, NULL, "
                "0, 'verified', ?, '画画', '画了一张速写')",
                (at(2026, 10, 20, 9), unix_at(2026, 10, 20, 9)),
            )
            bet = conn.execute(
                "INSERT INTO bets "
                "(player_id, kind, period_key, rival_id, stake, free_stake, "
                "paid_stake, target_margin, odds, status, placed_at, locked_at, "
                "settled_at, payout, result_diff, idempotency_key) "
                "VALUES ('owner', 'weekly', '2026-10-19', 'rival-1', 520, 20, "
                "500, 150, 2.0, 'won', ?, ?, ?, 600, 150, 'history-bet-1')",
                (at(2026, 10, 20), at(2026, 10, 21, 23), at(2026, 10, 21, 10)),
            )
            group_bet = conn.execute(
                "INSERT INTO group_bets "
                "(player_id, week_start, group_id, stake, free_stake, paid_stake, "
                "odds, status, placed_at, settled_at, payout, group_rank, "
                "idempotency_key) "
                "VALUES ('owner', '2026-10-19', 7, 220, 20, 200, 2.0, 'won', "
                "?, ?, 440, 3, 'history-group-1')",
                (at(2026, 10, 20), at(2026, 10, 22, 10)),
            )
            conn.execute(
                "INSERT INTO rival_results "
                "(week_start, player_id, rival_id, my_xp, rival_xp, outcome, "
                "reward_diamonds, settled_at) VALUES "
                "('2026-10-19', 'owner', 'rival-1', 1200, 900, 'win', 120, ?)",
                (at(2026, 10, 23, 10),),
            )
            conn.execute(
                "INSERT INTO player_stars "
                "(id, player_id, name, kind, season_key, price_diamonds, "
                "acquired_at, source, star_type, rarity, palette_json, "
                "visual_seed, companion_count, catalog_code) "
                "VALUES ('star-history-1', 'owner', '霜蓝', 'normal', NULL, 300, "
                "?, 'star', 'blue_white_star', 'rare', '[]', 4242, 0, "
                "'GL-HISTORY-1')",
                (at(2026, 10, 24, 10),),
            )
            conn.execute(
                "INSERT INTO weekly_results "
                "(week_start, player_id, group_id, tier, rank, xp, promoted, "
                "demoted, repaired_days, clean_checkins, settled_at) VALUES "
                "('2026-10-19', 'owner', 7, 'Bronze', 3, 4200, 1, 0, 0, 5, ?)",
                (at(2026, 10, 25, 10),),
            )
            # Another player's rows must never leak into this timeline.
            conn.execute(
                "INSERT INTO checkins "
                "(player_id, date, source, seconds, xp, checked_at, repaired_at, "
                "repair_cost, status, created_at, domain, content) "
                "VALUES ('outsider', '2026-10-26', 'verified', 300, 50, ?, NULL, "
                "0, 'verified', ?, '跑步', '别人的记录')",
                (at(2026, 10, 26, 9), unix_at(2026, 10, 26, 9)),
            )
            conn.execute(
                "INSERT INTO player_stars "
                "(id, player_id, name, kind, season_key, price_diamonds, "
                "acquired_at, source, star_type, rarity, palette_json, "
                "visual_seed, companion_count, catalog_code) "
                "VALUES ('star-outsider', 'outsider', '别人的星', 'normal', NULL, "
                "300, ?, 'star', 'blue_white_star', 'rare', '[]', 1, 0, "
                "'GL-HISTORY-OUTSIDER')",
                (at(2026, 10, 26, 11),),
            )
        return {
            "bet": int(bet.lastrowid or 0),
            "group_bet": int(group_bet.lastrowid or 0),
        }

    def test_01_all_six_types_are_sorted_and_only_include_the_caller(self) -> None:
        with self.client() as client:
            ids = self.seed_history()
            response = client.get("/v1/me/history", headers=auth())
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["user_id"], "owner")
        self.assertEqual(payload["limit"], 100)
        self.assertTrue(payload["generated_at"].endswith("+08:00"))
        items = payload["items"]
        self.assertEqual(
            [item["type"] for item in items],
            ["week", "star", "rival", "group_bet", "bet", "checkin"],
        )
        self.assertEqual(
            [item["id"] for item in items],
            [
                "week:2026-10-19",
                "star:star-history-1",
                "rival:2026-10-19",
                f"group_bet:{ids['group_bet']}",
                f"bet:{ids['bet']}",
                "checkin:2026-10-20",
            ],
        )
        for item in items:
            self.assertEqual(
                set(item), {"id", "type", "at", "title", "body", "data"}
            )
            self.assertTrue(item["at"].endswith("+08:00"))
        self.assertEqual(items[0]["body"], "Bronze · 第 3 名 · 4,200 XP · 晋级 · 干净打卡 5 天")
        self.assertEqual(items[1]["body"], "霜蓝 · 蓝白星 · 耀星")
        self.assertEqual(items[2]["body"], "我 1,200 XP · 宿敌 900 XP · 获胜 · 奖励 120 钻石")
        self.assertIn("组内第 3 名", items[3]["body"])
        self.assertIn("组内下注", items[3]["title"])
        self.assertIn("周注", items[4]["body"])
        self.assertIn("目标 +150 XP", items[4]["body"])
        self.assertIn("派彩 600", items[4]["body"])
        self.assertEqual(items[5]["body"], "画画 · 画了一张速写")
        self.assertEqual(
            set(items[5]["data"]), {"date", "domain", "content"}
        )
        self.assertNotIn("outsider", response.text)
        self.assertNotIn("别人的记录", response.text)
        self.assertNotIn("star-outsider", response.text)
        self.assertNotIn("diamond_ledger", response.text)
        self.assertNotIn("player_id", response.text)

    def test_02_limit_is_validated_and_applied_after_global_sort(self) -> None:
        with self.client() as client:
            self.seed_history()
            limited = client.get(
                "/v1/me/history?limit=3", headers=auth()
            )
            self.assertEqual(limited.status_code, 200, limited.text)
            payload = limited.json()
            self.assertEqual(payload["limit"], 3)
            self.assertEqual(
                [item["type"] for item in payload["items"]],
                ["week", "star", "rival"],
            )
            for bad in ("0", "201", "-1"):
                response = client.get(
                    f"/v1/me/history?limit={bad}", headers=auth()
                )
                self.assertEqual(response.status_code, 422, bad)

    def test_03_same_timestamp_uses_id_and_legacy_checkin_does_not_crash(self) -> None:
        with self.client() as client:
            with sqlite3.connect(self.game_db_path) as conn:
                conn.execute(
                    "INSERT INTO checkins "
                    "(player_id, date, source, seconds, xp, checked_at, "
                    "repaired_at, repair_cost, status, created_at, domain, "
                    "content) VALUES ('owner', '2026-10-18', 'verified', 300, "
                    "50, '2026-10-18T08:00:00+08:00', NULL, 0, 'verified', "
                    "NULL, NULL, NULL)"
                )
                shared = at(2026, 10, 19, 9)
                for suffix in ("b", "a"):
                    conn.execute(
                        "INSERT INTO checkins "
                        "(player_id, date, source, seconds, xp, checked_at, "
                        "repaired_at, repair_cost, status, created_at, domain, "
                        "content) VALUES ('owner', ?, 'verified', 300, 50, ?, "
                        "NULL, 0, 'verified', ?, NULL, NULL)",
                        (
                            f"2026-10-{19 if suffix == 'b' else 20}",
                            shared,
                            unix_at(2026, 10, 19, 9),
                        ),
                    )
            response = client.get("/v1/me/history", headers=auth())
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertEqual(
            [item["id"] for item in items],
            ["checkin:2026-10-19", "checkin:2026-10-20", "checkin:2026-10-18"],
        )
        legacy = items[-1]
        self.assertEqual(legacy["body"], "打卡记录")
        self.assertEqual(legacy["data"]["domain"], "")
        self.assertEqual(legacy["data"]["content"], "")

    def test_04_history_requires_auth(self) -> None:
        with self.client() as client:
            response = client.get("/v1/me/history")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
