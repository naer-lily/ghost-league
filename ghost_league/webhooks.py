"""Webhook subscriptions, signed outbox deliveries, and local CLI.

This first version intentionally validates only the URL shape (https + a
non-literal-IP, non-localhost hostname).  It does not resolve DNS, enforce
private ranges, or implement allowlists.  The CLI ``--force`` path can write an
HTTP/IP target directly for trusted local deployments.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence

from .schedule import TZ

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_DIR = PROJECT_ROOT / "data" / "api"
DEFAULT_WEBHOOKS_DB = DEFAULT_API_DIR / "webhooks.db"
ALLOWED_EVENTS = (
    "checkin.completed",
    "webhook.test",
    "streak.milestone",
    "streak.broken",
    "rank.top3",
    "rank.bottom3",
)
STREAK_MILESTONES = (3, 7, 14, 30, 60, 100)
ALLOWED_TRANSPORTS = ("generic", "event_injector")
RETRY_DELAYS = (60, 300, 1800)  # after failed attempts 1, 2, 3
MAX_ATTEMPTS = 1 + len(RETRY_DELAYS)  # initial attempt + up to 3 retries
USER_AGENT = "ghost-league-webhook/1.0"


def _iso(value: datetime) -> str:
    return value.astimezone(TZ).isoformat(timespec="seconds")


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def validate_webhook_url(url: str, *, force: bool = False) -> str:
    """Validate a webhook URL without DNS, CIDR, or allowlist checks.

    Normal API/CLI calls require HTTPS and a dot-containing domain hostname.
    ``force=True`` is the local CLI escape hatch and allows HTTP/IP targets.
    """

    if not isinstance(url, str) or not url.strip():
        raise ValueError("webhook url must be a non-empty string")
    value = url.strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("webhook url must use http or https")
    if not force and parsed.scheme != "https":
        raise ValueError("webhook url must use https")
    host = parsed.hostname
    if not host:
        raise ValueError("webhook url must include a hostname")
    host_clean = host.rstrip(".").lower()
    if not force:
        if host_clean == "localhost":
            raise ValueError("webhook url hostname cannot be localhost")
        try:
            ipaddress.ip_address(host_clean)
        except ValueError:
            pass
        else:
            raise ValueError("webhook url hostname cannot be an IP literal")
        if "." not in host_clean:
            raise ValueError("webhook url hostname must be a domain name")
    return value


def normalize_events(events: list[str] | tuple[str, ...]) -> list[str]:
    if not isinstance(events, (list, tuple)) or not events:
        raise ValueError("events must be a non-empty list")
    normalized: list[str] = []
    for event in events:
        if not isinstance(event, str) or event not in ALLOWED_EVENTS:
            raise ValueError(f"unsupported webhook event: {event!r}")
        if event not in normalized:
            normalized.append(event)
    return normalized


def generate_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign_payload(secret: str, timestamp: str | int, raw_body: str | bytes) -> str:
    message = f"{timestamp}.".encode("utf-8")
    if isinstance(raw_body, str):
        message += raw_body.encode("utf-8")
    else:
        message += raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def sign_payload_hex(secret: str, timestamp: str | int, raw_body: str | bytes) -> str:
    """Hex HMAC for the compatible ``X-Webhook-Signature-V2`` header."""

    return sign_payload(secret, timestamp, raw_body).split("=", 1)[1]


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_events(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def format_event_injector_content(payload: dict[str, Any]) -> str:
    """Build a minimal event notice for event-injector.

    The notice only says that something changed. The assistant receiving it
    must query the live Ghost League API for the actual state and decide
    whether the change is worth telling the user about. Do not put the full
    event payload (or a pre-rendered report) here.
    """

    event_type = payload.get("type")
    event_type = (
        event_type if isinstance(event_type, str) and event_type.strip() else "unknown"
    )
    event_label = {
        "checkin.completed": "打卡完成",
        "streak.milestone": "连胜里程碑",
        "streak.broken": "连胜中断",
        "rank.top3": "进入小组前三",
        "rank.bottom3": "落入小组后三",
        "webhook.test": "测试事件",
    }.get(event_type, event_type)
    occurred_at = payload.get("occurred_at")
    occurred_at = (
        occurred_at if isinstance(occurred_at, str) and occurred_at.strip() else "—"
    )
    return "\n".join(
        [
            f"【Ghost League】检测到系统事件：{event_label}（{event_type}）。",
            f"事件时间：{occurred_at}。",
            "这里只有变化提示，不是完整数据。请查询 Ghost League 当前状态，"
            "判断这个变化是否值得告诉主人；不要直接把本事件当作汇报。",
        ]
    )


class WebhookService:
    """SQLite-backed webhook configuration, outbox, and delivery worker."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_WEBHOOKS_DB,
        *,
        now_fn: Callable[[], datetime] | None = None,
        timeout: float = 5.0,
        poll_interval: float = 2.0,
    ) -> None:
        self.db_path = Path(db_path)
        self._now_fn = now_fn or (lambda: datetime.now(TZ))
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()

    def now(self) -> datetime:
        return _local(self._now_fn())

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    secret TEXT NOT NULL,
                    events TEXT NOT NULL,
                    transport TEXT NOT NULL DEFAULT 'generic',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_status TEXT,
                    last_attempt_at TEXT,
                    last_success_at TEXT,
                    failure_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    next_attempt_at TEXT,
                    UNIQUE (webhook_id, event_id)
                )
                """
            )
            webhook_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(webhooks)").fetchall()
            }
            if "transport" not in webhook_columns:
                connection.execute(
                    "ALTER TABLE webhooks ADD COLUMN transport TEXT NOT NULL DEFAULT 'generic'"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_webhooks_user ON webhooks (user_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_deliveries_pending "
                "ON webhook_deliveries (status, next_attempt_at)"
            )
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    # -- configuration -------------------------------------------------
    def _latest_delivery(self, connection: sqlite3.Connection, webhook_id: int) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT id, event_id, event_type, status, attempts, last_error, "
            "created_at, delivered_at FROM webhook_deliveries "
            "WHERE webhook_id = ? ORDER BY id DESC LIMIT 1",
            (webhook_id,),
        ).fetchone()
        return dict(row) if row else None

    def _public_webhook(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        include_secret: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "id": int(row["id"]),
            "user_id": row["user_id"],
            "url": row["url"],
            "events": _parse_events(row["events"]),
            "transport": row["transport"],
            "active": bool(row["active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_status": row["last_status"],
            "last_attempt_at": row["last_attempt_at"],
            "last_success_at": row["last_success_at"],
            "failure_count": int(row["failure_count"]),
            "latest_delivery": self._latest_delivery(connection, int(row["id"])),
        }
        if include_secret:
            payload["secret"] = row["secret"]
        return payload

    def create_webhook(
        self,
        user_id: str,
        url: str,
        events: list[str] | tuple[str, ...],
        *,
        transport: str = "generic",
        force: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be a non-empty string")
        if transport not in ALLOWED_TRANSPORTS:
            raise ValueError(f"unsupported webhook transport: {transport!r}")
        clean_url = validate_webhook_url(url, force=force)
        clean_events = normalize_events(events)
        now = _iso(self.now())
        secret = generate_secret()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO webhooks "
                "(user_id, url, secret, events, transport, active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    user_id,
                    clean_url,
                    secret,
                    json.dumps(clean_events, ensure_ascii=False),
                    transport,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM webhooks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            payload = self._public_webhook(connection, row, include_secret=True)
        return payload

    def list_webhooks(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM webhooks WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [self._public_webhook(connection, row) for row in rows]

    def get_webhook(self, user_id: str, webhook_id: int, *, include_secret: bool = False) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM webhooks WHERE id = ? AND user_id = ?",
                (webhook_id, user_id),
            ).fetchone()
            if row is None:
                return None
            return self._public_webhook(connection, row, include_secret=include_secret)

    def update_webhook(
        self,
        user_id: str,
        webhook_id: int,
        *,
        url: str | None = None,
        events: list[str] | tuple[str, ...] | None = None,
        transport: str | None = None,
        active: bool | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_webhook(user_id, webhook_id)
        if current is None:
            return None
        clean_url = validate_webhook_url(url) if url is not None else None
        clean_events = normalize_events(events) if events is not None else None
        if transport is not None and transport not in ALLOWED_TRANSPORTS:
            raise ValueError(f"unsupported webhook transport: {transport!r}")
        updated_at = _iso(self.now())
        with self._connect() as connection:
            connection.execute(
                "UPDATE webhooks SET "
                "url = COALESCE(?, url), events = COALESCE(?, events), "
                "transport = COALESCE(?, transport), active = COALESCE(?, active), "
                "updated_at = ? WHERE id = ? AND user_id = ?",
                (
                    clean_url,
                    json.dumps(clean_events, ensure_ascii=False) if clean_events is not None else None,
                    transport,
                    None if active is None else int(bool(active)),
                    updated_at,
                    webhook_id,
                    user_id,
                ),
            )
        return self.get_webhook(user_id, webhook_id)

    def delete_webhook(self, user_id: str, webhook_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM webhooks WHERE id = ? AND user_id = ?",
                (webhook_id, user_id),
            )
            return cursor.rowcount == 1

    def rotate_secret(self, user_id: str, webhook_id: int) -> str | None:
        secret = generate_secret()
        now = _iso(self.now())
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE webhooks SET secret = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (secret, now, webhook_id, user_id),
            )
            if cursor.rowcount != 1:
                return None
        return secret

    # -- outbox --------------------------------------------------------
    def _insert_delivery(
        self,
        connection: sqlite3.Connection,
        *,
        webhook_id: int,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        raw = _canonical_json(payload)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO webhook_deliveries "
            "(webhook_id, event_id, event_type, payload, status, attempts, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', 0, ?)",
            (webhook_id, event_id, event_type, raw, _iso(self.now())),
        )
        return cursor.rowcount == 1

    def enqueue_event(
        self,
        user_id: str,
        event_type: str,
        event_id: str,
        payload: dict[str, Any],
        occurred_at: str,
    ) -> int:
        """Queue one event for every active webhook subscribed to it.

        ``payload`` contains the event's ``data`` fields only.  The method
        builds the stable v1 envelope around it, so callers share one SQL and
        idempotency path instead of duplicating outbox inserts.
        """

        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be a non-empty string")
        if event_type not in ALLOWED_EVENTS:
            raise ValueError(f"unsupported webhook event: {event_type!r}")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        event = {
            "id": event_id,
            "type": event_type,
            "version": 1,
            "occurred_at": occurred_at,
            "data": dict(payload),
        }
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, events FROM webhooks WHERE user_id = ? AND active = 1",
                (user_id,),
            ).fetchall()
            created = 0
            for row in rows:
                if event_type not in _parse_events(row["events"]):
                    continue
                if self._insert_delivery(
                    connection,
                    webhook_id=int(row["id"]),
                    event_id=event_id,
                    event_type=event_type,
                    payload=event,
                ):
                    created += 1
        return created

    def enqueue_checkin(
        self,
        *,
        user_id: str,
        date: str,
        today_seconds: int,
        current_streak: int,
        week_start: str,
        occurred_at: str,
        activity_label: str = "练习",
        week_total_seconds: int | None = None,
        rank: int | None = None,
        group_size: int | None = None,
    ) -> int:
        event_id = f"checkin:{user_id}:{date}"
        data = {
            "date": date,
            "today_seconds": int(today_seconds),
            "current_streak": int(current_streak),
            "week_start": week_start,
            "activity_label": activity_label,
        }
        if week_total_seconds is not None:
            data["week_total_seconds"] = int(week_total_seconds)
        if rank is not None:
            data["rank"] = int(rank)
        if group_size is not None:
            data["group_size"] = int(group_size)
        return self.enqueue_event(
            user_id,
            "checkin.completed",
            event_id,
            data,
            occurred_at,
        )

    def enqueue_test(
        self,
        *,
        user_id: str,
        webhook_id: int,
        date: str,
        today_seconds: int,
        current_streak: int,
        week_start: str,
        occurred_at: str,
        activity_label: str = "练习",
        week_total_seconds: int | None = None,
        rank: int | None = None,
        group_size: int | None = None,
    ) -> int | None:
        with self._connect() as connection:
            webhook = connection.execute(
                "SELECT id FROM webhooks WHERE id = ? AND user_id = ?",
                (webhook_id, user_id),
            ).fetchone()
            if webhook is None:
                return None
            event_id = f"test:{uuid.uuid4().hex}"
            payload = {
                "id": event_id,
                "type": "webhook.test",
                "version": 1,
                "occurred_at": occurred_at,
                "data": {
                    "date": date,
                    "today_seconds": int(today_seconds),
                    "current_streak": int(current_streak),
                    "week_start": week_start,
                    "activity_label": activity_label,
                },
            }
            if week_total_seconds is not None:
                payload["data"]["week_total_seconds"] = int(week_total_seconds)
            if rank is not None:
                payload["data"]["rank"] = int(rank)
            if group_size is not None:
                payload["data"]["group_size"] = int(group_size)
            self._insert_delivery(
                connection,
                webhook_id=webhook_id,
                event_id=event_id,
                event_type="webhook.test",
                payload=payload,
            )
            row = connection.execute(
                "SELECT id FROM webhook_deliveries WHERE webhook_id = ? AND event_id = ?",
                (webhook_id, event_id),
            ).fetchone()
            return int(row["id"]) if row else None

    # -- delivery ------------------------------------------------------
    def _delivery_result(self, delivery_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, webhook_id, event_id, event_type, status, attempts, "
                "last_error, created_at, delivered_at, next_attempt_at "
                "FROM webhook_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()
        return dict(row) if row else None

    def _attempt(self, delivery_id: int, *, force: bool = False) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT d.*, w.url, w.secret, w.active, w.transport "
                "FROM webhook_deliveries d "
                "JOIN webhooks w ON w.id = d.webhook_id "
                "WHERE d.id = ?",
                (delivery_id,),
            ).fetchone()
        if row is None or (row["status"] != "pending" and not force):
            return None
        if not row["active"] and not force:
            return None

        body = str(row["payload"])
        if row["transport"] == "event_injector":
            try:
                event_payload = json.loads(body)
            except ValueError:
                event_payload = {}
            if not isinstance(event_payload, dict):
                event_payload = {}
            body = json.dumps(
                {
                    "content": format_event_injector_content(event_payload),
                    "role": "user",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            headers = {
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-Event-Token": str(row["secret"]),
            }
        else:
            timestamp = str(int(self.now().timestamp()))
            headers = {
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-Ghost-Event-Id": str(row["event_id"]),
                "X-Ghost-Timestamp": timestamp,
                "X-Ghost-Signature": sign_payload(row["secret"], timestamp, body),
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature-V2": sign_payload_hex(
                    row["secret"], timestamp, body
                ),
            }
        success = False
        status_code: int | None = None
        error_text: str | None = None
        try:
            request = urllib.request.Request(
                row["url"],
                data=body.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status_code = int(response.status)
                response.read(4096)
                success = 200 <= status_code < 300
                if not success:
                    error_text = f"HTTP {status_code}"
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            error_text = f"HTTP {status_code}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            error_text = f"{type(exc).__name__}: {exc}"[:400]

        now = self.now()
        now_iso = _iso(now)
        attempts = int(row["attempts"]) + 1
        with self._connect() as connection:
            if success:
                connection.execute(
                    "UPDATE webhook_deliveries SET status = 'delivered', attempts = ?, "
                    "last_error = NULL, delivered_at = ?, next_attempt_at = NULL "
                    "WHERE id = ?",
                    (attempts, now_iso, delivery_id),
                )
                connection.execute(
                    "UPDATE webhooks SET last_status = 'delivered', last_attempt_at = ?, "
                    "last_success_at = ?, failure_count = 0 WHERE id = ?",
                    (now_iso, now_iso, row["webhook_id"]),
                )
            else:
                final = attempts >= MAX_ATTEMPTS
                next_attempt = None
                if final:
                    delivery_status = "failed"
                    webhook_status = "failed"
                else:
                    delivery_status = "pending"
                    webhook_status = "retrying"
                    next_attempt = _iso(now + timedelta(seconds=RETRY_DELAYS[attempts - 1]))
                connection.execute(
                    "UPDATE webhook_deliveries SET status = ?, attempts = ?, "
                    "last_error = ?, next_attempt_at = ? WHERE id = ?",
                    (delivery_status, attempts, error_text, next_attempt, delivery_id),
                )
                connection.execute(
                    "UPDATE webhooks SET last_status = ?, last_attempt_at = ?, "
                    "failure_count = failure_count + 1 WHERE id = ?",
                    (webhook_status, now_iso, row["webhook_id"]),
                )
        return self._delivery_result(delivery_id)

    def deliver_now(self, delivery_id: int) -> dict[str, Any] | None:
        return self._attempt(delivery_id, force=True)

    def process_due(self, limit: int = 20) -> list[dict[str, Any]]:
        now = _iso(self.now())
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT d.id FROM webhook_deliveries d "
                "JOIN webhooks w ON w.id = d.webhook_id "
                "WHERE d.status = 'pending' AND w.active = 1 "
                "AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?) "
                "ORDER BY d.id LIMIT ?",
                (now, limit),
            ).fetchall()
        results = []
        for row in rows:
            result = self._attempt(int(row["id"]))
            if result is not None:
                results.append(result)
        return results

    # -- background worker --------------------------------------------
    def start_worker(self) -> None:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="ghost-league-webhook-worker",
                daemon=True,
            )
            self._worker.start()

    def stop_worker(self) -> None:
        with self._worker_lock:
            worker = self._worker
            self._worker = None
            self._stop.set()
        if worker is not None:
            worker.join(timeout=5)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_due()
            except Exception:
                # Never log payloads or secrets here.
                pass
            self._stop.wait(self.poll_interval)


def _parse_event_args(values: list[str] | None) -> list[str]:
    events: list[str] = []
    for value in values or []:
        for part in value.split(","):
            part = part.strip()
            if part and part not in events:
                events.append(part)
    return events


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ghost_league.webhooks",
        description="Local webhook subscription management.",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("GHOST_LEAGUE_WEBHOOKS_DB", str(DEFAULT_WEBHOOKS_DB)),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    set_cmd = sub.add_parser("set", help="create a webhook")
    set_cmd.add_argument("--user-id", required=True)
    set_cmd.add_argument("--url", required=True)
    set_cmd.add_argument("--events", action="append", required=True)
    set_cmd.add_argument(
        "--transport",
        choices=ALLOWED_TRANSPORTS,
        default="generic",
    )
    set_cmd.add_argument("--force", action="store_true")

    list_cmd = sub.add_parser("list", help="list a user's webhooks")
    list_cmd.add_argument("--user-id", required=True)

    rotate = sub.add_parser("rotate-secret", help="rotate a webhook secret")
    rotate.add_argument("--user-id", required=True)
    rotate.add_argument("--webhook-id", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _cli_parser().parse_args(argv)
    service = WebhookService(args.db)
    try:
        service.initialize()
        if args.command == "set":
            events = _parse_event_args(args.events)
            webhook = service.create_webhook(
                args.user_id,
                args.url,
                events,
                transport=args.transport,
                force=args.force,
            )
            print(f"id={webhook['id']}")
            print(f"url={webhook['url']}")
            print(f"events={','.join(webhook['events'])}")
            print(f"transport={webhook['transport']}")
            print(f"secret={webhook['secret']}")
        elif args.command == "list":
            webhooks = service.list_webhooks(args.user_id)
            print("id\turl\tevents\ttransport\tactive\tlast_status\tlast_attempt_at\tfailure_count")
            for webhook in webhooks:
                print(
                    f"{webhook['id']}\t{webhook['url']}\t"
                    f"{','.join(webhook['events'])}\t"
                    f"{webhook['transport']}\t"
                    f"{str(webhook['active']).lower()}\t"
                    f"{webhook['last_status'] or '-'}\t"
                    f"{webhook['last_attempt_at'] or '-'}\t"
                    f"{webhook['failure_count']}"
                )
        elif args.command == "rotate-secret":
            secret = service.rotate_secret(args.user_id, args.webhook_id)
            if secret is None:
                raise ValueError("webhook not found")
            print(f"secret={secret}")
        else:  # pragma: no cover
            raise ValueError(f"unknown command: {args.command}")
    except (OSError, ValueError) as exc:
        print(f"webhooks: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ALLOWED_EVENTS",
    "DEFAULT_WEBHOOKS_DB",
    "STREAK_MILESTONES",
    "MAX_ATTEMPTS",
    "RETRY_DELAYS",
    "WebhookService",
    "generate_secret",
    "normalize_events",
    "format_event_injector_content",
    "sign_payload",
    "sign_payload_hex",
    "validate_webhook_url",
]
