"""Tests for the stdlib-only account-backed AI channel."""

from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ai_channel.cli import (
    DEFAULT_SERVE_PREFIX,
    build_parser,
    list_accounts,
    next_user_ids,
    provision_accounts,
    serve,
    tick,
)
from ai_channel.client import AIClient, AIChannelHTTPError
from ai_channel.config import load_config
from ai_channel.policy import star_request_id, xp_event_id
from ai_channel.store import StateStore

AT = datetime(2026, 11, 5, 12, 34, 0, tzinfo=timezone.utc)


class FakeClient:
    """Stands in for Ghost; records every call without touching the network."""

    def __init__(
        self,
        *,
        shop: list[dict[str, Any]] | None = None,
        diamonds: dict[str, int] | None = None,
        increment_error: Exception | None = None,
    ) -> None:
        self.shop = shop if shop is not None else []
        self.diamonds = diamonds or {}
        self.increment_error = increment_error
        self.provision_calls: list[tuple[str, str]] = []
        self.increment_calls: list[tuple[str, str, int, str]] = []
        self.status_calls: list[str] = []
        self.shop_calls: list[str] = []
        self.purchase_calls: list[tuple[str, str, str]] = []

    def provision_account(
        self,
        user_id: str,
        display_name: str,
        *,
        activity_label: str | None = None,
    ) -> dict[str, Any]:
        self.provision_calls.append((user_id, display_name))
        return {
            "account": {"user_id": user_id, "display_name": display_name},
            "token": f"token-{user_id}",
        }

    def send_increment(
        self, token: str, event_id: str, seconds: int, occurred_at: str
    ) -> dict[str, Any]:
        self.increment_calls.append((token, event_id, seconds, occurred_at))
        if self.increment_error is not None:
            raise self.increment_error
        return {"duplicate": False, "week_xp": 150, "accepted": True}

    def get_status(self, token: str) -> dict[str, Any]:
        self.status_calls.append(token)
        return {"diamonds": int(self.diamonds.get(token, 0))}

    def get_shop(self, token: str) -> list[dict[str, Any]]:
        self.shop_calls.append(token)
        return list(self.shop)

    def purchase(self, token: str, item_id: str, request_id: str) -> dict[str, Any]:
        self.purchase_calls.append((token, item_id, request_id))
        return {"ok": True, "item_id": item_id, "diamonds": 0}


def _store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "state" / "ai_accounts.db")
    store.initialize()
    return store


def _seed(store: StateStore, user_id: str, token: str) -> None:
    store.save_account(user_id, f"Sim {user_id}", token)


