from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.game import calendar as cal
from ghost_league.game.store import GameStore
from ghost_league.schedule import TZ

TOKEN = "game-token"
FRIEND_TOKEN = "game-friend-token"
CHANNEL_TOKEN = "game-channel-token"
CHANNEL = "game-channel"
NOW = datetime(2026, 10, 26, 10, 0, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"
HIDDEN_FIELDS = {
    "kind",
    "raw_seconds",
    "effective_seconds",
    "target_seconds",
    "anchor_seconds",
    "source_key_hash",
}


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_cache(path: Path, *, rows: int = 14) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    users = [
        {
            "id": f"anchor-{index:03d}",
            "seconds": 500_000 - index * 10_000,
            "rank": index + 1,
        }
        for index in range(rows)
    ]
    path.write_text(json.dumps({"users": users}), encoding="utf-8")
    return path


class GameAPITestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.api_dir = self.base / "api"
        self.api_dir.mkdir(parents=True)
        self.cache_path = write_cache(self.base / "cache.json")
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
            cache_path=self.cache_path,
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

    def seed_channel_roster(self, client: TestClient, *, players: int = 14) -> None:
        response = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=auth(CHANNEL_TOKEN),
            json={
                "players": [
                    {"player_ref": f"channel-ai-{index:02d}", "kind": "ai"}
                    for index in range(players)
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    @contextmanager
    def client(self, *, seed_roster: bool = True):
        with TestClient(self.app()) as client:
            if seed_roster:
                self.seed_channel_roster(client)
            yield client

    def post_increment(
        self,
        client: TestClient,
        *,
        token: str = TOKEN,
        event_id: str = "event-1",
        seconds: int = 600,
        occurred_at: datetime | None = None,
    ):
        return client.post(
            "/v1/me/increments",
            headers=auth(token),
            json={
                "event_id": event_id,
                "seconds": seconds,
                "occurred_at": (occurred_at or self.clock["now"]).isoformat(),
            },
        )

    def counts(self) -> dict[str, int]:
        with sqlite3.connect(self.game_db_path) as connection:
            return {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in ("players", "groups", "group_members", "activity_events")
            }


class StartupAndGroupTests(GameAPITestBase):
    def test_startup_waits_for_roster_then_builds_one_group_of_fifteen(self) -> None:
        with self.client(seed_roster=False) as client:
            empty = client.get("/v1/me/league", headers=auth())
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.json()["group_size"], 0)
            self.assertEqual(empty.json()["standings"], [])
            empty_status = client.get("/v1/me/status", headers=auth()).json()
            self.assertIsNone(empty_status["group"])
            self.assertEqual(empty_status["group_size"], 0)
            self.assertIsNone(empty_status["rank"])

            self.seed_channel_roster(client)
            first = client.get("/v1/me/league", headers=auth())
            self.assertEqual(first.status_code, 200)
            payload = first.json()
            self.assertEqual(payload["week_start"], WEEK_START)
            self.assertEqual(payload["group_size"], 15)
            self.assertEqual(len(payload["standings"]), 15)
            self.assertEqual(
                sum(1 for row in payload["standings"] if row["is_me"]), 1
            )
            self.assertEqual(
                sum(1 for row in payload["standings"] if not row["is_me"]), 14
            )
            self.assertEqual(payload["group"]["size"], 15)
            group_id = payload["group_id"]
            self.assertNotIn("kind", first.text)
            self.assertNotIn("is_ai", first.text)
            self.assertNotIn("raw", first.text.lower())
            self.assertNotIn("seconds", json.dumps(payload))
            for row in payload["standings"]:
                self.assertTrue(HIDDEN_FIELDS.isdisjoint(row))
                self.assertIsInstance(row["xp"], int)
            before = self.counts()

        with self.client() as client:
            second = client.get("/v1/league/standings", headers=auth()).json()
            self.assertEqual(second["group_id"], group_id)
            self.assertEqual(second["group_size"], 15)
            after = self.counts()
        self.assertEqual(before, after)
        self.assertEqual(before["players"], 15)
        self.assertEqual(before["groups"], 1)
        self.assertEqual(before["group_members"], 15)

    def test_status_starts_at_zero_and_has_new_shape(self) -> None:
        with self.client() as client:
            response = client.get("/v1/me/status", headers=auth())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user_id"], "owner")
        self.assertEqual(payload["week_start"], WEEK_START)
        self.assertEqual(payload["tier"], "Bronze")
        self.assertEqual(payload["group_size"], 15)
        self.assertIsNotNone(payload["group"])
        self.assertEqual(payload["seconds"], 0)
        self.assertEqual(payload["xp"], 0)
        self.assertEqual(payload["today_seconds"], 0)
        self.assertEqual(payload["today_xp"], 0)
        self.assertEqual(payload["required_xp"], 100)
        self.assertIsNone(payload["checkin"])
        self.assertEqual(payload["rank"], 15)
        self.assertIn("current", payload["streak"])
        self.assertEqual(payload["embers"]["balance"], 0)
        self.assertEqual(payload["embers"]["cap"], 3)
        self.assertEqual(
            payload["next_settlement_at"], "2026-11-02T00:00:00+08:00"
        )
        for key in ("week_total_seconds", "required_seconds", "checked_in_today",
                    "current_streak"):
            self.assertNotIn(key, payload)


class IncrementTests(GameAPITestBase):
    def test_increment_updates_xp_checkin_and_is_idempotent(self) -> None:
        with self.client() as client:
            response = self.post_increment(client, seconds=600)
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertTrue(payload["accepted"])
            self.assertFalse(payload["duplicate"])
            self.assertEqual(payload["week_start"], WEEK_START)
            self.assertEqual(payload["seconds"], 600)
            self.assertEqual(payload["week_seconds"], 600)
            self.assertEqual(payload["week_xp"], 100)
            self.assertEqual(payload["today_seconds"], 600)
            self.assertEqual(payload["today_xp"], 100)
            self.assertEqual(payload["checkin"], "verified")

            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["seconds"], 600)
            self.assertEqual(status["xp"], 100)
            self.assertEqual(status["today_seconds"], 600)
            self.assertEqual(status["today_xp"], 100)
            self.assertEqual(status["checkin"], "verified")
            self.assertEqual(status["streak"]["current"], 1)

            league = client.get("/v1/me/league", headers=auth()).json()
            me = next(row for row in league["standings"] if row["is_me"])
            self.assertEqual(me["xp"], 100)
            self.assertEqual(me["rank"], status["rank"])

            replay = self.post_increment(client, seconds=600)
            self.assertEqual(replay.status_code, 200)
            replay_payload = replay.json()
            self.assertTrue(replay_payload["duplicate"])
            self.assertFalse(replay_payload["accepted"])
            self.assertEqual(replay_payload["week_seconds"], 600)
            self.assertEqual(replay_payload["today_seconds"], 600)
            after = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(after["seconds"], 600)

        with sqlite3.connect(self.game_db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM activity_events WHERE player_id = ?",
                ("owner",),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_future_timestamp_is_422_and_negative_or_zero_seconds_rejected(self) -> None:
        with self.client() as client:
            future = self.post_increment(
                client,
                event_id="future",
                seconds=10,
                occurred_at=NOW + timedelta(hours=1),
            )
            self.assertEqual(future.status_code, 422)
            self.assertEqual(
                future.json()["detail"], "occurred_at must not be in the future"
            )
            for seconds in (0, -1):
                invalid = client.post(
                    "/v1/me/increments",
                    headers=auth(),
                    json={"event_id": f"bad-{seconds}", "seconds": seconds},
                )
                self.assertEqual(invalid.status_code, 422)

    def test_checkin_threshold_is_six_hundred_seconds(self) -> None:
        with self.client() as client:
            under = self.post_increment(client, event_id="under", seconds=599)
            self.assertIsNone(under.json()["checkin"])
            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertIsNone(status["checkin"])
            self.assertEqual(status["today_seconds"], 599)
            crossing = self.post_increment(client, event_id="cross", seconds=1)
            self.assertEqual(crossing.json()["checkin"], "verified")
            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["today_seconds"], 600)
            self.assertEqual(status["checkin"], "verified")


class StandingsTests(GameAPITestBase):
    def test_standings_rank_by_xp_and_hide_ai_internals(self) -> None:
        with self.client() as client:
            response = self.post_increment(
                client, event_id="huge", seconds=500_000
            )
            self.assertEqual(response.status_code, 200)
            league = client.get("/v1/me/league", headers=auth()).json()
            standings = league["standings"]
            self.assertEqual(len(standings), 15)
            self.assertEqual(standings[0]["is_me"], True)
            self.assertEqual(standings[0]["rank"], 1)
            self.assertEqual(league["me"], {"rank": 1, "xp": 83333})
            xp_values = [row["xp"] for row in standings]
            self.assertEqual(xp_values, sorted(xp_values, reverse=True))
            self.assertEqual(
                [row["rank"] for row in standings], list(range(1, 16))
            )
            for row in standings:
                self.assertTrue(HIDDEN_FIELDS.isdisjoint(row))
                self.assertIn("display_name", row)
                self.assertIn("xp", row)
                self.assertIn("is_me", row)
            self.assertNotIn("kind", response.text)
            self.assertNotIn("raw_seconds", response.text)
            self.assertNotIn("effective_seconds", response.text)


class EmberRepairCheckinTests(GameAPITestBase):
    def test_embers_repair_and_daily_checkins(self) -> None:
        saturday = NOW - timedelta(days=2)
        sunday = NOW - timedelta(days=1)
        with self.client() as client:
            earned = self.post_increment(
                client,
                event_id="saturday-work",
                seconds=12_000,
                occurred_at=saturday,
            )
            self.assertEqual(earned.status_code, 200, earned.text)
            short = self.post_increment(
                client,
                event_id="sunday-short",
                seconds=300,
                occurred_at=sunday,
            )
            self.assertEqual(short.status_code, 200, short.text)
            service = client.app.state.game_service
            assert service.store is not None
            service.store.grant_daily_embers(
                "owner", saturday, now=self.clock["now"]
            )

            embers = client.get("/v1/me/embers", headers=auth())
            self.assertEqual(embers.status_code, 200)
            ember_payload = embers.json()
            self.assertEqual(ember_payload["cap"], 3)
            self.assertGreaterEqual(ember_payload["balance"], 1)
            self.assertIsInstance(ember_payload["ledger"], list)
            self.assertTrue(
                any(row["reason"] == "weekly_xp" for row in ember_payload["ledger"])
            )

            balance_before = ember_payload["balance"]
            repaired = client.post(
                "/v1/me/repair",
                headers=auth(),
                json={
                    "date": sunday.date().isoformat(),
                    "idempotency_key": "repair-sunday-1",
                },
            )
            self.assertEqual(repaired.status_code, 200, repaired.text)
            repair_payload = repaired.json()
            self.assertTrue(repair_payload["repaired"])
            self.assertFalse(repair_payload["duplicate"])
            self.assertEqual(repair_payload["date"], sunday.date().isoformat())
            self.assertEqual(repair_payload["embers_spent"], 1)
            self.assertEqual(repair_payload["balance"], balance_before - 1)

            replay = client.post(
                "/v1/me/repair",
                headers=auth(),
                json={
                    "date": sunday.date().isoformat(),
                    "idempotency_key": "repair-sunday-1",
                },
            )
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.json()["duplicate"])
            self.assertEqual(replay.json()["balance"], balance_before - 1)

            week = (sunday - timedelta(days=sunday.weekday())).date().isoformat()
            checkins = client.get(
                f"/v1/me/checkins?week_start={week}", headers=auth()
            )
            self.assertEqual(checkins.status_code, 200)
            payload = checkins.json()
            self.assertEqual(payload["week_start"], week)
            self.assertEqual(len(payload["days"]), 7)
            by_date = {row["date"]: row for row in payload["days"]}
            self.assertTrue(by_date[saturday.date().isoformat()]["checked_in"])
            self.assertEqual(
                by_date[saturday.date().isoformat()]["source"], "verified"
            )
            self.assertEqual(
                by_date[sunday.date().isoformat()]["source"], "repaired"
            )

    def test_repair_requires_idempotency_key_and_valid_window(self) -> None:
        with self.client() as client:
            missing = client.post(
                "/v1/me/repair",
                headers=auth(),
                json={"date": (NOW - timedelta(days=1)).date().isoformat()},
            )
            self.assertEqual(missing.status_code, 422)
            too_old = client.post(
                "/v1/me/repair",
                headers=auth(),
                json={
                    "date": (NOW - timedelta(days=10)).date().isoformat(),
                    "idempotency_key": "old",
                },
            )
            self.assertEqual(too_old.status_code, 422)
            self.assertEqual(too_old.json()["detail"]["code"], "outside_window")


