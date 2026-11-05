"""Account provisioning is a separate, narrow privilege from account auth."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.schedule import TZ

OWNER_TOKEN = "provisioning-owner-token"
PROVISIONING_TOKEN = "provisioning-service-token"
CHANNEL_TOKEN = "provisioning-channel-token"
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=TZ)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_app(
    tmp_path: Path,
    *,
    provisioning_token: str | None = PROVISIONING_TOKEN,
):
    api_dir = tmp_path / "api"
    api_dir.mkdir(parents=True)
    accounts_db = api_dir / "accounts.db"
    accounts = AccountsStore(accounts_db, now_fn=lambda: NOW)
    accounts.initialize()
    accounts.create("owner", "You", token=OWNER_TOKEN)
    app = create_app(
        game_db_path=tmp_path / "league.db",
        cache_path=tmp_path / "cache.json",
        avatars_path=tmp_path / "avatars.json",
        api_dir=api_dir,
        accounts_db=accounts_db,
        social_db=api_dir / "social.db",
        webhooks_db=api_dir / "webhooks.db",
        start_webhook_worker=False,
        token=OWNER_TOKEN,
        channel_token=CHANNEL_TOKEN,
        provisioning_token=provisioning_token,
        now_fn=lambda: NOW,
        game_now_fn=lambda: NOW,
    )
    return app, tmp_path / "league.db"


def _payload(**overrides):
    payload = {
        "user_id": "sim-0001",
        "display_name": "Sim One",
        "activity_label": "练习",
    }
    payload.update(overrides)
    return payload


def test_missing_and_wrong_provisioning_token_are_401(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/v1/provisioning/accounts", json=_payload()).status_code == 401
        assert (
            client.post(
                "/v1/provisioning/accounts",
                headers=_headers("wrong-token"),
                json=_payload(),
            ).status_code
            == 401
        )


def test_missing_configured_provisioning_token_is_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GHOST_LEAGUE_PROVISIONING_TOKEN", raising=False)
    app, _ = _make_app(tmp_path, provisioning_token=None)
    with TestClient(app) as client:
        response = client.post(
            "/v1/provisioning/accounts",
            headers=_headers("anything"),
            json=_payload(),
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "service_token_not_configured"


def test_create_returns_account_and_working_token(tmp_path: Path) -> None:
    app, game_db = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["account"]["user_id"] == "sim-0001"
        assert body["account"]["display_name"] == "Sim One"
        assert body["account"]["activity_label"] == "练习"
        assert body["token"]

        status_response = client.get("/v1/me/status", headers=_headers(body["token"]))
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["user_id"] == "sim-0001"

        with sqlite3.connect(game_db) as connection:
            player = connection.execute(
                "SELECT source_kind FROM players WHERE id = ?", ("sim-0001",)
            ).fetchone()
            wallet = connection.execute(
                "SELECT balance FROM diamond_balance WHERE player_id = ?",
                ("sim-0001",),
            ).fetchone()
            channel_players = connection.execute(
                "SELECT COUNT(*) FROM channel_players"
            ).fetchone()[0]
        assert player is not None and player[0] == "local_increment"
        assert wallet is not None
        assert channel_players == 0


def test_duplicate_owner_and_malformed_bodies_are_rejected(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    with TestClient(app) as client:
        first = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(),
        )
        assert first.status_code == 201, first.text

        duplicate = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(display_name="Another Name"),
        )
        assert duplicate.status_code == 409

        owner = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(user_id="owner"),
        )
        assert owner.status_code == 422

        malformed = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json={
                "user_id": "sim-0002",
                "display_name": "Sim Two",
                "activity_label": "练习",
                "kind": "ai",
            },
        )
        assert malformed.status_code == 422

        bad_user_id = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(user_id="../escape"),
        )
        assert bad_user_id.status_code == 422

        blank_name = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(user_id="sim-0003", display_name="   "),
        )
        assert blank_name.status_code == 422


@pytest.mark.parametrize(
    "user_id",
    [
        "sim-0001",
        "a",
        "a" * 64,
        "a" * 80,
    ],
    ids=["short", "single-character", "legacy-64", "max-80"],
)
def test_user_ids_up_to_80_characters_are_accepted(
    tmp_path: Path,
    user_id: str,
) -> None:
    app, _ = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(user_id=user_id),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["account"]["user_id"] == user_id

        status_response = client.get("/v1/me/status", headers=_headers(body["token"]))
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["user_id"] == user_id


def test_81_character_user_id_is_rejected(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(user_id="a" * 81),
        )
        assert response.status_code == 422, response.text


def test_token_namespaces_do_not_cross_authorize(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    with TestClient(app) as client:
        assert (
            client.get(
                "/v1/me/status",
                headers=_headers(PROVISIONING_TOKEN),
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/v1/provisioning/accounts",
                headers=_headers(OWNER_TOKEN),
                json=_payload(),
            ).status_code
            == 401
        )


def test_increment_uses_existing_human_path(tmp_path: Path) -> None:
    app, game_db = _make_app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(),
        )
        token = created.json()["token"]
        before = client.get("/v1/me/status", headers=_headers(token)).json()
        response = client.post(
            "/v1/me/increments",
            headers=_headers(token),
            json={
                "event_id": "ai_channel:sim-0001:20261105T12",
                "seconds": 600,
                "occurred_at": NOW.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        after = client.get("/v1/me/status", headers=_headers(token)).json()
        assert after["xp"] > before["xp"]
        with sqlite3.connect(game_db) as connection:
            source_kind = connection.execute(
                "SELECT source_kind FROM players WHERE id = ?", ("sim-0001",)
            ).fetchone()[0]
        assert source_kind == "local_increment"
