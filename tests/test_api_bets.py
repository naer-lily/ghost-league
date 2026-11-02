from __future__ import annotations

import unittest

from test_api import APITestBase, TOKEN, auth


class BetsAPITests(APITestBase):
    def game_store(self, client):
        return client.app.state.game_service.store

    def group_id(self, client) -> int:
        payload = client.get("/v1/me/league", headers=auth(TOKEN)).json()
        self.assertIsNotNone(payload["group_id"])
        return int(payload["group_id"])

    def set_group_tier(self, client, tier: str) -> None:
        group_id = self.group_id(client)
        store = self.game_store(client)
        with store.transaction() as conn:
            conn.execute(
                "UPDATE groups SET tier = ? WHERE id = ?", (tier, group_id)
            )

    def test_three_markets_place_in_one_week_and_list_as_a_group(
        self,
    ) -> None:
        with self.client() as client:
            self.set_group_tier(client, "Silver")
            options = client.get("/v1/me/bets", headers=auth(TOKEN)).json()
            markets = options["bet_options"]["group"]["markets"]
            self.assertEqual(
                [entry["market"] for entry in markets],
                ["top3", "promote", "no_demote"],
            )
            odds = [entry["odds"] for entry in markets]
            self.assertEqual(odds, sorted(odds, reverse=True))
            self.assertTrue(all(entry["available"] for entry in markets))

            placed = {}
            for market in ("top3", "promote", "no_demote"):
                response = client.post(
                    "/v1/me/bets",
                    headers=auth(TOKEN),
                    json={
                        "kind": "group",
                        "market": market,
                        "paid_stake": 10,
                        "request_id": "same-week",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                placed[market] = response.json()["bet"]
                self.assertEqual(placed[market]["market"], market)
            self.assertEqual(
                len({bet["id"] for bet in placed.values()}), 3
            )
            self.assertEqual(
                self.game_store(client).get_diamond_balance(
                    "owner", now=self.clock["now"]
                ),
                970,
            )

            repeat = client.post(
                "/v1/me/bets",
                headers=auth(TOKEN),
                json={
                    "kind": "group",
                    "market": "top3",
                    "paid_stake": 10,
                    "request_id": "same-week",
                },
            )
            self.assertEqual(repeat.status_code, 200, repeat.text)
            self.assertEqual(
                repeat.json()["bet"]["id"], placed["top3"]["id"]
            )
            self.assertEqual(
                self.game_store(client).get_diamond_balance(
                    "owner", now=self.clock["now"]
                ),
                970,
            )

            duplicate = client.post(
                "/v1/me/bets",
                headers=auth(TOKEN),
                json={
                    "kind": "group",
                    "market": "promote",
                    "paid_stake": 0,
                    "request_id": "another-request",
                },
            )
            self.assertEqual(duplicate.status_code, 409, duplicate.text)

            listed = client.get("/v1/me/bets", headers=auth(TOKEN)).json()
            listed_markets = {
                entry["market"]: entry for entry in listed["groups"]
            }
            self.assertEqual(
                set(listed_markets), {"top3", "promote", "no_demote"}
            )
            for market, bet in placed.items():
                entry = listed_markets[market]
                self.assertEqual(entry["status"], "placed")
                self.assertEqual(entry["bet"]["id"], bet["id"])
                self.assertGreater(entry["odds"], 1.0)
            self.assertEqual(
                listed["group"]["id"], placed["top3"]["id"]
            )
            self.assertEqual(
                listed["bets"]["groups"], listed["groups"]
            )

    def test_bronze_hides_and_rejects_no_demote(self) -> None:
        with self.client() as client:
            options = client.get("/v1/me/bets", headers=auth(TOKEN)).json()
            self.assertNotIn(
                "no_demote",
                {
                    entry["market"]
                    for entry in options["bet_options"]["group"]["markets"]
                },
            )

            response = client.post(
                "/v1/me/bets",
                headers=auth(TOKEN),
                json={
                    "kind": "group",
                    "market": "no_demote",
                    "paid_stake": 20,
                    "request_id": "bronze-no-demote",
                },
            )
            self.assertEqual(response.status_code, 422, response.text)
            payload = response.json()
            self.assertEqual(payload["code"], "market_unavailable")
            self.assertEqual(
                self.game_store(client).get_diamond_balance(
                    "owner", now=self.clock["now"]
                ),
                1000,
            )
            listed = client.get("/v1/me/bets", headers=auth(TOKEN)).json()
            self.assertEqual(
                [entry["market"] for entry in listed["groups"]],
                ["top3", "promote"],
            )
            self.assertNotIn(
                "no_demote",
                {entry["market"] for entry in listed["groups"]},
            )

    def test_diamond_hides_and_rejects_promote(self) -> None:
        with self.client() as client:
            self.set_group_tier(client, "Diamond")
            options = client.get("/v1/me/bets", headers=auth(TOKEN)).json()
            self.assertNotIn(
                "promote",
                {
                    entry["market"]
                    for entry in options["bet_options"]["group"]["markets"]
                },
            )

            response = client.post(
                "/v1/me/bets",
                headers=auth(TOKEN),
                json={
                    "kind": "group",
                    "market": "promote",
                    "paid_stake": 20,
                    "request_id": "diamond-promote",
                },
            )
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["code"], "market_unavailable")
            self.assertEqual(
                self.game_store(client).get_diamond_balance(
                    "owner", now=self.clock["now"]
                ),
                1000,
            )

            accepted = client.post(
                "/v1/me/bets",
                headers=auth(TOKEN),
                json={
                    "kind": "group",
                    "market": "no_demote",
                    "paid_stake": 20,
                    "request_id": "diamond-no-demote",
                },
            )
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(
                accepted.json()["bet"]["market"], "no_demote"
            )
            listed = client.get("/v1/me/bets", headers=auth(TOKEN)).json()
            self.assertEqual(
                [entry["market"] for entry in listed["groups"]],
                ["top3", "no_demote"],
            )
            self.assertEqual(listed["groups"][1]["bet"]["market"], "no_demote")

    def test_group_market_is_rejected_for_weekly_bets(self) -> None:
        with self.client() as client:
            response = client.post(
                "/v1/me/bets",
                headers=auth(TOKEN),
                json={
                    "kind": "weekly",
                    "market": "top3",
                    "target_margin": 0,
                    "paid_stake": 0,
                    "request_id": "weekly-market",
                },
            )
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["code"], "invalid_market")

    def test_no_group_returns_an_empty_market_list(self) -> None:
        with self.client(seed_roster=False) as client:
            listed = client.get("/v1/me/bets", headers=auth(TOKEN)).json()
            self.assertIsNone(listed["group"])
            self.assertEqual(listed["groups"], [])
            self.assertIsNone(listed["bet_options"]["group"])

            response = client.post(
                "/v1/me/bets",
                headers=auth(TOKEN),
                json={
                    "kind": "group",
                    "market": "top3",
                    "paid_stake": 0,
                    "request_id": "no-group",
                },
            )
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["code"], "no_group")


if __name__ == "__main__":
    unittest.main()
