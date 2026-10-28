from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import GameService, create_app
from ghost_league.schedule import TZ

TOKEN = "channel-ingest-user-token"
CHANNEL_TOKEN = "channel-ingest-test-token"
CHANNEL = "fake-channel"
OTHER_CHANNEL = "fake-channel-2"
NOW = datetime(2026, 10, 26, 10, 0, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"
PLAYERS = [
    {"player_ref": "fake-player-a", "kind": "ai"},
    {"player_ref": "fake-player-b", "kind": "ai"},
    {"player_ref": "fake-player-c", "kind": "human"},
]


def auth(token: str = CHANNEL_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_cache(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "users": [
                    {"id": f"legacy-anchor-{index}", "seconds": 10_000 - index * 100}
                    for index in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class TestChannelIngest:
    def setup_method(self) -> None:
        import tempfile

        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.api_dir = self.base / "api"
        self.api_dir.mkdir(parents=True)
        self.cache_path = write_cache(self.base / "cache.json")
        self.game_db_path = self.api_dir / "league.db"
        self.accounts_db = self.api_dir / "accounts.db"
        self.accounts = AccountsStore(self.accounts_db, now_fn=lambda: NOW)
        self.accounts.initialize()
        self.accounts.create("owner", "You", token=TOKEN)

    def teardown_method(self) -> None:
        self._temp.cleanup()

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
            now_fn=lambda: NOW,
        )

    @contextmanager
    def client(self):
        with TestClient(self.app()) as client:
            yield client

    @staticmethod
    def post_roster(client, players, *, channel=CHANNEL, token=CHANNEL_TOKEN):
        return client.post(
            f"/v1/channels/{channel}/roster",
            headers=auth(token),
            json={"players": players},
        )

    @staticmethod
    def post_increment(
        client,
        *,
        player_ref="fake-player-a",
        event_id="event-1",
        seconds=600,
        occurred_at="2026-10-26T09:00:00+08:00",
        channel=CHANNEL,
        token=CHANNEL_TOKEN,
    ):
        return client.post(
            f"/v1/channels/{channel}/increments",
            headers=auth(token),
            json={
                "player_ref": player_ref,
                "event_id": event_id,
                "seconds": seconds,
                "occurred_at": occurred_at,
            },
        )

    def scalar(self, sql: str, params: tuple = ()) -> int:
        with sqlite3.connect(self.game_db_path) as connection:
            return int(connection.execute(sql, params).fetchone()[0])

    def store(self, app):
        return app.state.game_service.store

    def test_roster_is_idempotent_and_keeps_stable_player_ids(self) -> None:
        with self.client() as client:
            first = self.post_roster(client, PLAYERS)
            assert first.status_code == 200, first.text
            first_payload = first.json()
            assert first_payload["count"] == 3
            assert first_payload["created"] == 3
            ids = {row["player_ref"]: row["player_id"] for row in first_payload["players"]}

            second = self.post_roster(
                client,
                [
                    {
                        **PLAYERS[0],
                        "profile": {"display_name": "Fake A", "avatar_url": "/a.webp"},
                    },
                    *PLAYERS[1:],
                ],
            )
            assert second.status_code == 200, second.text
            second_payload = second.json()
            assert second_payload["created"] == 0
            assert second_payload["updated"] == 3
            assert {
                row["player_ref"]: row["player_id"] for row in second_payload["players"]
            } == ids

        assert self.scalar(
            "SELECT COUNT(*) FROM channel_players WHERE channel_id = ?", (CHANNEL,)
        ) == 3
        assert self.scalar(
            "SELECT COUNT(DISTINCT player_id) FROM channel_players WHERE channel_id = ?",
            (CHANNEL,),
        ) == 3

    def test_roster_accepts_a_plain_player_array(self) -> None:
        with self.client() as client:
            response = client.post(
                f"/v1/channels/{CHANNEL}/roster",
                headers=auth(),
                json=[{"player_ref": "array-ref", "kind": "ai"}],
            )
            assert response.status_code == 200, response.text
            assert response.json()["count"] == 1
            assert response.json()["players"][0]["player_ref"] == "array-ref"

    def test_same_player_ref_in_different_channels_does_not_conflict(self) -> None:
        player = {"player_ref": "shared-ref", "kind": "ai"}
        with self.client() as client:
            one = self.post_roster(client, [player], channel="channel-a")
            two = self.post_roster(client, [player], channel="channel-b")
            assert one.status_code == two.status_code == 200
            one_id = one.json()["players"][0]["player_id"]
            two_id = two.json()["players"][0]["player_id"]
            assert one_id != two_id

            first = self.post_increment(
                client,
                channel="channel-a",
                player_ref="shared-ref",
                event_id="same-ref-a",
                seconds=600,
            )
            second = self.post_increment(
                client,
                channel="channel-b",
                player_ref="shared-ref",
                event_id="same-ref-b",
                seconds=300,
            )
            assert first.status_code == second.status_code == 200
            assert first.json()["player_id"] == one_id
            assert second.json()["player_id"] == two_id
            assert first.json()["week_seconds"] == 600
            assert second.json()["week_seconds"] == 300

        assert self.scalar(
            "SELECT COUNT(*) FROM channel_players WHERE player_ref = 'shared-ref'"
        ) == 2

    def test_increment_event_id_is_globally_idempotent(self) -> None:
        with self.client() as client:
            assert self.post_roster(client, [PLAYERS[0]]).status_code == 200
            first = self.post_increment(client, event_id="hour-1", seconds=600)
            assert first.status_code == 200, first.text
            assert first.json()["accepted"] is True
            player_id = first.json()["player_id"]

            replay = self.post_increment(client, event_id="hour-1", seconds=600)
            assert replay.status_code == 200, replay.text
            payload = replay.json()
            assert payload["accepted"] is False
            assert payload["duplicate"] is True
            assert payload["week_seconds"] == 600
            assert payload["week_xp"] == 100
            assert payload["today_xp"] == 100

        assert self.scalar(
            "SELECT COUNT(*) FROM activity_events WHERE player_id = ?",
            (player_id,),
        ) == 1
        assert self.scalar(
            "SELECT COUNT(*) FROM channel_events WHERE event_id = 'hour-1'"
        ) == 1

    def test_increment_for_unknown_roster_is_rejected_without_creating_player(self) -> None:
        with self.client() as client:
            missing = self.post_increment(
                client, player_ref="not-announced", event_id="unknown-1"
            )
            assert missing.status_code == 404, missing.text

            assert self.post_roster(
                client, [{"player_ref": "known-elsewhere", "kind": "ai"}],
                channel=OTHER_CHANNEL,
            ).status_code == 200
            wrong_channel = self.post_increment(
                client,
                channel=CHANNEL,
                player_ref="known-elsewhere",
                event_id="unknown-2",
            )
            assert wrong_channel.status_code == 404, wrong_channel.text

        assert self.scalar(
            "SELECT COUNT(*) FROM channel_players WHERE player_ref = 'not-announced'"
        ) == 0
        assert self.scalar(
            "SELECT COUNT(*) FROM channel_events WHERE event_id IN ('unknown-1', 'unknown-2')"
        ) == 0

    def test_increment_advances_score_today_xp_and_checkin(self) -> None:
        app = self.app()
        with TestClient(app) as client:
            assert self.post_roster(client, [PLAYERS[0]]).status_code == 200
            first = self.post_increment(
                client,
                event_id="morning-1",
                seconds=300,
                occurred_at="2026-10-26T09:00:00+08:00",
            )
            assert first.status_code == 200, first.text
            assert first.json()["checkin"] is None
            assert first.json()["week_xp"] == 50

            second = self.post_increment(
                client,
                event_id="morning-2",
                seconds=300,
                occurred_at="2026-10-26T09:30:00+08:00",
            )
            assert second.status_code == 200, second.text
            payload = second.json()
            assert payload["checkin"] == "verified"
            assert payload["week_start"] == WEEK_START
            assert payload["week_seconds"] == 600
            assert payload["week_xp"] == 100
            assert payload["today_seconds"] == 600
            assert payload["today_xp"] == 100

        store = self.store(app)
        player_id = payload["player_id"]
        score = store.get_week_score(player_id, WEEK_START)
        checkin = store.get_checkin(player_id, "2026-10-26")
        assert score is not None and score["seconds"] == 600 and score["xp"] == 100
        assert store.day_seconds(player_id, "2026-10-26") == 600
        assert checkin is not None
        assert checkin["source"] == "verified"
        assert checkin["xp"] == 100
        assert store.get_streak(player_id)["current"] == 1

    def test_profile_is_display_only_and_does_not_change_scoring(self) -> None:
        app = self.app()
        with TestClient(app) as client:
            roster = self.post_roster(
                client,
                [
                    {
                        "player_ref": "profile-ref",
                        "kind": "ai",
                        "profile": {
                            "display_name": "Snapshot Name",
                            "avatar_url": "/snapshot.webp",
                        },
                    }
                ],
                channel="profile-channel",
            )
            assert roster.status_code == 200, roster.text
            player_id = roster.json()["players"][0]["player_id"]

            first = self.post_increment(
                client,
                channel="profile-channel",
                player_ref="profile-ref",
                event_id="profile-event-1",
                seconds=600,
            )
            assert first.status_code == 200, first.text
            assert first.json()["week_xp"] == 100

            updated = self.post_roster(
                client,
                [
                    {
                        "player_ref": "profile-ref",
                        "kind": "ai",
                        "profile": {"display_name": "Renamed Snapshot"},
                    }
                ],
                channel="profile-channel",
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["players"][0]["player_id"] == player_id

        store = self.store(app)
        player = store.get_player(player_id)
        assert player["display_name"] == "Renamed Snapshot"
        score = store.get_week_score(player_id, WEEK_START)
        assert score is not None and score["seconds"] == 600 and score["xp"] == 100
        mapping = store.get_channel_player("profile-channel", "profile-ref")
        assert mapping is not None
        assert mapping["profile"] == {"display_name": "Renamed Snapshot"}
        with sqlite3.connect(self.game_db_path) as connection:
            event = connection.execute(
                "SELECT * FROM activity_events WHERE player_id = ? AND event_id = ?",
                (player_id, "profile-event-1"),
            ).fetchone()
        assert event is not None
        assert "Snapshot Name" not in json.dumps(list(event))

    def test_channel_profile_name_and_avatar_reach_public_views(self) -> None:
        self.accounts.set_avatar_url("owner", "avatars/owner.webp")
        avatar_url = "https://wakatime.com/photo/avatar-ai"
        app = self.app()
        with TestClient(app) as client:
            roster = self.post_roster(
                client,
                [
                    {
                        "player_ref": "avatar-ai",
                        "kind": "ai",
                        "profile": {
                            "display_name": "Waka Public",
                            "avatar_url": avatar_url,
                        },
                    }
                ],
            )
            assert roster.status_code == 200, roster.text
            player_id = roster.json()["players"][0]["player_id"]

            league = client.get("/v1/league/standings", headers=auth(TOKEN))
            assert league.status_code == 200, league.text
            rows = {
                row["user_id"]: row for row in league.json()["standings"]
            }
            assert rows[player_id]["display_name"] == "Waka Public"
            assert rows[player_id]["avatar_url"] == avatar_url
            assert rows["owner"]["avatar_url"] == "/avatars/owner"

            detail = client.get(f"/v1/users/{player_id}", headers=auth(TOKEN))
            assert detail.status_code == 200, detail.text
            assert detail.json()["display_name"] == "Waka Public"
            assert detail.json()["avatar_url"] == avatar_url
            assert "is_ai" not in detail.json()

            import xml.etree.ElementTree as ET

            badge = client.get(f"/badge/{player_id}.svg")
            assert badge.status_code == 200, badge.text
            ET.fromstring(badge.text)
            assert "Waka Public" in badge.text
            assert "data:image/png;base64," in badge.text
            assert "is_ai" not in badge.text

            inserted = self.post_increment(
                client,
                player_ref="avatar-ai",
                event_id="avatar-feed",
                seconds=600,
            )
            assert inserted.status_code == 200, inserted.text
            feed = client.get("/v1/league/feed", headers=auth(TOKEN))
            assert feed.status_code == 200, feed.text
            item = next(
                item
                for item in feed.json()["items"]
                if item["author"]["id"] == player_id
            )
            assert item["author"]["name"] == "Waka Public"
            assert item["author"]["avatar_url"] == avatar_url
            assert "is_ai" not in item["author"]

    def test_unknown_provider_and_raw_fields_are_rejected(self) -> None:
        with self.client() as client:
            provider_roster = client.post(
                f"/v1/channels/{CHANNEL}/roster",
                headers=auth(),
                json={
                    "provider": "forbidden",
                    "players": [{"player_ref": "bad-ref", "kind": "ai"}],
                },
            )
            assert provider_roster.status_code == 422, provider_roster.text

            raw_player = self.post_roster(
                client,
                [{"player_ref": "bad-ref", "kind": "ai", "raw_seconds": 123}],
            )
            assert raw_player.status_code == 422, raw_player.text

            assert self.post_roster(client, [PLAYERS[0]]).status_code == 200
            raw_increment = client.post(
                f"/v1/channels/{CHANNEL}/increments",
                headers=auth(),
                json={
                    "player_ref": "fake-player-a",
                    "event_id": "bad-event",
                    "seconds": 600,
                    "occurred_at": "2026-10-26T09:00:00+08:00",
                    "provider": "forbidden",
                    "raw_seconds": 600,
                },
            )
            assert raw_increment.status_code == 422, raw_increment.text

        assert self.scalar(
            "SELECT COUNT(*) FROM channel_players WHERE player_ref = 'bad-ref'"
        ) == 0
        assert self.scalar(
            "SELECT COUNT(*) FROM channel_events WHERE event_id = 'bad-event'"
        ) == 0

    def test_channel_service_does_not_need_legacy_cache_or_accounts(self) -> None:
        service = GameService(
            game_db_path=self.base / "standalone" / "league.db",
            cache_path=self.base / "missing-cache.json",
            api_dir=self.base / "standalone-api",
            accounts_db=self.base / "standalone-api" / "accounts.db",
            now_fn=lambda: NOW,
        )
        roster = service.channel_roster(
            "standalone-channel", [{"player_ref": "standalone-ref", "kind": "ai"}]
        )
        assert roster["created"] == 1
        increment = service.channel_increment(
            "standalone-channel",
            player_ref="standalone-ref",
            event_id="standalone-event",
            seconds=600,
            occurred_at=datetime(2026, 10, 26, 9, 0, tzinfo=TZ),
        )
        assert increment["accepted"] is True
        assert increment["week_xp"] == 100

    def test_channel_ingest_does_not_write_legacy_source_or_plan_tables(self) -> None:
        app = self.app()
        with TestClient(app) as client:
            sources_before = self.scalar("SELECT COUNT(*) FROM sources")
            roster = self.post_roster(client, [PLAYERS[0]])
            assert roster.status_code == 200, roster.text
            player_id = roster.json()["players"][0]["player_id"]
            increment = self.post_increment(
                client, event_id="independent-event", seconds=600
            )
            assert increment.status_code == 200, increment.text
            sources_after = self.scalar("SELECT COUNT(*) FROM sources")

        assert sources_after == sources_before
        assert self.scalar(
            "SELECT COUNT(*) FROM opponent_week_plan WHERE player_id = ?",
            (player_id,),
        ) == 0
        with sqlite3.connect(self.game_db_path) as connection:
            source = connection.execute(
                "SELECT source FROM activity_events WHERE player_id = ? AND event_id = ?",
                (player_id, "independent-event"),
            ).fetchone()
        assert source == ("channel_ingest",)

    def test_channel_token_is_separate_from_account_token(self) -> None:
        with self.client() as client:
            no_token = client.post(
                f"/v1/channels/{CHANNEL}/roster",
                json={"players": [PLAYERS[0]]},
            )
            assert no_token.status_code == 401
            account_token = self.post_roster(client, [PLAYERS[0]], token=TOKEN)
            assert account_token.status_code == 401
            channel_token = self.post_roster(client, [PLAYERS[0]])
            assert channel_token.status_code == 200
