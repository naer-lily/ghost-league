from __future__ import annotations

import unittest

from test_api import APITestBase, FRIEND_TOKEN, TOKEN, auth


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
