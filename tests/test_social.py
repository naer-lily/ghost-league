from __future__ import annotations

import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_api import APITestBase, FRIEND2_TOKEN, FRIEND_TOKEN, TOKEN, auth  # noqa: E402


class SocialAPITests(APITestBase):
    def league_player_id(self, client, *, human: bool = False) -> str:
        payload = client.get("/v1/me/league", headers=auth(TOKEN)).json()
        for row in payload["standings"]:
            if row["is_me"] == human and not human:
                return row["user_id"]
            if row["is_me"] == human and human:
                return row["user_id"]
        raise AssertionError("no matching league player")

    def test_01_follow_is_idempotent_and_counts_are_one_way(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            target = self.league_player_id(client)
            first = client.post(f"/v1/me/follows/{target}", headers=auth(TOKEN))
            second = client.post(f"/v1/me/follows/{target}", headers=auth(TOKEN))
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)

            target_detail = client.get(
                f"/v1/users/{target}", headers=auth(TOKEN)
            ).json()
            self.assertEqual(target_detail["followers_count"], 1)
            self.assertEqual(target_detail["following_count"], 0)
            self.assertTrue(target_detail["is_following"])
            me = client.get("/v1/users/owner", headers=auth(TOKEN)).json()
            self.assertEqual(me["following_count"], 1)
            self.assertEqual(me["followers_count"], 0)

            friend = client.get("/v1/users/friend-1", headers=auth(TOKEN)).json()
            self.assertFalse(friend["is_following"])
            self.assertEqual(friend["followers_count"], 0)

    def test_02_self_follow_unknown_and_delete_are_safe(self) -> None:
        with self.client() as client:
            target = self.league_player_id(client)
            self.assertEqual(
                client.post(
                    "/v1/me/follows/owner", headers=auth(TOKEN)
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/v1/me/follows/not-a-real-user", headers=auth(TOKEN)
                ).status_code,
                404,
            )
            client.post(f"/v1/me/follows/{target}", headers=auth(TOKEN))
            self.assertEqual(
                client.delete(
                    f"/v1/me/follows/{target}", headers=auth(TOKEN)
                ).status_code,
                204,
            )
            self.assertEqual(
                client.delete(
                    f"/v1/me/follows/{target}", headers=auth(TOKEN)
                ).status_code,
                204,
            )
            target_detail = client.get(
                f"/v1/users/{target}", headers=auth(TOKEN)
            ).json()
            self.assertEqual(target_detail["followers_count"], 0)

    def test_03_friends_standings_use_xp_and_hide_internals(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            target = self.league_player_id(client)
            client.post(f"/v1/me/follows/{target}", headers=auth(TOKEN))
            client.post("/v1/me/follows/friend-1", headers=auth(TOKEN))
            response = client.get("/v1/me/friends/standings", headers=auth(TOKEN))
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["week_start"], "2026-10-26")
            members = payload["members"]
            self.assertEqual(len(members), 3)
            self.assertEqual(sum(1 for member in members if member["user_id"] == "owner"), 1)
            xp_values = [member["xp"] for member in members]
            self.assertEqual(xp_values, sorted(xp_values, reverse=True))
            for forbidden in ("is_ghost", "origin", "synthetic", "kind", "raw"):
                self.assertNotIn(forbidden, response.text)

    def test_04_discover_people_lists_only_accounts(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        self.add_account("friend-2", "Friend Two", FRIEND2_TOKEN)
        with self.client() as client:
            target = self.league_player_id(client)
            client.post(f"/v1/me/follows/{target}", headers=auth(TOKEN))
            response = client.get("/v1/discover/people", headers=auth(TOKEN))
            self.assertEqual(response.status_code, 200)
            people = response.json()
            ids = {person["user_id"] for person in people}
            self.assertEqual(ids, {"friend-1", "friend-2"})
            self.assertNotIn("owner", ids)
            self.assertNotIn(target, ids)
            self.assertNotIn("is_ghost", response.text)
            for person in people:
                for key in (
                    "user_id",
                    "display_name",
                    "avatar_url",
                    "activity_label",
                    "tier",
                    "group_id",
                    "xp",
                    "is_following",
                    "followers_count",
                ):
                    self.assertIn(key, person)

    def test_05_detail_works_for_human_and_league_player(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            target = self.league_player_id(client)
            human = client.get("/v1/users/friend-1", headers=auth(TOKEN))
            self.assertEqual(human.status_code, 200)
            human_payload = human.json()
            self.assertEqual(human_payload["user_id"], "friend-1")
            self.assertIsNotNone(human_payload["activity_label"])
            self.assertIn("xp", human_payload)
            self.assertIn("streak", human_payload)

            league_user = client.get(
                f"/v1/users/{target}", headers=auth(TOKEN)
            )
            self.assertEqual(league_user.status_code, 200)
            payload = league_user.json()
            self.assertIsNone(payload["activity_label"])
            self.assertEqual(payload["user_id"], target)
            self.assertIn("xp", payload)
            for forbidden in ("is_ghost", "origin", "synthetic", "kind", "raw"):
                self.assertNotIn(forbidden, league_user.text)

            missing = client.get("/v1/users/not-a-real-user", headers=auth(TOKEN))
            self.assertEqual(missing.status_code, 404)

    def test_06_new_endpoints_require_auth(self) -> None:
        with self.client() as client:
            target = self.league_player_id(client)
            for method, path in (
                (client.get, f"/v1/users/{target}"),
                (client.get, "/v1/me/follows"),
                (client.get, "/v1/me/friends/standings"),
                (client.get, "/v1/discover/people"),
                (client.post, f"/v1/me/follows/{target}"),
                (client.delete, f"/v1/me/follows/{target}"),
            ):
                response = method(path)
                self.assertEqual(response.status_code, 401, path)

    def test_07_followers_count_aggregates_accounts(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        self.add_account("friend-2", "Friend Two", FRIEND2_TOKEN)
        with self.client() as client:
            target = self.league_player_id(client)
            self.assertEqual(
                client.post(
                    f"/v1/me/follows/{target}", headers=auth(TOKEN)
                ).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    f"/v1/me/follows/{target}", headers=auth(FRIEND_TOKEN)
                ).status_code,
                200,
            )
            detail = client.get(f"/v1/users/{target}", headers=auth(TOKEN)).json()
            self.assertEqual(detail["followers_count"], 2)
            self.assertEqual(detail["following_count"], 0)
            following = client.get("/v1/me/follows", headers=auth(TOKEN)).json()
            self.assertEqual([member["user_id"] for member in following], [target])
            self.assertTrue(following[0]["is_following"])

    def test_08_player_avatar_is_visible_in_detail(self) -> None:
        from test_api import image_bytes

        with self.client() as client:
            upload = client.post(
                "/v1/me/avatar",
                headers=auth(TOKEN),
                files={"file": ("avatar.png", image_bytes(), "image/png")},
            )
            self.assertEqual(upload.status_code, 200)
            detail = client.get("/v1/users/owner", headers=auth(TOKEN))
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(
                detail.json()["avatar_url"], "/avatars/owner"
            )


if __name__ == "__main__":
    unittest.main()