class HistoryTests(GameAPITestBase):
    def test_history_is_empty_before_settlement_then_exposes_weekly_results(self) -> None:
        with self.client() as client:
            empty = client.get("/v1/league/history", headers=auth())
            self.assertEqual(empty.status_code, 200)
            payload = empty.json()
            self.assertEqual(payload["results"], [])
            self.assertNotIn("history", payload)

        previous_week = (NOW - timedelta(days=7)).date().replace(
            day=19
        )
        store = GameStore(self.game_db_path)
        ai_ids = [player["id"] for player in store.list_players(kind="ai")]
        store.create_group(
            previous_week,
            tier="Bronze",
            player_ids=["owner"] + ai_ids,
            now=NOW.isoformat(),
        )
        store.ingest_activity(
            "owner",
            event_id="settled-event",
            seconds=600,
            occurred_at=cal.week_start_at(previous_week) + timedelta(days=2),
            source="local_increment",
            now=NOW.isoformat(),
        )
        store.settle_week(previous_week, now=NOW.isoformat())

        with self.client() as client:
            response = client.get("/v1/league/history", headers=auth())
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["week_start"], previous_week.isoformat())
        self.assertEqual(row["xp"], 100)
        self.assertEqual(row["tier"], "Bronze")
        self.assertIn("rank", row)
        self.assertIn("promoted", row)
        self.assertIn("demoted", row)
        self.assertIn("settled_at", row)


class BadgeReadsNewStateTests(GameAPITestBase):
    def test_badge_and_embed_read_game_status(self) -> None:
        with self.client() as client:
            self.post_increment(client, event_id="badge", seconds=600)
            badge = client.get("/badge/owner.svg")
            embed = client.get("/embed/owner")
        self.assertEqual(badge.status_code, 200)
        self.assertIn("青铜", badge.text)
        self.assertIn("100 XP", badge.text)
        self.assertIn("已打卡", badge.text)
        self.assertNotIn("kind", badge.text)
        self.assertEqual(embed.status_code, 200)
        self.assertIn('src="/badge/owner.svg"', embed.text)


if __name__ == "__main__":
    unittest.main()
