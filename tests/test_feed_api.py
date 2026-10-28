from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

from ghost_league.game.feed import allowed_tags

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_api_game import WEEK_START, GameAPITestBase, auth  # noqa: E402

PREV_WEEK = "2026-10-19"
FORBIDDEN = ("seconds", "minutes", "ghost", "synthetic", "模拟", "真人")


def feed_payload(response) -> list[dict]:
    payload = response.json()
    assert isinstance(payload, dict)
    assert isinstance(payload["items"], list)
    return payload["items"]


class FeedAPITests(GameAPITestBase):
    def event_count(self, table: str) -> int:
        with sqlite3.connect(self.game_db_path) as connection:
            return int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )

    def test_01_checkin_feed_is_idempotent_and_ai_reacts(self) -> None:
        with self.client() as client:
            increment = self.post_increment(client, seconds=8040)
            self.assertEqual(increment.status_code, 200, increment.text)
            self.assertTrue(increment.json()["checkin"] == "verified")

            response = client.get("/v1/league/feed", headers=auth())
            self.assertEqual(response.status_code, 200, response.text)
            items = feed_payload(response)
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(set(item), {
                "id", "kind", "day", "body", "author",
                "reactions", "tags", "created_at",
            })
            self.assertEqual(item["kind"], "checkin")
            self.assertEqual(item["day"], WEEK_START)
            self.assertEqual(item["body"], "今天点着了 1,340 XP")
            self.assertEqual(
                set(item["author"]),
                {"id", "name", "title", "frame", "avatar_url"},
            )
            self.assertNotIn("is_ai", item["author"])
            self.assertNotIn("source_ref", response.text)
            self.assertNotIn("channel_id", response.text)
            for forbidden in FORBIDDEN:
                self.assertNotIn(forbidden, response.text.lower())

            with sqlite3.connect(self.game_db_path) as connection:
                actors = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT actor_id FROM feed_reactions WHERE event_id = ?",
                        (item["id"],),
                    )
                ]
                tag_rows = connection.execute(
                    "SELECT actor_id, tag FROM feed_tags WHERE event_id = ?",
                    (item["id"],),
                ).fetchall()
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM feed_events WHERE id = ?",
                        (item["id"],),
                    ).fetchone()[0]
                )
            self.assertGreaterEqual(len(actors), 1)
            self.assertLessEqual(len(actors), 3)
            self.assertEqual(len(set(actors)), len(actors))
            allowed = set(allowed_tags("checkin", payload))
            self.assertTrue({str(row[1]) for row in tag_rows} <= allowed)

            before = (
                self.event_count("feed_events"),
                self.event_count("feed_reactions"),
                self.event_count("feed_tags"),
            )
            replay = self.post_increment(client, seconds=8040)
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.json()["duplicate"])
            after = (
                self.event_count("feed_events"),
                self.event_count("feed_reactions"),
                self.event_count("feed_tags"),
            )
            self.assertEqual(after, before)
            self.assertEqual(len(feed_payload(client.get("/v1/league/feed", headers=auth()))), 1)

    def test_02_human_reaction_is_idempotent_and_visibility_is_enforced(self) -> None:
        with self.client() as client:
            self.post_increment(client, seconds=600)
            item = feed_payload(client.get("/v1/league/feed", headers=auth()))[0]
            before = next(
                (
                    reaction["count"]
                    for reaction in item["reactions"]
                    if reaction["emoji"] == "盯"
                ),
                0,
            )
            first = client.post(
                f"/v1/league/feed/{item['id']}/reactions",
                headers=auth(),
                json={"emoji": "盯"},
            )
            self.assertEqual(first.status_code, 200, first.text)
            mine = next(
                reaction
                for reaction in first.json()["reactions"]
                if reaction["emoji"] == "盯"
            )
            self.assertTrue(mine["mine"])
            self.assertEqual(mine["count"], before + 1)
            second = client.post(
                f"/v1/league/feed/{item['id']}/reactions",
                headers=auth(),
                json={"emoji": "盯"},
            )
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["reactions"], first.json()["reactions"])

            self.assertEqual(
                client.post(
                    f"/v1/league/feed/{item['id']}/reactions",
                    headers=auth(),
                    json={"emoji": "不存在"},
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    f"/v1/league/feed/{item['id']}/reactions",
                    headers=auth(),
                    json={"emoji": "盯", "extra": True},
                ).status_code,
                422,
            )

            with sqlite3.connect(self.game_db_path) as connection:
                cursor = connection.execute(
                    "INSERT INTO feed_events "
                    "(player_id, kind, day, week_start, body, payload_json, created_at) "
                    "VALUES ('outsider', 'checkin', ?, ?, ?, ?, ?)",
                    (
                        WEEK_START,
                        WEEK_START,
                        "今天点着了 100 XP",
                        '{"xp": 100}',
                        "2026-10-26T10:00:00+08:00",
                    ),
                )
                outsider_event = int(cursor.lastrowid)
            hidden = client.post(
                f"/v1/league/feed/{outsider_event}/reactions",
                headers=auth(),
                json={"emoji": "盯"},
            )
            self.assertEqual(hidden.status_code, 404)

            # Following one outsider makes only that person's real event visible.
            service = client.app.state.game_service
            store = service.store
            store.create_player(
                "outside-human",
                kind="human",
                joined_week=WEEK_START,
                now="2026-10-26T10:00:00+08:00",
            )
            store.create_group(
                WEEK_START,
                tier="Bronze",
                player_ids=["outside-human"],
                now="2026-10-26T10:00:00+08:00",
            )
            store.ingest_activity(
                "outside-human",
                event_id="outside-event",
                seconds=600,
                occurred_at="2026-10-26T12:00:00+08:00",
                source="local_increment",
                now="2026-10-26T12:00:00+08:00",
            )
            feed = feed_payload(client.get("/v1/league/feed", headers=auth()))
            self.assertNotIn(
                "outside-human", {entry["author"]["id"] for entry in feed}
            )
            follow = client.post(
                "/v1/me/follows/outside-human", headers=auth()
            )
            self.assertEqual(follow.status_code, 200, follow.text)
            feed = feed_payload(client.get("/v1/league/feed", headers=auth()))
            self.assertIn(
                "outside-human", {entry["author"]["id"] for entry in feed}
            )

    def test_03_weekly_results_generate_promoted_and_champion_events(self) -> None:
        with self.client() as client:
            league = client.get("/v1/me/league", headers=auth()).json()
            player_ids = [row["user_id"] for row in league["standings"]]
            self.assertEqual(len(player_ids), 15)
            store = client.app.state.game_service.store
            store.create_group(
                PREV_WEEK,
                tier="Bronze",
                player_ids=player_ids,
                now=f"{PREV_WEEK}T00:00:00+08:00",
            )
            for index, player_id in enumerate(player_ids):
                store.ingest_activity(
                    player_id,
                    event_id=f"prev:{player_id}",
                    seconds=15000 - index * 500,
                    occurred_at=f"{PREV_WEEK}T12:00:00+08:00",
                    source="local_increment",
                    now=f"{PREV_WEEK}T12:00:00+08:00",
                )
            settled = store.settle_week(PREV_WEEK, now=self.clock["now"])
            self.assertEqual(settled["already_settled"], False)
            self.assertEqual(len(settled["results"]), 15)

            response = client.get("/v1/league/feed?limit=50", headers=auth())
            self.assertEqual(response.status_code, 200, response.text)
            items = feed_payload(response)
            kinds = {item["kind"] for item in items}
            self.assertIn("promoted", kinds)
            self.assertIn("champion", kinds)
            champion = next(item for item in items if item["kind"] == "champion")
            self.assertIn("小组拿下第一", champion["body"])
            promoted = next(item for item in items if item["kind"] == "promoted")
            self.assertIn("这周从青铜升到白银", promoted["body"])
            for item in items:
                for forbidden in FORBIDDEN:
                    self.assertNotIn(forbidden, item["body"].lower())

            before = (
                self.event_count("feed_events"),
                self.event_count("feed_reactions"),
                self.event_count("feed_tags"),
            )
            replay = store.settle_week(PREV_WEEK, now=self.clock["now"])
            self.assertTrue(replay["already_settled"])
            after = (
                self.event_count("feed_events"),
                self.event_count("feed_reactions"),
                self.event_count("feed_tags"),
            )
            self.assertEqual(after, before)

    def test_04_feed_requires_auth_and_rejects_bad_limits(self) -> None:
        with self.client() as client:
            self.assertEqual(
                client.get("/v1/league/feed").status_code,
                401,
            )
            self.assertEqual(
                client.post(
                    "/v1/league/feed/1/reactions", json={"emoji": "盯"}
                ).status_code,
                401,
            )
            self.assertEqual(
                client.get("/v1/league/feed?limit=0", headers=auth()).status_code,
                422,
            )
            self.assertEqual(
                client.get("/v1/league/feed?limit=51", headers=auth()).status_code,
                422,
            )


if __name__ == "__main__":
    unittest.main()
