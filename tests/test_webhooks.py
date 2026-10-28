from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.schedule import TZ
from ghost_league.webhooks import (
    ALLOWED_EVENTS,
    MAX_ATTEMPTS,
    STREAK_MILESTONES,
    WebhookService,
    format_event_injector_content,
    sign_payload,
    sign_payload_hex,
    validate_webhook_url,
)

TOKEN = "webhook-owner-token"
FRIEND_TOKEN = "webhook-friend-token"
CHANNEL_TOKEN = "webhook-channel-token"
CHANNEL = "webhook-channel"
NOW = datetime(2026, 10, 26, 18, 36, 0, tzinfo=TZ)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_fixture(base: Path) -> tuple[Path, Path, Path, Path, dict]:
    state_path = base / "state.json"
    cache_path = base / "cache.json"
    api_dir = base / "api"
    accounts_db = api_dir / "accounts.db"
    webhooks_db = api_dir / "webhooks.db"
    users = [
        {
            "user_id": "owner",
            "name": "You",
            "tier": "Bronze",
            "joined_week": 53,
            "weeks_played": 0,
            "best_tier": "Bronze",
            "history": [],
        }
    ]
    cache_users = []
    for index in range(1, 14):
        user_id = f"ghost-{index:02d}"
        users.append(
            {
                "user_id": user_id,
                "name": f"Ghost {index:02d}",
                "tier": "Bronze",
                "joined_week": 1,
                "weeks_played": 52,
                "best_tier": "Bronze",
                "history": [],
            }
        )
        cache_users.append(
            {
                "id": user_id,
                "name": f"Ghost {index:02d}",
                "seconds": 36_000 + index * 2_500,
            }
        )
    state = {
        "schema_version": 1,
        "settled_weeks": 52,
        "week_numbers": list(range(1, 53)),
        "user_count": len(users),
        "rules": {},
        "tier_counts": {"Bronze": len(users)},
        "users": users,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    cache_path.write_text(json.dumps({"source": "test", "users": cache_users}), encoding="utf-8")
    accounts = AccountsStore(accounts_db, now_fn=lambda: NOW)
    accounts.initialize()
    accounts.create("owner", "You", token=TOKEN)
    accounts.create("friend-1", "Friend", token=FRIEND_TOKEN)
    return state_path, cache_path, accounts_db, webhooks_db, state


class Receiver:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code
        self.received: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.received.append(
                    {
                        "path": self.path,
                        "headers": {key.lower(): value for key, value in self.headers.items()},
                        "body": body,
                    }
                )
                self.send_response(outer.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, format, *args):  # noqa: A003
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/hook"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class URLValidationTests(unittest.TestCase):
    def test_01_domain_urls_are_accepted_without_dns(self) -> None:
        self.assertEqual(
            validate_webhook_url("https://example.com/hooks/ghost"),
            "https://example.com/hooks/ghost",
        )
        self.assertEqual(
            validate_webhook_url("https://hooks.example.com:8443/path"),
            "https://hooks.example.com:8443/path",
        )

    def test_02_ip_localhost_and_http_are_rejected_without_force(self) -> None:
        for url in (
            "https://127.0.0.1/hook",
            "https://[::1]/hook",
            "https://localhost/hook",
            "https://example/hook",
            "http://example.com/hook",
            "ftp://example.com/hook",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_webhook_url(url)

    def test_03_force_allows_private_http_ip(self) -> None:
        self.assertEqual(
            validate_webhook_url("http://198.51.100.10:8099/events", force=True),
            "http://198.51.100.10:8099/events",
        )
        self.assertEqual(
            validate_webhook_url("http://127.0.0.1:9000/hook", force=True),
            "http://127.0.0.1:9000/hook",
        )


class WebhookAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (
            self.state_path,
            self.cache_path,
            self.accounts_db,
            self.webhooks_db,
            self.state,
        ) = make_fixture(self.base)
        self.clock = {"now": NOW}
        self.app = create_app(
            game_db_path=self.base / "league.db",
            state_path=self.state_path,
            cache_path=self.cache_path,
            avatars_path=self.base / "avatars.json",
            api_dir=self.base / "api",
            accounts_db=self.accounts_db,
            webhooks_db=self.webhooks_db,
            start_webhook_worker=False,
            token=TOKEN,
            now_fn=lambda: self.clock["now"],
        )

    def test_04_create_returns_secret_once_and_list_hides_it(self) -> None:
        with TestClient(self.app) as client:
            created = client.post(
                "/v1/me/webhooks",
                headers=AUTH,
                json={
                    "url": "https://example.com/hook",
                    "events": ["checkin.completed"],
                },
            )
            self.assertEqual(created.status_code, 200)
            payload = created.json()
            self.assertTrue(payload["secret"].startswith("whsec_"))
            self.assertEqual(payload["events"], ["checkin.completed"])
            self.assertEqual(payload["transport"], "generic")
            listed = client.get("/v1/me/webhooks", headers=AUTH)
            self.assertEqual(listed.status_code, 200)
            items = listed.json()
            self.assertEqual(len(items), 1)
            self.assertNotIn("secret", items[0])
            self.assertEqual(items[0]["id"], payload["id"])

    def test_05_invalid_urls_and_missing_webhooks(self) -> None:
        with TestClient(self.app) as client:
            for url in (
                "https://127.0.0.1/hook",
                "https://[::1]/hook",
                "http://example.com/hook",
            ):
                response = client.post(
                    "/v1/me/webhooks",
                    headers=AUTH,
                    json={"url": url, "events": ["checkin.completed"]},
                )
                self.assertEqual(response.status_code, 422)
            self.assertEqual(client.get("/v1/me/webhooks").status_code, 401)
            self.assertEqual(
                client.patch(
                    "/v1/me/webhooks/9999",
                    headers=AUTH,
                    json={"active": False},
                ).status_code,
                404,
            )
            self.assertEqual(
                client.post("/v1/me/webhooks/9999/test", headers=AUTH).status_code,
                404,
            )
            self.assertEqual(
                client.delete("/v1/me/webhooks/9999", headers=AUTH).status_code,
                404,
            )

    def test_06_only_owner_can_manage_or_test(self) -> None:
        receiver = Receiver()
        self.addCleanup(receiver.close)
        with TestClient(self.app) as client:
            webhook = self.app.state.webhook_service.create_webhook(
                "owner",
                receiver.url,
                ["checkin.completed"],
                force=True,
            )
            webhook_id = webhook["id"]
            self.assertEqual(
                client.patch(
                    f"/v1/me/webhooks/{webhook_id}",
                    headers=auth(FRIEND_TOKEN),
                    json={"active": False},
                ).status_code,
                404,
            )
            self.assertEqual(
                client.delete(
                    f"/v1/me/webhooks/{webhook_id}",
                    headers=auth(FRIEND_TOKEN),
                ).status_code,
                404,
            )
            self.assertEqual(
                client.post(
                    f"/v1/me/webhooks/{webhook_id}/test",
                    headers=auth(FRIEND_TOKEN),
                ).status_code,
                404,
            )

    def test_07_test_endpoint_delivers_immediately_and_signs(self) -> None:
        receiver = Receiver()
        self.addCleanup(receiver.close)
        with TestClient(self.app) as client:
            webhook = self.app.state.webhook_service.create_webhook(
                "owner",
                receiver.url,
                ["webhook.test"],
                force=True,
            )
            response = client.post(
                f"/v1/me/webhooks/{webhook['id']}/test",
                headers=AUTH,
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["status"], "delivered")
            self.assertNotIn("secret", body)
        self.assertEqual(len(receiver.received), 1)
        request = receiver.received[0]
        timestamp = request["headers"]["x-ghost-timestamp"]
        self.assertEqual(timestamp, request["headers"]["x-webhook-timestamp"])
        self.assertTrue(timestamp.isdigit())
        self.assertEqual(
            request["headers"]["x-ghost-signature"],
            sign_payload(webhook["secret"], timestamp, request["body"]),
        )
        self.assertEqual(
            request["headers"]["x-webhook-signature-v2"],
            sign_payload_hex(webhook["secret"], timestamp, request["body"]),
        )
        event = json.loads(request["body"])
        self.assertEqual(event["type"], "webhook.test")
        self.assertEqual(event["version"], 1)
        self.assertIn("date", event["data"])
        self.assertIn("today_seconds", event["data"])
        self.assertIn("current_streak", event["data"])
        self.assertIn("week_start", event["data"])
        with TestClient(self.app) as client:
            listed = client.get("/v1/me/webhooks", headers=AUTH).json()
        self.assertEqual(listed[0]["last_status"], "delivered")
        self.assertIsNotNone(listed[0]["latest_delivery"])
        self.assertNotIn("secret", listed[0])

    def test_13_transport_roundtrip_and_validation(self) -> None:
        with TestClient(self.app) as client:
            created = client.post(
                "/v1/me/webhooks",
                headers=AUTH,
                json={
                    "url": "https://example.com/hook",
                    "events": ["webhook.test"],
                    "transport": "event_injector",
                },
            )
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["transport"], "event_injector")
            webhook_id = created.json()["id"]
            listed = client.get("/v1/me/webhooks", headers=AUTH).json()
            self.assertEqual(listed[0]["transport"], "event_injector")
            updated = client.patch(
                f"/v1/me/webhooks/{webhook_id}",
                headers=AUTH,
                json={"transport": "generic"},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["transport"], "generic")
            invalid = client.patch(
                f"/v1/me/webhooks/{webhook_id}",
                headers=AUTH,
                json={"transport": "not-a-transport"},
            )
            self.assertEqual(invalid.status_code, 422)

    def test_18_test_endpoint_delivers_event_injector(self) -> None:
        receiver = Receiver()
        self.addCleanup(receiver.close)
        with TestClient(self.app) as client:
            webhook = self.app.state.webhook_service.create_webhook(
                "owner",
                receiver.url,
                ["webhook.test"],
                transport="event_injector",
                force=True,
            )
            response = client.post(
                f"/v1/me/webhooks/{webhook['id']}/test",
                headers=AUTH,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "delivered")
        self.assertEqual(len(receiver.received), 1)
        request = receiver.received[0]
        self.assertEqual(request["headers"]["x-event-token"], webhook["secret"])
        self.assertNotIn("x-ghost-signature", request["headers"])
        body = json.loads(request["body"])
        self.assertEqual(set(body), {"content", "role"})
        self.assertIn(
            "【Ghost League】检测到系统事件：测试事件（webhook.test）。",
            body["content"],
        )
        self.assertIn("请查询 Ghost League 当前状态", body["content"])
        self.assertNotIn("本周：", body["content"])

    def test_12_patch_url_validation_active_and_delete(self) -> None:
        with TestClient(self.app) as client:
            created = client.post(
                "/v1/me/webhooks",
                headers=AUTH,
                json={
                    "url": "https://example.com/hook",
                    "events": ["checkin.completed"],
                },
            ).json()
            webhook_id = created["id"]
            invalid = client.patch(
                f"/v1/me/webhooks/{webhook_id}",
                headers=AUTH,
                json={"url": "https://127.0.0.1/hook"},
            )
            self.assertEqual(invalid.status_code, 422)

            updated = client.patch(
                f"/v1/me/webhooks/{webhook_id}",
                headers=AUTH,
                json={"active": False, "events": ["webhook.test"]},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertFalse(updated.json()["active"])
            self.assertEqual(updated.json()["events"], ["webhook.test"])
            self.assertNotIn("secret", updated.json())

            self.assertEqual(
                client.delete(f"/v1/me/webhooks/{webhook_id}", headers=AUTH).status_code,
                204,
            )
            self.assertEqual(
                client.delete(f"/v1/me/webhooks/{webhook_id}", headers=AUTH).status_code,
                404,
            )


class DeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_08_checkin_outbox_crosses_600_once_and_is_signed(self) -> None:
        receiver = Receiver()
        self.addCleanup(receiver.close)
        state_path, cache_path, accounts_db, webhooks_db, _ = make_fixture(self.base)
        clock = {"now": NOW}
        app = create_app(
            game_db_path=self.base / "league.db",
            state_path=state_path,
            cache_path=cache_path,
            avatars_path=self.base / "avatars.json",
            api_dir=self.base / "api",
            accounts_db=accounts_db,
            webhooks_db=webhooks_db,
            start_webhook_worker=False,
            token=TOKEN,
            now_fn=lambda: clock["now"],
        )
        with TestClient(app) as client:
            profile = client.patch(
                "/v1/me/profile",
                headers=AUTH,
                json={"activity_label": "骑行"},
            )
            self.assertEqual(profile.status_code, 200)
            webhook = app.state.webhook_service.create_webhook(
                "owner",
                receiver.url,
                ["checkin.completed"],
                force=True,
            )
            first = client.post(
                "/v1/me/increments",
                headers=AUTH,
                json={"event_id": "under-600", "seconds": 599},
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(receiver.received, [])

            crossing = client.post(
                "/v1/me/increments",
                headers=AUTH,
                json={"event_id": "cross-600", "seconds": 1},
            )
            self.assertEqual(crossing.status_code, 200)
            self.assertEqual(receiver.received, [])
            app.state.webhook_service.process_due()
            self.assertEqual(len(receiver.received), 1)

            request = receiver.received[0]
            timestamp = request["headers"]["x-ghost-timestamp"]
            self.assertTrue(timestamp.isdigit())
            self.assertEqual(timestamp, request["headers"]["x-webhook-timestamp"])
            self.assertEqual(
                request["headers"]["x-ghost-signature"],
                sign_payload(webhook["secret"], timestamp, request["body"]),
            )
            self.assertEqual(
                request["headers"]["x-webhook-signature-v2"],
                sign_payload_hex(webhook["secret"], timestamp, request["body"]),
            )
            self.assertNotIn(webhook["secret"], request["body"].decode("utf-8"))
            self.assertEqual(
                request["headers"]["x-ghost-event-id"],
                "checkin:owner:2026-10-26",
            )
            payload = json.loads(request["body"])
            self.assertEqual(payload["id"], "checkin:owner:2026-10-26")
            self.assertEqual(payload["type"], "checkin.completed")
            self.assertEqual(payload["data"]["date"], "2026-10-26")
            self.assertEqual(payload["data"]["today_seconds"], 600)
            self.assertEqual(payload["data"]["current_streak"], 1)
            self.assertEqual(payload["data"]["week_start"], "2026-10-26")
            self.assertEqual(payload["data"]["activity_label"], "骑行")

            duplicate = client.post(
                "/v1/me/increments",
                headers=AUTH,
                json={"event_id": "cross-600", "seconds": 1},
            )
            self.assertTrue(duplicate.json()["duplicate"])
            app.state.webhook_service.process_due()
            self.assertEqual(len(receiver.received), 1)

            extra = client.post(
                "/v1/me/increments",
                headers=AUTH,
                json={"event_id": "after-checkin", "seconds": 600},
            )
            self.assertEqual(extra.status_code, 200)
            app.state.webhook_service.process_due()
            self.assertEqual(len(receiver.received), 1)

            webhook_state = app.state.webhook_service.get_webhook(
                "owner", webhook["id"]
            )
            self.assertEqual(webhook_state["last_status"], "delivered")
            with sqlite3.connect(webhooks_db) as connection:
                deliveries = connection.execute(
                    "SELECT event_id, event_type, status, attempts FROM webhook_deliveries"
                ).fetchall()
            self.assertEqual(
                deliveries,
                [("checkin:owner:2026-10-26", "checkin.completed", "delivered", 1)],
            )

    def test_09_failures_retry_with_backoff_then_fail(self) -> None:
        receiver = Receiver(status_code=500)
        self.addCleanup(receiver.close)
        clock = {"now": NOW}
        service = WebhookService(
            self.base / "webhooks.db",
            now_fn=lambda: clock["now"],
            timeout=2,
        )
        service.initialize()
        webhook = service.create_webhook(
            "owner",
            receiver.url,
            ["webhook.test"],
            force=True,
        )
        delivery_id = service.enqueue_test(
            user_id="owner",
            webhook_id=webhook["id"],
            date="2026-10-26",
            today_seconds=600,
            current_streak=1,
            week_start="2026-10-26",
            occurred_at=NOW.isoformat(),
        )
        self.assertIsNotNone(delivery_id)

        first = service.process_due()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["attempts"], 1)
        self.assertEqual(first[0]["status"], "pending")
        self.assertIsNotNone(first[0]["next_attempt_at"])

        clock["now"] = NOW.replace(minute=37)
        second = service.process_due()
        self.assertEqual(second[0]["attempts"], 2)
        self.assertEqual(second[0]["status"], "pending")

        clock["now"] = NOW.replace(minute=42)
        third = service.process_due()
        self.assertEqual(third[0]["attempts"], 3)
        self.assertEqual(third[0]["status"], "pending")

        clock["now"] = NOW.replace(hour=19, minute=13)
        fourth = service.process_due()
        self.assertEqual(fourth[0]["attempts"], 4)
        self.assertEqual(fourth[0]["status"], "failed")
        self.assertEqual(MAX_ATTEMPTS, 4)
        self.assertEqual(len(receiver.received), 4)
        timestamps = [item["headers"]["x-webhook-timestamp"] for item in receiver.received]
        self.assertEqual(len(set(timestamps)), 4)
        for request in receiver.received:
            timestamp = request["headers"]["x-webhook-timestamp"]
            self.assertTrue(timestamp.isdigit())
            self.assertEqual(
                request["headers"]["x-webhook-signature-v2"],
                sign_payload_hex(webhook["secret"], timestamp, request["body"]),
            )
            self.assertEqual(
                request["headers"]["x-ghost-signature"],
                sign_payload(webhook["secret"], timestamp, request["body"]),
            )
            self.assertNotIn(webhook["secret"], request["body"].decode("utf-8"))
        state = service.get_webhook("owner", webhook["id"])
        self.assertEqual(state["last_status"], "failed")
        self.assertEqual(state["failure_count"], 4)
        self.assertNotIn(webhook["secret"], json.dumps(state))

    def test_10_restart_continues_pending_delivery(self) -> None:
        receiver = Receiver()
        self.addCleanup(receiver.close)
        db = self.base / "webhooks.db"
        clock = {"now": NOW}
        first = WebhookService(db, now_fn=lambda: clock["now"], timeout=2)
        first.initialize()
        webhook = first.create_webhook(
            "owner",
            receiver.url,
            ["webhook.test"],
            force=True,
        )
        delivery_id = first.enqueue_test(
            user_id="owner",
            webhook_id=webhook["id"],
            date="2026-10-26",
            today_seconds=0,
            current_streak=0,
            week_start="2026-10-26",
            occurred_at=NOW.isoformat(),
        )
        self.assertIsNotNone(delivery_id)
        self.assertEqual(receiver.received, [])

        second = WebhookService(db, now_fn=lambda: clock["now"], timeout=2)
        second.initialize()
        delivered = second.process_due()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["status"], "delivered")
        self.assertEqual(len(receiver.received), 1)


class DerivedEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.clock = {"now": NOW}

    def _make_app(self):
        state_path, cache_path, accounts_db, webhooks_db, _ = make_fixture(self.base)
        app = create_app(
            game_db_path=self.base / "league.db",
            state_path=state_path,
            cache_path=cache_path,
            avatars_path=self.base / "avatars.json",
            api_dir=self.base / "api",
            accounts_db=accounts_db,
            webhooks_db=webhooks_db,
            start_webhook_worker=False,
            token=TOKEN,
            channel_token=CHANNEL_TOKEN,
            now_fn=lambda: self.clock["now"],
        )
        return app, webhooks_db

    def _seed_roster(self, client: TestClient, *, players: int = 14) -> None:
        response = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=auth(CHANNEL_TOKEN),
            json={
                "players": [
                    {"player_ref": f"webhook-ai-{index:02d}", "kind": "ai"}
                    for index in range(players)
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _post(self, client: TestClient, event_id: str, seconds: int = 600, occurred_at=None):
        payload = {"event_id": event_id, "seconds": seconds}
        if occurred_at is not None:
            payload["occurred_at"] = (
                occurred_at.isoformat()
                if isinstance(occurred_at, datetime)
                else occurred_at
            )
        return client.post("/v1/me/increments", headers=AUTH, json=payload)

    def _deliveries(self, webhooks_db: Path, event_type: str | None = None):
        with sqlite3.connect(webhooks_db) as connection:
            connection.row_factory = sqlite3.Row
            if event_type is None:
                rows = connection.execute(
                    "SELECT event_id, event_type, payload FROM webhook_deliveries "
                    "ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT event_id, event_type, payload FROM webhook_deliveries "
                    "WHERE event_type = ? ORDER BY id",
                    (event_type,),
                ).fetchall()
        return [dict(row) for row in rows]

    def test_19_all_event_types_are_accepted(self) -> None:
        app, _ = self._make_app()
        with TestClient(app) as client:
            response = client.post(
                "/v1/me/webhooks",
                headers=AUTH,
                json={
                    "url": "https://example.com/hook",
                    "events": list(ALLOWED_EVENTS),
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["events"], list(ALLOWED_EVENTS))
        self.assertIn("streak.milestone", ALLOWED_EVENTS)
        self.assertIn("streak.broken", ALLOWED_EVENTS)
        self.assertIn("rank.top3", ALLOWED_EVENTS)
        self.assertIn("rank.bottom3", ALLOWED_EVENTS)

    def test_20_streak_milestones_fire_once_each(self) -> None:
        app, webhooks_db = self._make_app()
        start = datetime(2026, 7, 1, 10, 0, tzinfo=TZ)
        with TestClient(app) as client:
            app.state.webhook_service.create_webhook(
                "owner",
                "https://example.com/hook",
                ["streak.milestone"],
            )
            for day_number in range(1, 101):
                self.clock["now"] = start + timedelta(days=day_number - 1)
                response = self._post(
                    client,
                    f"day-{day_number}",
                    seconds=600,
                    occurred_at=self.clock["now"],
                )
                self.assertEqual(response.status_code, 200, response.text)

            rows = self._deliveries(webhooks_db, "streak.milestone")
            self.assertEqual(len(rows), len(STREAK_MILESTONES))
            milestones = [
                json.loads(row["payload"])["data"]["milestone"] for row in rows
            ]
            self.assertEqual(milestones, list(STREAK_MILESTONES))
            expected_ids = [
                f"streak.milestone:owner:"
                f"{(start + timedelta(days=milestone - 1)).date().isoformat()}:"
                f"{milestone}"
                for milestone in STREAK_MILESTONES
            ]
            self.assertEqual([row["event_id"] for row in rows], expected_ids)
            # Re-enqueueing the same stable event id must stay idempotent.
            first = rows[0]
            created = app.state.webhook_service.enqueue_event(
                "owner",
                "streak.milestone",
                first["event_id"],
                {"date": "2026-07-03", "milestone": 3, "current_streak": 3},
                "2026-07-03T10:00:00+08:00",
            )
            self.assertEqual(created, 0)
            self.assertEqual(
                len(self._deliveries(webhooks_db, "streak.milestone")), 6
            )

    def test_21_streak_broken_has_previous_date_and_gap(self) -> None:
        app, webhooks_db = self._make_app()
        with TestClient(app) as client:
            app.state.webhook_service.create_webhook(
                "owner",
                "https://example.com/hook",
                ["streak.broken"],
            )
            self.clock["now"] = datetime(2026, 10, 20, 10, 0, tzinfo=TZ)
            first = self._post(
                client,
                "before-gap",
                seconds=600,
                occurred_at=self.clock["now"],
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(self._deliveries(webhooks_db, "streak.broken"), [])

            self.clock["now"] = datetime(2026, 10, 26, 10, 0, tzinfo=TZ)
            second = self._post(
                client,
                "after-gap",
                seconds=600,
                occurred_at=self.clock["now"],
            )
            self.assertEqual(second.status_code, 200)
            rows = self._deliveries(webhooks_db, "streak.broken")
            self.assertEqual(len(rows), 1)
            data = json.loads(rows[0]["payload"])["data"]
            self.assertEqual(data["previous_last_checkin_date"], "2026-10-20")
            self.assertEqual(data["gap_days"], 6)
            self.assertEqual(data["date"], "2026-10-26")
            self.assertEqual(
                rows[0]["event_id"],
                "streak.broken:owner:2026-10-26:2026-10-20",
            )

            duplicate = self._post(
                client,
                "after-gap",
                seconds=600,
                occurred_at=self.clock["now"],
            )
            self.assertTrue(duplicate.json()["duplicate"])
            self.assertEqual(len(self._deliveries(webhooks_db, "streak.broken")), 1)

    def test_22_rank_top3_fires_on_crossing_and_not_twice(self) -> None:
        app, webhooks_db = self._make_app()
        with TestClient(app) as client:
            self._seed_roster(client)
            app.state.webhook_service.create_webhook(
                "owner",
                "https://example.com/hook",
                ["rank.top3", "rank.bottom3"],
            )
            response = self._post(
                client, "jump-to-top", seconds=72_000, occurred_at=self.clock["now"]
            )
            self.assertEqual(response.status_code, 200, response.text)
            rows = self._deliveries(webhooks_db, "rank.top3")
            self.assertEqual(len(rows), 1)
            event = json.loads(rows[0]["payload"])
            self.assertGreater(event["data"]["previous_rank"], 3)
            self.assertEqual(event["data"]["rank"], 1)
            self.assertEqual(event["data"]["group_size"], 15)
            self.assertIn("rank.top3:owner:2026-10-26:", rows[0]["event_id"])
            self.assertEqual(self._deliveries(webhooks_db, "rank.bottom3"), [])

            duplicate = self._post(
                client,
                "jump-to-top",
                seconds=72_000,
                occurred_at=self.clock["now"],
            )
            self.assertTrue(duplicate.json()["duplicate"])
            self.assertEqual(len(self._deliveries(webhooks_db, "rank.top3")), 1)

            again = self._post(
                client, "stay-at-top", seconds=1, occurred_at=self.clock["now"]
            )
            self.assertEqual(again.status_code, 200)
            self.assertEqual(len(self._deliveries(webhooks_db, "rank.top3")), 1)

    def test_23_rank_bottom3_crossing_and_no_crossing(self) -> None:
        app, webhooks_db = self._make_app()

        def snapshot(rank: int) -> dict:
            return {
                "week_start": "2026-10-26",
                "rank": rank,
                "group_size": 15,
                "current_streak": 0,
                "last_checkin_date": None,
                "week_seconds": 0,
                "week_xp": 0,
            }

        with TestClient(app) as client:
            app.state.webhook_service.create_webhook(
                "owner",
                "https://example.com/hook",
                ["rank.bottom3"],
            )
            with patch.object(
                app.state.game_service,
                "hook_snapshot",
                side_effect=[snapshot(12), snapshot(13)],
            ):
                crossed = self._post(
                    client, "slip-to-bottom", seconds=1, occurred_at=self.clock["now"]
                )
            self.assertEqual(crossed.status_code, 200, crossed.text)
            rows = self._deliveries(webhooks_db, "rank.bottom3")
            self.assertEqual(len(rows), 1)
            data = json.loads(rows[0]["payload"])["data"]
            self.assertEqual(data["previous_rank"], 12)
            self.assertEqual(data["rank"], 13)
            self.assertEqual(data["group_size"], 15)

            with patch.object(
                app.state.game_service,
                "hook_snapshot",
                side_effect=[snapshot(12), snapshot(12)],
            ):
                same = self._post(
                    client, "stay-at-bottom", seconds=1, occurred_at=self.clock["now"]
                )
            self.assertEqual(same.status_code, 200, same.text)
            self.assertEqual(len(self._deliveries(webhooks_db, "rank.bottom3")), 1)

    def test_24_new_event_labels_stay_minimal(self) -> None:
        expected = {
            "streak.milestone": "连胜里程碑",
            "streak.broken": "连胜中断",
            "rank.top3": "进入小组前三",
            "rank.bottom3": "落入小组后三",
        }
        for event_type, label in expected.items():
            content = format_event_injector_content(
                {
                    "id": f"event-{event_type}",
                    "type": event_type,
                    "version": 1,
                    "occurred_at": "2026-10-27T09:27:31+08:00",
                    "data": {
                        "today_seconds": 12345,
                        "week_total_seconds": 54321,
                        "rank": 2,
                        "group_size": 15,
                        "current_streak": 99,
                    },
                }
            )
            self.assertIn(f"检测到系统事件：{label}（{event_type}）", content)
            self.assertIn("事件时间：2026-10-27T09:27:31+08:00", content)
            self.assertIn("请查询 Ghost League 当前状态", content)
            for detail in ("今日：", "本周：", "小组排名：", "当前连胜："):
                self.assertNotIn(detail, content)
            for value in ("12345", "54321", "第 2 名", "99 天"):
                self.assertNotIn(value, content)

    def test_25_checkin_event_stays_single(self) -> None:
        app, webhooks_db = self._make_app()
        with TestClient(app) as client:
            app.state.webhook_service.create_webhook(
                "owner",
                "https://example.com/hook",
                list(ALLOWED_EVENTS),
            )
            response = self._post(
                client, "first-checkin", seconds=600, occurred_at=self.clock["now"]
            )
            self.assertEqual(response.status_code, 200)
            checkins = self._deliveries(webhooks_db, "checkin.completed")
            self.assertEqual(len(checkins), 1)
            self.assertEqual(
                checkins[0]["event_id"], "checkin:owner:2026-10-26"
            )

            duplicate = self._post(
                client, "first-checkin", seconds=600, occurred_at=self.clock["now"]
            )
            self.assertTrue(duplicate.json()["duplicate"])
            self.assertEqual(
                len(self._deliveries(webhooks_db, "checkin.completed")), 1
            )


class EventInjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_14_event_injector_formats_content_and_headers(self) -> None:
        receiver = Receiver()
        self.addCleanup(receiver.close)
        service = WebhookService(self.base / "webhooks.db", now_fn=lambda: NOW)
        service.initialize()
        webhook = service.create_webhook(
            "sample-user",
            receiver.url,
            ["checkin.completed"],
            transport="event_injector",
            force=True,
        )
        service.enqueue_checkin(
            user_id="sample-user",
            date="2026-10-26",
            today_seconds=600,
            current_streak=2,
            week_start="2026-10-26",
            occurred_at=NOW.isoformat(),
            activity_label="骑行",
            week_total_seconds=1800,
            rank=3,
            group_size=15,
        )
        delivered = service.process_due()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["status"], "delivered")
        request = receiver.received[0]
        headers = request["headers"]
        self.assertEqual(headers["x-event-token"], webhook["secret"])
        self.assertEqual(headers["content-type"], "application/json")
        for absent in (
            "x-ghost-signature",
            "x-ghost-timestamp",
            "x-webhook-signature-v2",
            "x-webhook-timestamp",
        ):
            self.assertNotIn(absent, headers)
        body = json.loads(request["body"])
        self.assertEqual(set(body), {"content", "role"})
        self.assertEqual(body["role"], "user")
        content = body["content"]
        for expected in (
            "【Ghost League】检测到系统事件：打卡完成（checkin.completed）。",
            f"事件时间：{NOW.isoformat()}",
            "请查询 Ghost League 当前状态",
            "不要直接把本事件当作汇报",
        ):
            self.assertIn(expected, content)
        self.assertNotIn(webhook["secret"], content)
        self.assertNotIn("今日：", content)
        self.assertNotIn("本周：", content)
        state = service.get_webhook("sample-user", webhook["id"])
        self.assertEqual(state["last_status"], "delivered")
        self.assertEqual(state["failure_count"], 0)
        self.assertEqual(state["transport"], "event_injector")

    def test_15_missing_fields_are_not_fabricated(self) -> None:
        content = format_event_injector_content(
            {
                "id": "evt",
                "type": "webhook.test",
                "version": 1,
                "occurred_at": "2026-10-26T18:36:00+08:00",
                "data": {"activity_label": "阅读"},
            }
        )
        self.assertIn(
            "【Ghost League】检测到系统事件：测试事件（webhook.test）。",
            content,
        )
        self.assertIn("事件时间：2026-10-26T18:36:00+08:00", content)
        self.assertIn("请查询 Ghost League 当前状态", content)
        self.assertNotIn("日期：", content)
        self.assertNotIn("今日：", content)
        self.assertNotIn("本周：", content)
        self.assertNotIn("小组排名：", content)
        self.assertNotIn("当前连胜：", content)

    def test_16_event_injector_failure_retries_then_succeeds(self) -> None:
        receiver = Receiver(status_code=500)
        self.addCleanup(receiver.close)
        clock = {"now": NOW}
        service = WebhookService(
            self.base / "webhooks.db", now_fn=lambda: clock["now"], timeout=2
        )
        service.initialize()
        webhook = service.create_webhook(
            "owner",
            receiver.url,
            ["webhook.test"],
            transport="event_injector",
            force=True,
        )
        service.enqueue_test(
            user_id="owner",
            webhook_id=webhook["id"],
            date="2026-10-26",
            today_seconds=0,
            current_streak=0,
            week_start="2026-10-26",
            occurred_at=NOW.isoformat(),
            activity_label="练习",
        )
        first = service.process_due()
        self.assertEqual(first[0]["status"], "pending")
        self.assertEqual(first[0]["attempts"], 1)
        self.assertIn("HTTP 500", first[0]["last_error"])
        state = service.get_webhook("owner", webhook["id"])
        self.assertEqual(state["last_status"], "retrying")
        self.assertNotIn(webhook["secret"], json.dumps(state))

        receiver.status_code = 200
        clock["now"] = NOW.replace(minute=37)
        second = service.process_due()
        self.assertEqual(second[0]["status"], "delivered")
        self.assertEqual(second[0]["attempts"], 2)
        state = service.get_webhook("owner", webhook["id"])
        self.assertEqual(state["last_status"], "delivered")
        self.assertEqual(state["failure_count"], 0)
        self.assertEqual(len(receiver.received), 2)
        for request in receiver.received:
            self.assertEqual(request["headers"]["x-event-token"], webhook["secret"])
            self.assertNotIn("x-ghost-signature", request["headers"])

    def test_17_old_webhooks_table_migrates_to_generic(self) -> None:
        db = self.base / "webhooks.db"
        with sqlite3.connect(db) as connection:
            connection.execute(
                "CREATE TABLE webhooks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, "
                "url TEXT NOT NULL, secret TEXT NOT NULL, events TEXT NOT NULL, "
                "active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, last_status TEXT, last_attempt_at TEXT, "
                "last_success_at TEXT, failure_count INTEGER NOT NULL DEFAULT 0)"
            )
            connection.execute(
                "INSERT INTO webhooks "
                "(user_id,url,secret,events,active,created_at,updated_at) "
                "VALUES (?,?,?,?,1,?,?)",
                (
                    "owner",
                    "https://example.com/hook",
                    "whsec_old",
                    json.dumps(["checkin.completed"]),
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            )
        service = WebhookService(db, now_fn=lambda: NOW)
        service.initialize()
        migrated = service.get_webhook("owner", 1)
        self.assertEqual(migrated["transport"], "generic")
        with sqlite3.connect(db) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(webhooks)")
            }
        self.assertIn("transport", columns)


class WebhookCLITests(unittest.TestCase):
    def test_11_cli_force_set_list_rotate_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "webhooks.db"
            env = os.environ.copy()
            env["GHOST_LEAGUE_WEBHOOKS_DB"] = str(db)

            def run(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-m", "ghost_league.webhooks", *args],
                    cwd=Path(__file__).resolve().parents[1],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            rejected = run(
                "set",
                "--user-id",
                "owner",
                "--url",
                "http://198.51.100.10:8099/events",
                "--events",
                "checkin.completed",
            )
            self.assertNotEqual(rejected.returncode, 0)

            created = run(
                "set",
                "--user-id",
                "owner",
                "--url",
                "http://198.51.100.10:8099/events",
                "--events",
                "checkin.completed",
                "--force",
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            secret_match = re.search(r"^secret=(.+)$", created.stdout, re.MULTILINE)
            self.assertIsNotNone(secret_match)
            secret = secret_match.group(1).strip()
            self.assertTrue(secret.startswith("whsec_"))
            self.assertEqual(created.stdout.count("secret="), 1)

            listed = run("list", "--user-id", "owner")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("http://198.51.100.10:8099/events", listed.stdout)
            self.assertIn("checkin.completed", listed.stdout)
            self.assertIn("generic", listed.stdout)
            self.assertNotIn(secret, listed.stdout)

            event_injector = run(
                "set",
                "--user-id",
                "owner",
                "--url",
                "http://127.0.0.1:19000/inject",
                "--events",
                "webhook.test",
                "--transport",
                "event_injector",
                "--force",
            )
            self.assertEqual(event_injector.returncode, 0, event_injector.stderr)
            self.assertIn("transport=event_injector", event_injector.stdout)
            listed_again = run("list", "--user-id", "owner")
            self.assertIn("event_injector", listed_again.stdout)
            second_secret = re.search(
                r"^secret=(.+)$", event_injector.stdout, re.MULTILINE
            ).group(1)
            self.assertNotIn(second_secret, listed_again.stdout)

            webhook_id = re.search(r"^id=(\d+)$", created.stdout, re.MULTILINE).group(1)
            rotated = run(
                "rotate-secret",
                "--user-id",
                "owner",
                "--webhook-id",
                webhook_id,
            )
            self.assertEqual(rotated.returncode, 0, rotated.stderr)
            new_secret = re.search(r"^secret=(.+)$", rotated.stdout, re.MULTILINE).group(1)
            self.assertNotEqual(new_secret, secret)
            self.assertEqual(rotated.stdout.count("secret="), 1)
            self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
