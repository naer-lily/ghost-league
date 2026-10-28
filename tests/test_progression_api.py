from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.schedule import TZ

TOKEN = "progression-token"
CHANNEL_TOKEN = "progression-channel-token"
CHANNEL = "progression-channel"
NOW = datetime(2026, 10, 28, 10, 0, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"
BANNED = ("seconds", "minutes", "ghost", "synthetic", "模拟", "真人")


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ProgressionAPITest(unittest.TestCase):
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

    def seed_roster(self, client: TestClient) -> None:
        response = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=auth(CHANNEL_TOKEN),
            json={
                "players": [
                    {"player_ref": f"channel-ai-{index:02d}", "kind": "ai"}
                    for index in range(14)
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def increment(
        self,
        client: TestClient,
        *,
        event_id: str,
        seconds: int = 600,
        occurred_at: datetime | None = None,
    ):
        return client.post(
            "/v1/me/increments",
            headers=auth(),
            json={
                "event_id": event_id,
                "seconds": seconds,
                "occurred_at": (occurred_at or self.clock["now"]).isoformat(),
            },
        )

    def test_collection_loadout_user_and_standings_expose_unlocked_display(
        self,
    ) -> None:
        with TestClient(self.app()) as client:
            self.seed_roster(client)
            response = self.increment(client, event_id="first-checkin")
            self.assertEqual(response.status_code, 200, response.text)

            collection = client.get("/v1/me/collection", headers=auth())
            self.assertEqual(collection.status_code, 200, collection.text)
            payload = collection.json()
            self.assertEqual(payload["titles"][0]["name"], "点火")
            self.assertEqual(payload["items"][0]["name"], "余烬")
            self.assertEqual(payload["items"][0]["slot"], "frame")
            self.assertEqual(payload["equipped"]["title_id"], None)

            equipped = client.patch(
                "/v1/me/loadout",
                headers=auth(),
                json={"title_id": "title_ignition", "frame_id": "frame_ember"},
            )
            self.assertEqual(equipped.status_code, 200, equipped.text)
            self.assertEqual(equipped.json()["title"], "点火")
            self.assertEqual(equipped.json()["frame"], "余烬")

            after = client.get("/v1/me/collection", headers=auth()).json()
            self.assertTrue(after["titles"][0]["equipped"])
            self.assertTrue(after["items"][0]["equipped"])

            badge = client.get("/badge/owner.svg")
            self.assertEqual(badge.status_code, 200, badge.text)
            self.assertIn("称号 · 点火", badge.text)
            self.assertIn('viewBox="0 0 880 260"', badge.text)
            self.assertIn('class="badge-frame" data-frame="frame_ember"', badge.text)
            self.assertIn('class="badge-frame-image"', badge.text)
            self.assertIn('href="data:image/png;base64,', badge.text)

            status = client.get("/v1/me/status", headers=auth())
            self.assertEqual(status.status_code, 200, status.text)
            self.assertEqual(status.json()["equipped_title"], "点火")
            self.assertEqual(status.json()["equipped_title_id"], "title_ignition")
            self.assertEqual(status.json()["frame"], "余烬")
            self.assertEqual(status.json()["frame_id"], "frame_ember")
            self.assertNotIn("is_ai", status.json())

            detail = client.get("/v1/users/owner", headers=auth())
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()["equipped_title"], "点火")
            self.assertEqual(detail.json()["frame"], "余烬")
            self.assertNotIn("is_ai", detail.json())

            standings = client.get("/v1/league/standings", headers=auth())
            self.assertEqual(standings.status_code, 200, standings.text)
            me = next(row for row in standings.json()["standings"] if row["is_me"])
            self.assertEqual(me["title"], "点火")
            self.assertEqual(me["frame"], "余烬")
            self.assertNotIn("is_ai", me)
            self.assertTrue(
                all("is_ai" not in row for row in standings.json()["standings"])
            )
            combined = json.dumps(
                [payload, equipped.json(), detail.json(), standings.json()],
                ensure_ascii=False,
            ).lower()
            for word in BANNED:
                self.assertNotIn(word, combined)

    def test_unknown_locked_and_wrong_slot_loadouts_are_422(self) -> None:
        with TestClient(self.app()) as client:
            self.seed_roster(client)
            self.assertEqual(
                self.increment(client, event_id="first-checkin").status_code, 200
            )
            for body in (
                {"title_id": "missing"},
                {"frame_id": "missing"},
                {"backdrop_id": "backdrop_night"},
                {"badge_accent_id": "badge_champion"},
                {"title_id": "frame_ember"},
                {"frame_id": "badge_champion"},
            ):
                response = client.patch(
                    "/v1/me/loadout", headers=auth(), json=body
                )
                self.assertEqual(response.status_code, 422, (body, response.text))

    def test_three_day_streak_unlocks_title_through_real_checkins(self) -> None:
        with TestClient(self.app()) as client:
            self.seed_roster(client)
            for offset, event_id in enumerate(("day-1", "day-2", "day-3")):
                response = self.increment(
                    client,
                    event_id=event_id,
                    occurred_at=NOW - timedelta(days=2 - offset),
                )
                self.assertEqual(response.status_code, 200, response.text)
            payload = client.get("/v1/me/collection", headers=auth()).json()
            names = [row["name"] for row in payload["titles"]]
            self.assertIn("三日不息", names)

    def test_ai_gets_same_awards_and_standings_flag_without_internal_target(
        self,
    ) -> None:
        with TestClient(self.app()) as client:
            self.seed_roster(client)
            response = client.post(
                f"/v1/channels/{CHANNEL}/increments",
                headers=auth(CHANNEL_TOKEN),
                json={
                    "player_ref": "channel-ai-00",
                    "event_id": "ai-checkin",
                    "seconds": 600,
                    "occurred_at": self.clock["now"].isoformat(),
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            ai_id = response.json()["player_id"]
            league = client.get("/v1/league/standings", headers=auth())
            self.assertEqual(league.status_code, 200, league.text)
            ai_row = next(
                row for row in league.json()["standings"] if row["user_id"] == ai_id
            )
            self.assertNotIn("is_ai", ai_row)
            self.assertEqual(ai_row["title"], "点火")
            self.assertEqual(ai_row["frame"], "余烬")

            detail = client.get(f"/v1/users/{ai_id}", headers=auth())
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertNotIn("is_ai", detail.json())
            self.assertEqual(detail.json()["equipped_title"], "点火")
            rendered = json.dumps(league.json(), ensure_ascii=False).lower()
            for word in BANNED:
                self.assertNotIn(word, rendered)
            for hidden in ("target_seconds", "anchor_seconds", "source_key_hash"):
                self.assertNotIn(hidden, rendered)


if __name__ == "__main__":
    unittest.main()
