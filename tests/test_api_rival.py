from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.game.rival import round_to_step
from ghost_league.schedule import TZ

TOKEN = "rival-token"
CHANNEL_TOKEN = "rival-channel-token"
CHANNEL = "rival-channel"
NOW = datetime(2026, 11, 2, 8, 0, 0, tzinfo=TZ)
TUESDAY = datetime(2026, 11, 3, 0, 0, 0, tzinfo=TZ)
WEEK_START = "2026-11-02"
PREVIOUS_WEEK = "2026-10-26"


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def collect_keys(value, keys: set[str]) -> None:
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            collect_keys(child, keys)
    elif isinstance(value, list):
        for child in value:
            collect_keys(child, keys)


class RivalAPITestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.api_dir = self.base / "api"
        self.api_dir.mkdir(parents=True)
        self.game_db_path = self.api_dir / "league.db"
        self.accounts_db = self.api_dir / "accounts.db"
        self.clock = {"now": NOW}
        self.accounts = AccountsStore(
            self.accounts_db, now_fn=lambda: self.clock["now"]
        )
        self.accounts.initialize()
        self.accounts.create("owner", "You", token=TOKEN)

    def app(self):
        return create_app(
            game_db_path=self.game_db_path,
            cache_path=self.base / "cache.json",
            avatars_path=self.api_dir / "avatars.json",
            api_dir=self.api_dir,
            accounts_db=self.accounts_db,
            social_db=self.api_dir / "social.db",
            webhooks_db=self.api_dir / "webhooks.db",
            start_webhook_worker=False,
            token=TOKEN,
            channel_token=CHANNEL_TOKEN,
            now_fn=lambda: self.clock["now"],
        )

    def seed_roster(self, client: TestClient, *, players: int = 16) -> None:
        response = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=auth(CHANNEL_TOKEN),
            json={
                "players": [
                    {
                        "player_ref": f"rival-ai-{index:02d}",
                        "kind": "ai",
                    }
                    for index in range(players)
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def client(self):
        app = self.app()
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.seed_roster(client)
        return client

    def first_candidate(self, client: TestClient) -> dict:
        payload = client.get(
            "/v1/me/rival/candidates", headers=auth()
        ).json()
        self.assertTrue(payload["candidates"])
        return payload["candidates"][0]

    def select_first(self, client: TestClient) -> dict:
        candidate = self.first_candidate(client)
        response = client.post(
            "/v1/me/rival/select",
            headers=auth(),
            json={"rival_id": candidate["user_id"], "request_id": "select-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def store(self, client: TestClient):
        return client.app.state.game_service.store


class RivalStateAPITests(RivalAPITestBase):
    def test_state_is_open_before_selection_and_hides_private_fields(
        self,
    ) -> None:
        client = self.client()
        response = client.get("/v1/me/rival", headers=auth())
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["week_start"], WEEK_START)
        self.assertEqual(payload["server_now"], "2026-11-02T08:00:00+08:00")
        self.assertTrue(payload["selection"]["open"])
        self.assertIsNone(payload["selection"]["mode"])
        self.assertIsNone(payload["rival"])
        self.assertIsNone(payload["result"])
        self.assertEqual(payload["me"]["user_id"], "owner")
        self.assertEqual(payload["me"]["group_no"], 1)
        self.assertIsNone(payload["bets"]["weekly"])
        self.assertIsNone(payload["bets"]["daily"])
        self.assertIsNone(payload["bets"]["group"])
        self.assertEqual(
            [entry["market"] for entry in payload["bets"]["groups"]],
            ["top3", "promote"],
        )
        self.assertTrue(
            all(entry["bet"] is None for entry in payload["bets"]["groups"])
        )
        self.assertIsNone(payload["bet_options"]["weekly"])
        self.assertIsNone(payload["bet_options"]["daily"])
        group_options = payload["bet_options"]["group"]
        self.assertEqual(group_options["target_rank"], 3)
        self.assertGreater(group_options["odds"], 1.0)
        self.assertEqual(group_options["free_stake"], 20)
        self.assertEqual(group_options["max_paid_stake"], 500)
        self.assertEqual(
            [entry["market"] for entry in group_options["markets"]],
            ["top3", "promote"],
        )
        self.assertEqual(
            payload["bet_windows"],
            {
                "weekly_locks_at": "2026-11-02T23:59:59+08:00",
                "daily_locks_at": "2026-11-02T21:00:00+08:00",
                "daily_settles_at": "2026-11-02T22:30:00+08:00",
            },
        )
        keys: set[str] = set()
        collect_keys(payload, keys)
        self.assertNotIn("is_ai", keys)
        self.assertNotIn("kind", keys)
        self.assertNotIn("diamonds", keys)
        self.assertNotIn("balance", keys)
        self.assertNotIn("diamond_balance", keys)

        unauth = client.get("/v1/me/rival")
        self.assertEqual(unauth.status_code, 401)

    def test_candidates_are_cross_group_and_sorted_by_power_gap(self) -> None:
        client = self.client()
        state = client.get("/v1/me/rival", headers=auth()).json()
        my_group = state["me"]["group_no"]
        payload = client.get(
            "/v1/me/rival/candidates", headers=auth()
        ).json()
        self.assertEqual(payload["week_start"], WEEK_START)
        self.assertTrue(payload["selection_open"])
        self.assertTrue(payload["candidates"])
        for candidate in payload["candidates"]:
            self.assertNotEqual(candidate["group_no"], my_group)
            self.assertEqual(
                set(candidate),
                {
                    "user_id",
                    "display_name",
                    "avatar_url",
                    "group_no",
                    "tier",
                    "power",
                    "week_xp",
                    "today_xp",
                },
            )

        store = self.store(client)
        ai_ids = [player["id"] for player in store.list_players(kind="ai")]
        with store.transaction() as conn:
            conn.execute(
                "UPDATE players SET power = 500 WHERE id = 'owner'"
            )
            conn.execute(
                "UPDATE players SET power = 1000 WHERE id = ?", (ai_ids[0],)
            )
            conn.execute(
                "UPDATE players SET power = 600 WHERE id = ?", (ai_ids[1],)
            )
        sorted_payload = client.get(
            "/v1/me/rival/candidates", headers=auth()
        ).json()
        self.assertEqual(sorted_payload["candidates"][0]["user_id"], ai_ids[1])
        self.assertEqual(sorted_payload["candidates"][0]["power"], 600)

    def test_daily_target_options_do_not_drift_during_the_day(self) -> None:
        client = self.client()
        selected = self.select_first(client)
        rival_id = selected["rival"]["user_id"]
        store = self.store(client)
        with store.transaction() as conn:
            conn.execute("UPDATE players SET power = 500 WHERE id = 'owner'")
            conn.execute(
                "UPDATE players SET power = 1000 WHERE id = ?", (rival_id,)
            )
        store.ensure_week(PREVIOUS_WEEK, status="settled")
        with store.transaction() as conn:
            for index, xp in enumerate((100, 200, 300, 400, 500), start=1):
                conn.execute(
                    "INSERT INTO weekly_scores "
                    "(week_start, player_id, seconds, xp) VALUES (?, ?, ?, ?)",
                    (PREVIOUS_WEEK, f"past-{index}", xp * 6, xp),
                )

        morning = datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ)
        evening = datetime(2026, 11, 2, 21, 0, 0, tzinfo=TZ)
        self.clock["now"] = morning
        store.ingest_activity(
            rival_id,
            event_id="api-rival-morning",
            seconds=600,
            occurred_at=morning,
            source="local_increment",
            now=morning,
        )
        morning_payload = client.get("/v1/me/rival", headers=auth()).json()
        self.clock["now"] = evening
        store.ingest_activity(
            rival_id,
            event_id="api-rival-evening",
            seconds=1800,
            occurred_at=evening,
            source="local_increment",
            now=evening,
        )
        evening_payload = client.get("/v1/me/rival", headers=auth()).json()

        morning_projection = morning_payload["projection"]
        self.assertNotIn("rival_today_estimate", morning_projection)
        self.assertNotIn("daily_target_max", morning_projection)
        self.assertIn("daily_target_margins", morning_projection)
        self.assertGreater(morning_projection["daily_sigma_diff"], 0)
        morning_daily = morning_payload["bet_options"]["daily"]
        daily_margins = [
            entry["margin"] for entry in morning_daily["target_options"]
        ]
        self.assertTrue(
            all(
                "expected_xp" in entry
                for entry in morning_daily["target_options"]
            )
        )
        self.assertTrue(
            all(
                isinstance(entry["expected_xp"], int)
                and entry["expected_xp"]
                == round_to_step(
                    morning_projection["daily_mu_rival"] + entry["margin"],
                    10,
                )
                for entry in morning_daily["target_options"]
            )
        )
        self.assertEqual(
            daily_margins, morning_projection["daily_target_margins"]
        )
        self.assertGreaterEqual(len(daily_margins), 3)
        self.assertLessEqual(len(daily_margins), 6)
        self.assertEqual(daily_margins[0], 1)
        self.assertEqual(daily_margins[0], morning_daily["min_target_margin"])
        self.assertEqual(daily_margins[-1], morning_daily["max_target_margin"])
        self.assertEqual(
            daily_margins, sorted(set(daily_margins))
        )
        self.assertTrue(
            all(
                margin == 1 or margin % 150 == 0
                for margin in daily_margins
            )
        )
        self.assertEqual(
            evening_payload["projection"], morning_payload["projection"]
        )
        self.assertEqual(
            evening_payload["bet_options"]["daily"], morning_daily
        )


class RivalSelectionAPITests(RivalAPITestBase):
    def test_select_returns_live_state_and_can_change_before_lock(self) -> None:
        client = self.client()
        candidates = client.get(
            "/v1/me/rival/candidates", headers=auth()
        ).json()["candidates"]
        first = client.post(
            "/v1/me/rival/select",
            headers=auth(),
            json={"rival_id": candidates[0]["user_id"], "request_id": "one"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["rival"]["user_id"], candidates[0]["user_id"])
        self.assertEqual(first.json()["selection"]["mode"], "manual")

        changed = client.post(
            "/v1/me/rival/select",
            headers=auth(),
            json={"rival_id": candidates[1]["user_id"], "request_id": "two"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["rival"]["user_id"], candidates[1]["user_id"])

        self.clock["now"] = TUESDAY
        locked = client.post(
            "/v1/me/rival/select",
            headers=auth(),
            json={"rival_id": candidates[0]["user_id"], "request_id": "three"},
        )
        self.assertEqual(locked.status_code, 409, locked.text)

    def test_select_errors_use_404_and_422(self) -> None:
        client = self.client()
        missing = client.post(
            "/v1/me/rival/select",
            headers=auth(),
            json={"rival_id": "does-not-exist", "request_id": "x"},
        )
        self.assertEqual(missing.status_code, 404, missing.text)

        self_select = client.post(
            "/v1/me/rival/select",
            headers=auth(),
            json={"rival_id": "owner", "request_id": "x"},
        )
        self.assertEqual(self_select.status_code, 422, self_select.text)

        invalid = client.post(
            "/v1/me/rival/select",
            headers=auth(),
            json={"rival_id": "someone"},
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)


class BetAPITests(RivalAPITestBase):
    def test_weekly_and_daily_bets_are_idempotent_and_do_not_leak(self) -> None:
        client = self.client()
        self.select_first(client)
        store = self.store(client)

        weekly = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "weekly",
                "paid_stake": 0,
                "target_margin": 0,
                "request_id": "w-1",
            },
        )
        self.assertEqual(weekly.status_code, 200, weekly.text)
        weekly_payload = weekly.json()
        self.assertEqual(weekly_payload["bet"]["kind"], "weekly")
        self.assertEqual(weekly_payload["bet"]["stake"], 20)
        self.assertEqual(weekly_payload["bet"]["free_stake"], 20)
        self.assertEqual(weekly_payload["bet"]["paid_stake"], 0)
        self.assertEqual(weekly_payload["bet"]["target_margin"], 0)
        self.assertEqual(weekly_payload["bet"]["odds"], 1.2)
        self.assertEqual(store.get_diamond_balance("owner", now=NOW), 1000)
        self.assertEqual(
            weekly_payload["state"]["bets"]["weekly"]["id"],
            weekly_payload["bet"]["id"],
        )
        weekly_options = weekly_payload["state"]["bet_options"]["weekly"]
        self.assertEqual(weekly_options["min_paid_stake"], 0)
        self.assertEqual(weekly_options["max_paid_stake"], 500)
        self.assertEqual(weekly_options["free_stake"], 20)
        weekly_margins = [
            entry["margin"] for entry in weekly_options["target_options"]
        ]
        self.assertEqual(weekly_margins[0], 0)
        self.assertEqual(
            weekly_margins[-1], weekly_options["max_target_margin"]
        )
        self.assertEqual(weekly_margins, sorted(set(weekly_margins)))
        self.assertGreaterEqual(len(weekly_margins), 3)
        self.assertEqual(weekly_options["target_options"][0]["odds"], 1.2)

        repeat = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "weekly",
                "paid_stake": 0,
                "target_margin": 0,
                "request_id": "w-1",
            },
        )
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()["bet"]["id"], weekly_payload["bet"]["id"])
        self.assertEqual(store.get_diamond_balance("owner", now=NOW), 1000)

        daily_target = weekly_payload["state"]["bet_options"]["daily"][
            "target_options"
        ][0]["margin"]
        daily = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "daily",
                "paid_stake": 80,
                "target_margin": daily_target,
                "request_id": "d-1",
            },
        )
        self.assertEqual(daily.status_code, 200, daily.text)
        daily_bet = daily.json()["bet"]
        self.assertEqual(daily_bet["stake"], 100)
        self.assertEqual(daily_bet["free_stake"], 20)
        self.assertEqual(daily_bet["paid_stake"], 80)
        self.assertEqual(daily_bet["target_margin"], daily_target)
        self.assertGreaterEqual(daily_bet["odds"], 1.2)
        self.assertLessEqual(daily_bet["odds"], 15.0)
        daily_options = daily.json()["state"]["bet_options"]["daily"]
        preview = {
            entry["margin"]: entry["odds"]
            for entry in daily_options["target_options"]
        }
        daily_margins = [
            entry["margin"] for entry in daily_options["target_options"]
        ]
        self.assertGreater(daily_margins[0], 0)
        self.assertEqual(daily_margins[0], daily_options["min_target_margin"])
        self.assertEqual(daily_margins[-1], daily_options["max_target_margin"])
        self.assertEqual(daily_margins, sorted(set(daily_margins)))
        self.assertGreaterEqual(len(daily_margins), 3)
        self.assertLessEqual(len(daily_margins), 6)
        self.assertEqual(preview[daily_target], daily_bet["odds"])
        self.assertEqual(store.get_diamond_balance("owner", now=NOW), 920)

        duplicate_daily = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "daily",
                "paid_stake": 0,
                "target_margin": daily_target,
                "request_id": "d-2",
            },
        )
        self.assertEqual(duplicate_daily.status_code, 409, duplicate_daily.text)

        listed = client.get("/v1/me/bets", headers=auth())
        self.assertEqual(listed.status_code, 200, listed.text)
        listed_payload = listed.json()
        self.assertEqual(listed_payload["week_start"], WEEK_START)
        self.assertEqual(listed_payload["day"], "2026-11-02")
        self.assertEqual(
            listed_payload["bets"]["weekly"]["id"], weekly_payload["bet"]["id"]
        )
        self.assertEqual(
            listed_payload["bets"]["daily"]["id"], daily_bet["id"]
        )
        self.assertIsNone(listed_payload["bets"]["group"])
        self.assertIsNone(listed_payload["group"])
        self.assertEqual(
            listed_payload["bet_options"]["daily"]["max_paid_stake"], 500
        )
        self.assertEqual(
            listed_payload["bet_options"]["daily"]["free_stake"], 20
        )

        keys: set[str] = set()
        collect_keys(weekly_payload, keys)
        collect_keys(listed_payload, keys)
        for forbidden in (
            "is_ai",
            "diamonds",
            "diamond_balance",
            "diamond_cap",
            "balance",
        ):
            self.assertNotIn(forbidden, keys)

    def test_group_bet_api_returns_group_without_rival(self) -> None:
        client = self.client()
        store = self.store(client)

        response = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "group",
                "paid_stake": 20,
                "request_id": "group-1",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        bet = response.json()["bet"]
        self.assertEqual(bet["kind"], "group")
        self.assertEqual(bet["market"], "top3")
        self.assertEqual(bet["stake"], 40)
        self.assertEqual(bet["free_stake"], 20)
        self.assertEqual(bet["paid_stake"], 20)
        self.assertEqual(bet["target_rank"], 3)
        self.assertEqual(bet["target_margin"], 0)
        self.assertGreater(bet["odds"], 1.0)
        self.assertEqual(store.get_diamond_balance("owner", now=NOW), 980)

        repeat = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "group",
                "paid_stake": 20,
                "request_id": "group-1",
            },
        )
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()["bet"]["id"], bet["id"])
        self.assertEqual(store.get_diamond_balance("owner", now=NOW), 980)

        promote = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "group",
                "market": "promote",
                "paid_stake": 10,
                "request_id": "group-promote",
            },
        )
        self.assertEqual(promote.status_code, 200, promote.text)
        self.assertEqual(promote.json()["bet"]["market"], "promote")
        self.assertEqual(store.get_diamond_balance("owner", now=NOW), 970)

        duplicate = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "group",
                "paid_stake": 0,
                "request_id": "group-2",
            },
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        listed = client.get("/v1/me/bets", headers=auth())
        self.assertEqual(listed.status_code, 200, listed.text)
        payload = listed.json()
        self.assertEqual(payload["bets"]["group"]["id"], bet["id"])
        self.assertEqual(payload["group"]["id"], bet["id"])
        self.assertEqual(payload["bet_options"]["group"]["target_rank"], 3)
        markets = {
            entry["market"]: entry for entry in payload["groups"]
        }
        self.assertEqual(set(markets), {"top3", "promote"})
        self.assertEqual(markets["top3"]["status"], "placed")
        self.assertEqual(markets["promote"]["status"], "placed")
        self.assertIsNone(payload["bets"]["weekly"])
        self.assertIsNone(payload["bets"]["daily"])

    def test_bet_rejections(self) -> None:
        client = self.client()
        no_rival = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "weekly",
                "paid_stake": 0,
                "target_margin": 0,
                "request_id": "none",
            },
        )
        self.assertEqual(no_rival.status_code, 409, no_rival.text)

        self.select_first(client)
        invalid_target = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "daily",
                "paid_stake": 0,
                "target_margin": 100,
                "request_id": "bad",
            },
        )
        self.assertEqual(invalid_target.status_code, 422, invalid_target.text)

        legacy_stake = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={"kind": "weekly", "stake": 20, "request_id": "legacy"},
        )
        self.assertEqual(legacy_stake.status_code, 422, legacy_stake.text)

        too_much = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "weekly",
                "paid_stake": 501,
                "target_margin": 0,
                "request_id": "too-much",
            },
        )
        self.assertEqual(too_much.status_code, 422, too_much.text)

        insufficient_store = self.store(client)
        with insufficient_store.transaction() as conn:
            conn.execute(
                "UPDATE diamond_balance SET balance = 10 WHERE player_id = ?",
                ("owner",),
            )
        poor = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "weekly",
                "paid_stake": 20,
                "target_margin": 0,
                "request_id": "poor",
            },
        )
        self.assertEqual(poor.status_code, 409, poor.text)
        self.assertEqual(
            insufficient_store.get_diamond_balance("owner", now=NOW), 10
        )

    def test_daily_bet_locks_at_2100(self) -> None:
        client = self.client()
        self.select_first(client)
        state = client.get("/v1/me/rival", headers=auth()).json()
        daily_target = state["bet_options"]["daily"]["target_options"][0][
            "margin"
        ]
        self.clock["now"] = datetime(2026, 11, 2, 21, 0, 0, tzinfo=TZ)
        response = client.post(
            "/v1/me/bets",
            headers=auth(),
            json={
                "kind": "daily",
                "paid_stake": 0,
                "target_margin": daily_target,
                "request_id": "late",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("截止", response.json()["detail"])