def _config_file(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_provision_stores_token_but_list_never_prints_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = FakeClient()
    provisioned_lines: list[str] = []
    provisioned = provision_accounts(
        client, store, count=2, prefix="sim-", out=provisioned_lines.append
    )
    assert provisioned == ["sim-0001", "sim-0002"]
    assert client.provision_calls == [
        ("sim-0001", "Sim 0001"),
        ("sim-0002", "Sim 0002"),
    ]
    stored = store.list_accounts(include_tokens=True)
    assert [row["token"] for row in stored] == ["token-sim-0001", "token-sim-0002"]
    assert "token-sim-0001" not in "\n".join(provisioned_lines)
    assert "token-sim-0002" not in "\n".join(provisioned_lines)

    listed_lines: list[str] = []
    list_accounts(store, out=listed_lines.append)
    output = "\n".join(listed_lines)
    assert "sim-0001" in output
    assert "Sim 0001" in output
    assert "token-sim-0001" not in output
    assert "token-sim-0002" not in output

    mode = stat.S_IMODE(store.db_path.stat().st_mode)
    assert mode == 0o600


def test_tick_sends_one_increment_per_account_with_bearer_token(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed(store, "sim-0001", "account-token-one")
    _seed(store, "sim-0002", "account-token-two")
    client = FakeClient()
    summary = tick(client, store, seconds=900, at=AT, out=lambda _line: None)
    assert summary["increments"] == 2
    assert summary["errors"] == 0
    assert [call[0] for call in client.increment_calls] == [
        "account-token-one",
        "account-token-two",
    ]
    assert all(call[2] == 900 for call in client.increment_calls)
    assert all("T12" in call[1] for call in client.increment_calls)


def test_same_hour_ticks_use_the_same_event_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed(store, "sim-0001", "token-one")
    client = FakeClient()
    tick(client, store, seconds=900, at=AT, out=lambda _line: None)
    tick(client, store, seconds=900, at=AT, out=lambda _line: None)
    event_ids = [call[1] for call in client.increment_calls]
    assert event_ids[0] == event_ids[1] == xp_event_id("sim-0001", AT)


def test_affordable_star_is_purchased_and_unaffordable_is_not(tmp_path: Path) -> None:
    shop = [
        {"id": "expensive-star", "kind": "star", "price_diamonds": 80, "available": True},
        {"id": "cheap-star", "kind": "star", "price_diamonds": 40, "available": True},
        {"id": "seasonal", "kind": "seasonal_star", "price_diamonds": 50, "available": True},
        {"id": "not-a-star", "kind": "ember", "price_diamonds": 1, "available": True},
    ]
    rich_store = _store(tmp_path / "rich")
    _seed(rich_store, "sim-0001", "rich-token")
    rich_client = FakeClient(shop=shop, diamonds={"rich-token": 40})
    rich_summary = tick(
        rich_client,
        rich_store,
        seconds=900,
        buy_stars=True,
        at=AT,
        out=lambda _line: None,
    )
    assert rich_summary["purchases"] == 1
    assert rich_client.purchase_calls == [
        ("rich-token", "cheap-star", star_request_id("sim-0001", "cheap-star", AT))
    ]

    poor_store = _store(tmp_path / "poor")
    _seed(poor_store, "sim-0002", "poor-token")
    poor_client = FakeClient(shop=shop, diamonds={"poor-token": 10})
    poor_summary = tick(
        poor_client,
        poor_store,
        seconds=900,
        buy_stars=True,
        at=AT,
        out=lambda _line: None,
    )
    assert poor_summary["purchases"] == 0
    assert poor_client.purchase_calls == []


def test_config_validation_and_env_overrides(tmp_path: Path) -> None:
    valid = {
        "base_url": "http://127.0.0.1:8095/",
        "provisioning_token": "secret-token",
        "state_db": str(tmp_path / "state.db"),
        "request_timeout_seconds": 5,
        "default_seconds": 900,
    }
    config = load_config(_config_file(tmp_path, valid), env={})
    assert config.base_url == "http://127.0.0.1:8095"
    assert config.state_db == tmp_path / "state.db"

    override = load_config(
        _config_file(tmp_path, valid),
        env={
            "AI_CHANNEL_BASE_URL": "https://ghost.example.test",
            "AI_CHANNEL_PROVISIONING_TOKEN": "env-token",
        },
    )
    assert override.base_url == "https://ghost.example.test"
    assert override.provisioning_token == "env-token"

    for bad in (
        {**valid, "base_url": "not-a-url"},
        {**valid, "base_url": "ftp://127.0.0.1"},
        {**valid, "request_timeout_seconds": 0},
        {**valid, "default_seconds": 0},
        {**valid, "provisioning_token": ""},
    ):
        with pytest.raises(ValueError):
            load_config(_config_file(tmp_path, bad), env={})


def test_http_error_is_reported_not_raised(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed(store, "sim-0001", "token-one")
    client = FakeClient(
        increment_error=AIChannelHTTPError(500, "http://ghost/v1/me/increments", "boom")
    )
    lines: list[str] = []
    summary = tick(client, store, seconds=900, at=AT, out=lines.append)
    assert summary["errors"] == 1
    assert summary["increments"] == 0
    assert "error" in "\n".join(lines)
    assert "token-one" not in "\n".join(lines)


def test_client_uses_bearer_tokens_and_public_paths() -> None:
    calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, Any]]:
        calls.append((method, url, headers, body))
        if url.endswith("/v1/provisioning/accounts"):
            return 201, {"account": {"user_id": "sim-0001"}, "token": "new-token"}
        return 200, {"ok": True}

    client = AIClient(
        "http://ghost.test",
        provisioning_token="provision-token",
        transport=transport,
    )
    client.provision_account("sim-0001", "Sim One")
    client.send_increment("account-token", "event-1", 900, AT)
    assert calls[0][1] == "http://ghost.test/v1/provisioning/accounts"
    assert calls[0][2]["Authorization"] == "Bearer provision-token"
    assert calls[1][1] == "http://ghost.test/v1/me/increments"
    assert calls[1][2]["Authorization"] == "Bearer account-token"


def test_next_user_ids_continues_existing_sequence() -> None:
    assert next_user_ids(["sim-0003", "other"], prefix="sim-", count=2) == [
        "sim-0004",
        "sim-0005",
    ]


def test_store_prefix_filter_is_exact_and_escapes_like_wildcards(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed(store, "sim-0001", "token-sim-one")
    _seed(store, "sim-0002", "token-sim-two")
    _seed(store, "sim_0001", "token-underscore")
    _seed(store, "ch-waka-0001", "token-waka")

    assert [row["user_id"] for row in store.list_accounts("sim-")] == [
        "sim-0001",
        "sim-0002",
    ]
    assert [row["user_id"] for row in store.list_accounts("sim_")] == [
        "sim_0001"
    ]
    assert [row["user_id"] for row in store.list_accounts("ch-")] == [
        "ch-waka-0001"
    ]
    assert len(store.list_accounts()) == 4
    assert [row["user_id"] for row in store.list_accounts("sim-", include_tokens=True)] == [
        "sim-0001",
        "sim-0002",
    ]


def test_parser_accepts_serve_and_prefix_filters() -> None:
    parser = build_parser()
    args = parser.parse_args(["serve", "--config", "config.json"])
    assert args.command == "serve"
    assert args.config == "config.json"
    assert args.interval == 3600
    assert args.seconds is None
    assert args.buy_stars is False
    assert args.prefix == DEFAULT_SERVE_PREFIX == "sim-"
    assert args.cycles == 0
    assert args.at is None

    tick_args = parser.parse_args(["tick", "--prefix", "sim-"])
    assert tick_args.command == "tick"
    assert tick_args.prefix == "sim-"
    assert parser.parse_args(["tick"]).prefix is None

    list_args = parser.parse_args(["list", "--prefix", "sim-"])
    assert list_args.command == "list"
    assert list_args.prefix == "sim-"


def test_serve_empty_prefix_makes_no_http_request(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed(store, "ch-waka-0001", "waka-account-token")
    client = FakeClient()
    lines: list[str] = []

    summary = serve(
        client,
        store,
        interval=3600,
        seconds=900,
        prefix="sim-",
        cycles=1,
        at=AT,
        out=lines.append,
    )

    assert summary["cycles"] == 1
    assert summary["accounts"] == 0
    assert summary["increments"] == 0
    assert client.increment_calls == []
    assert client.status_calls == []
    assert client.shop_calls == []
    assert client.purchase_calls == []
    output = "\n".join(lines)
    assert "accounts=0" in output
    assert "waka-account-token" not in output


def test_tick_prefix_only_touches_matching_accounts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed(store, "sim-0001", "token-sim-one")
    _seed(store, "sim-0002", "token-sim-two")
    _seed(store, "ch-waka-0001", "token-waka")
    client = FakeClient()

    summary = tick(
        client,
        store,
        seconds=900,
        prefix="sim-",
        at=AT,
        out=lambda _line: None,
    )

    assert summary["accounts"] == 2
    assert summary["increments"] == 2
    assert [call[0] for call in client.increment_calls] == [
        "token-sim-one",
        "token-sim-two",
    ]


@pytest.mark.parametrize("interval", [0, -1])
def test_serve_rejects_invalid_interval(tmp_path: Path, interval: int) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="interval"):
        serve(
            FakeClient(),
            store,
            interval=interval,
            seconds=900,
            cycles=1,
            out=lambda _line: None,
        )


@pytest.mark.parametrize("seconds", [0, -1])
def test_serve_rejects_invalid_seconds(tmp_path: Path, seconds: int) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="seconds"):
        serve(
            FakeClient(),
            store,
            interval=3600,
            seconds=seconds,
            cycles=1,
            out=lambda _line: None,
        )
