from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime

from ghost_league.game import calendar as cal
from ghost_league.schedule import TZ
from test_api import APITestBase, FRIEND_TOKEN, TOKEN, auth


class RecentXpAPITests(APITestBase):
    def seed_checkin(self, player_id: str, day: str, xp: int) -> None:
        checked_at = datetime.fromisoformat(f"{day}T09:00:00").replace(tzinfo=TZ)
        with sqlite3.connect(self.game_db_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO checkins "
                "(player_id, date, source, seconds, xp, checked_at, repaired_at, "
                "repair_cost, status, created_at) "
                "VALUES (?, ?, 'verified', 600, ?, ?, NULL, 0, 'verified', ?)",
                (
                    player_id,
                    day,
                    xp,
                    checked_at.isoformat(timespec="seconds"),
                    int(checked_at.timestamp()),
                ),
            )

    def seed_channel_event(
        self, player_id: str, day: str, seconds: int, event_id: str
    ) -> None:
        occurred_at = cal.iso_ts(
            datetime.fromisoformat(f"{day}T12:00:00").replace(tzinfo=TZ)
        )
        with sqlite3.connect(self.game_db_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO channel_events "
                "(event_id, channel_id, player_ref, player_id, seconds, "
                "occurred_at, week_start, created_at) "
                "VALUES (?, 'test-channel', ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    player_id,
                    player_id,
                    seconds,
                    occurred_at,
                    cal.week_start(day).isoformat(),
                    occurred_at,
                ),
            )

    def test_recent_xp_falls_back_to_channel_events_for_missing_checkins(
        self,
    ) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            # Create both players before writing raw Channel events.
            client.get("/v1/users/friend-1", headers=auth(TOKEN))
            self.seed_channel_event("friend-1", "2026-10-19", 600, "outside-before")
            self.seed_channel_event("friend-1", "2026-10-20", 59, "boundary-start")
            self.seed_channel_event("friend-1", "2026-10-24", 178, "target-a")
            self.seed_channel_event("friend-1", "2026-10-24", 120, "target-b")
            self.seed_channel_event("friend-1", "2026-10-25", 428, "target-c")
            self.seed_channel_event("friend-1", "2026-10-26", 142, "target-d")
            self.seed_channel_event("friend-1", "2026-10-27", 600, "outside-after")
            self.seed_channel_event("owner", "2026-10-23", 79, "viewer-a")

            response = client.get("/v1/users/friend-1", headers=auth(TOKEN))
            self.assertEqual(response.status_code, 200, response.text)
            recent = response.json()["recent_xp"]
            self.assertEqual(recent["target"], [9, 0, 0, 0, 49, 71, 23])
            self.assertEqual(recent["viewer"], [0, 0, 0, 13, 0, 0, 0])
            self.assertEqual(recent["target_total"], 152)
            self.assertEqual(recent["viewer_total"], 13)

    def test_recent_xp_prefers_checkins_over_channel_events_for_target_and_viewer(
        self,
    ) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            client.get("/v1/users/friend-1", headers=auth(TOKEN))
            self.seed_checkin("friend-1", "2026-10-24", 55)
            self.seed_channel_event("friend-1", "2026-10-24", 600, "covered-target")
            self.seed_channel_event("friend-1", "2026-10-25", 300, "fallback-target")
            self.seed_checkin("owner", "2026-10-23", 66)
            self.seed_channel_event("owner", "2026-10-23", 600, "covered-viewer")

            response = client.get("/v1/users/friend-1", headers=auth(TOKEN))
            self.assertEqual(response.status_code, 200, response.text)
            recent = response.json()["recent_xp"]
            self.assertEqual(recent["target"], [0, 0, 0, 0, 55, 50, 0])
            self.assertEqual(recent["viewer"], [0, 0, 0, 66, 0, 0, 0])
            self.assertEqual(recent["target_total"], 105)
            self.assertEqual(recent["viewer_total"], 66)

    def test_recent_xp_fills_missing_days_and_uses_the_seven_day_window(
        self,
    ) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            # Create both human players before writing their daily snapshots.
            client.get("/v1/users/friend-1", headers=auth(TOKEN))
            self.seed_checkin("friend-1", "2026-10-19", 999)
            self.seed_checkin("friend-1", "2026-10-20", 50)
            self.seed_checkin("friend-1", "2026-10-21", 189)
            self.seed_checkin("friend-1", "2026-10-24", 182)
            self.seed_checkin("friend-1", "2026-10-26", 150)
            self.seed_checkin("owner", "2026-10-22", 77)
            self.seed_checkin("owner", "2026-10-26", 441)

            response = client.get(
                "/v1/users/friend-1", headers=auth(TOKEN)
            )
            self.assertEqual(response.status_code, 200, response.text)
            recent = response.json()["recent_xp"]
            self.assertEqual(
                recent["days"],
                [
                    "2026-10-20",
                    "2026-10-21",
                    "2026-10-22",
                    "2026-10-23",
                    "2026-10-24",
                    "2026-10-25",
                    "2026-10-26",
                ],
            )
            self.assertEqual(
                recent["labels"],
                ["二", "三", "四", "五", "六", "日", "一"],
            )
            self.assertEqual(recent["target"], [50, 189, 0, 0, 182, 0, 150])
            self.assertEqual(recent["viewer"], [0, 0, 77, 0, 0, 0, 441])
            self.assertEqual(recent["target_total"], 571)
            self.assertEqual(recent["viewer_total"], 518)

    def test_recent_xp_is_identical_for_self_and_zero_without_checkins(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            client.get("/v1/users/owner", headers=auth(TOKEN))
            client.get("/v1/users/friend-1", headers=auth(TOKEN))
            self.seed_checkin("owner", "2026-10-24", 123)

            mine = client.get("/v1/users/owner", headers=auth(TOKEN))
            self.assertEqual(mine.status_code, 200, mine.text)
            recent = mine.json()["recent_xp"]
            self.assertEqual(recent["target"], recent["viewer"])
            self.assertEqual(recent["target_total"], recent["viewer_total"])
            self.assertEqual(recent["target"], [0, 0, 0, 0, 123, 0, 0])

            empty = client.get(
                "/v1/users/friend-1", headers=auth(TOKEN)
            ).json()["recent_xp"]
            self.assertEqual(empty["target"], [0] * 7)
            self.assertEqual(empty["viewer"], [0, 0, 0, 0, 123, 0, 0])
            self.assertEqual(empty["target_total"], 0)
            self.assertEqual(empty["viewer_total"], 123)

    def test_other_endpoints_do_not_gain_recent_xp(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            client.get("/v1/users/friend-1", headers=auth(TOKEN))
            friends = client.get(
                "/v1/me/friends/standings", headers=auth(TOKEN)
            )
            self.assertEqual(friends.status_code, 200, friends.text)
            for member in friends.json()["members"]:
                self.assertNotIn("recent_xp", member)


class UsersComparisonAPITests(APITestBase):
    def test_detail_compares_public_weekly_data(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            self.assertEqual(
                client.get(
                    "/v1/me/league", headers=auth(FRIEND_TOKEN)
                ).status_code,
                200,
            )
            owner = self.post_increment(
                client,
                event_id="owner-comparison",
                seconds=600,
            )
            self.assertEqual(owner.status_code, 200, owner.text)
            friend = self.post_increment(
                client,
                token=FRIEND_TOKEN,
                event_id="friend-comparison",
                seconds=1800,
            )
            self.assertEqual(friend.status_code, 200, friend.text)

            response = client.get(
                "/v1/users/friend-1", headers=auth(TOKEN)
            )
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            comparison = detail["comparison"]
            self.assertIsNotNone(comparison)
            self.assertEqual(comparison["viewer_id"], "owner")
            self.assertEqual(comparison["target_id"], "friend-1")
            self.assertEqual(comparison["target_xp"], detail["xp"])
            self.assertEqual(comparison["target_rank"], detail["rank"])
            self.assertEqual(comparison["viewer_xp"], 100)
            self.assertEqual(comparison["target_xp"], 300)
            self.assertEqual(comparison["xp_diff"], -200)
            self.assertEqual(comparison["leader"], "them")
            self.assertIn("tier", detail)
            self.assertIn("streak", detail)
            self.assertIn("display_name", detail)

            text = response.text
            for forbidden in (
                "diamonds",
                "diamond_balance",
                "inventory",
                "wallet",
                "paid_stake",
                "bets",
            ):
                self.assertNotIn(forbidden, text)

    def test_target_missing_returns_404(self) -> None:
        with self.client() as client:
            response = client.get(
                "/v1/users/not-a-real-user", headers=auth(TOKEN)
            )
            self.assertEqual(response.status_code, 404)

    def test_detail_requires_login(self) -> None:
        with self.client() as client:
            response = client.get("/v1/users/owner")
            self.assertEqual(response.status_code, 401)

    def test_self_comparison_is_null_without_group_data(self) -> None:
        with self.client(seed_roster=False) as client:
            response = client.get("/v1/users/owner", headers=auth(TOKEN))
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertIsNone(payload["comparison"])
            self.assertIsNone(payload["group_id"])
            self.assertEqual(payload["group_size"], 0)
            self.assertIsNone(payload["rank"])
            self.assertEqual(payload["xp"], 0)
            self.assertEqual(payload["tier"], "Bronze")

    def test_viewer_without_group_data_still_gets_a_stable_comparison(
        self,
    ) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client(seed_roster=False) as client:
            response = client.get(
                "/v1/users/friend-1", headers=auth(TOKEN)
            )
            self.assertEqual(response.status_code, 200, response.text)
            comparison = response.json()["comparison"]
            self.assertIsNotNone(comparison)
            self.assertIsNone(comparison["viewer_rank"])
            self.assertIsNone(comparison["target_rank"])
            self.assertEqual(comparison["viewer_group_size"], 0)
            self.assertEqual(comparison["target_group_size"], 0)
            self.assertEqual(comparison["xp_diff"], 0)
            self.assertEqual(comparison["leader"], "tie")


if __name__ == "__main__":
    unittest.main()
