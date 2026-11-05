"""Legacy Waka AI rows can be adopted into ordinary accounts in place."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.game.store import SOURCE_AI, GameStore
from ghost_league.schedule import TZ

OWNER_TOKEN = "adoption-owner-token"
PROVISIONING_TOKEN = "adoption-service-token"
CHANNEL_TOKEN = "adoption-channel-token"
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=TZ)
WEEK = "2026-11-02"
SOURCE_HASH = "legacy-waka-source-hash"
CHANNEL_ID = "waka"
PLAYER_REF = "waka-user-1"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_app(tmp_path: Path):
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
        provisioning_token=PROVISIONING_TOKEN,
        now_fn=lambda: NOW,
        game_now_fn=lambda: NOW,
    )
    return app, tmp_path / "league.db", accounts_db


def _seed_legacy_ai(game_db: Path) -> str:
    store = GameStore(game_db, epoch_reason="test")
    store.ensure_week(WEEK)
    player, created = store.upsert_ai_player(
        SOURCE_HASH,
        display_name="AI-LEGACY",
        joined_week=WEEK,
        last_seen_week=WEEK,
        now=NOW,
    )
    assert created is True
    player_id = str(player["id"])
    store.ingest_activity(
        player_id,
        event_id="legacy:waka:20261105T12",
        seconds=600,
        occurred_at=NOW,
        source=SOURCE_AI,
        now=NOW,
    )
    with store.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO groups (week_start, tier, group_no, created_at) "
            "VALUES (?, 'Bronze', 1, ?)",
            (WEEK, NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO group_members "
            "(group_id, player_id, tier_at_start, is_human, joined_at) "
            "VALUES (?, ?, 'Bronze', 0, ?)",
            (int(cursor.lastrowid), player_id, NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO channel_players "
            "(channel_id, player_ref, player_id, kind, profile_json, "
            "created_at, updated_at) VALUES (?, ?, ?, 'ai', '{}', ?, ?)",
            (
                CHANNEL_ID,
                PLAYER_REF,
                player_id,
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )
    return player_id


def _seed_legacy_ai_with_id(
    game_db: Path,
    player_id: str,
    source_hash: str,
) -> str:
    store = GameStore(game_db, epoch_reason="test")
    store.ensure_week(WEEK)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO players "
            "(id, kind, controller, source_kind, source_key_hash, display_name, "
            "joined_week, last_seen_week, created_at, is_active) "
            "VALUES (?, 'ai', 'ai', ?, ?, 'AI-LEGACY', ?, ?, ?, 1)",
            (
                player_id,
                SOURCE_AI,
                source_hash,
                WEEK,
                WEEK,
                NOW.isoformat(),
            ),
        )
    return player_id


def _payload(player_id: str, **overrides) -> dict:
    payload = {
        "user_id": player_id,
        "display_name": "Adopted Legacy",
        "activity_label": "练习",
        "adopt_existing_player": True,
    }
    payload.update(overrides)
    return payload


def _snapshot(game_db: Path, player_id: str) -> dict:
    with sqlite3.connect(game_db) as conn:
        conn.row_factory = sqlite3.Row
        player = conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        scores = conn.execute(
            "SELECT week_start, seconds, xp FROM weekly_scores "
            "WHERE player_id = ? ORDER BY week_start",
            (player_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT event_id, seconds FROM activity_events "
            "WHERE player_id = ? ORDER BY event_id",
            (player_id,),
        ).fetchall()
        memberships = conn.execute(
            "SELECT group_id, player_id, tier_at_start FROM group_members "
            "WHERE player_id = ? ORDER BY group_id",
            (player_id,),
        ).fetchall()
        mappings = conn.execute(
            "SELECT channel_id, player_ref, player_id, kind FROM channel_players "
            "WHERE player_id = ? ORDER BY channel_id, player_ref",
            (player_id,),
        ).fetchall()
        wallet_count = conn.execute(
            "SELECT COUNT(*) FROM diamond_balance WHERE player_id = ?",
            (player_id,),
        ).fetchone()[0]
    return {
        "player": dict(player) if player is not None else None,
        "scores": [tuple(row) for row in scores],
        "events": [tuple(row) for row in events],
        "memberships": [tuple(row) for row in memberships],
        "mappings": [tuple(row) for row in mappings],
        "wallet_count": int(wallet_count),
    }


def test_adopt_ai_preserves_identity_history_and_waka_sync(tmp_path: Path) -> None:
    player_id = _seed_legacy_ai(tmp_path / "league.db")
    app, game_db, accounts_db = _make_app(tmp_path)

    before = _snapshot(game_db, player_id)
    assert before["player"] is not None
    assert before["player"]["kind"] == "ai"
    assert before["player"]["source_key_hash"] == SOURCE_HASH
    assert before["wallet_count"] == 0
    assert before["scores"]
    assert before["events"]
    assert before["memberships"]
    assert len(before["mappings"]) == 1

    with TestClient(app) as client:
        response = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(player_id),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["account"]["user_id"] == player_id
        assert body["token"]

        with sqlite3.connect(accounts_db) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM users WHERE user_id = ?", (player_id,)
            ).fetchone()[0] == 1

        after = _snapshot(game_db, player_id)
        assert after["player"]["id"] == player_id
        assert after["player"]["kind"] == "human"
        assert after["player"]["controller"] == "human"
        assert after["player"]["source_kind"] == "local_increment"
        assert after["player"]["is_active"] == 1
        assert after["player"]["source_key_hash"] == SOURCE_HASH
        assert after["player"]["joined_week"] == before["player"]["joined_week"]
        assert after["player"]["last_seen_week"] == before["player"]["last_seen_week"]
        assert after["player"]["created_at"] == before["player"]["created_at"]
        assert after["scores"] == before["scores"]
        assert after["events"] == before["events"]
        assert after["memberships"] == before["memberships"]
        assert after["mappings"] == before["mappings"]
        assert after["wallet_count"] == 1

        status_response = client.get(
            "/v1/me/status", headers=_headers(body["token"])
        )
        assert status_response.status_code == 200, status_response.text
        status = status_response.json()
        assert status["user_id"] == player_id
        assert status["xp"] == before["scores"][0][2]

        increment = client.post(
            "/v1/me/increments",
            headers=_headers(body["token"]),
            json={
                "event_id": "adoption:first-human-increment",
                "seconds": 300,
                "occurred_at": NOW.isoformat(),
            },
        )
        assert increment.status_code == 200, increment.text
        refreshed = client.get(
            "/v1/me/status", headers=_headers(body["token"])
        ).json()
        assert refreshed["xp"] >= status["xp"]

        duplicate = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(player_id, display_name="Again"),
        )
        assert duplicate.status_code == 409

    # A later weekly Waka sync must refresh the adopted human, not resurrect
    # a duplicate AI identity for the same source key.
    store = GameStore(game_db, epoch_reason="test")
    lookup = store.get_player_by_source_key_hash(SOURCE_HASH)
    assert lookup is not None and lookup["id"] == player_id
    with sqlite3.connect(game_db) as conn:
        player_count_before = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]

    player, created = store.upsert_ai_player(
        SOURCE_HASH,
        display_name="AI-REFRESHED",
        joined_week=WEEK,
        last_seen_week=WEEK,
        now=NOW,
    )
    assert created is False
    assert player["id"] == player_id
    assert player["kind"] == "human"
    assert player["controller"] == "human"
    assert player["display_name"] == "AI-REFRESHED"
    assert store.get_player_by_source_key_hash(SOURCE_HASH)["id"] == player_id
    with sqlite3.connect(game_db) as conn:
        player_count_after = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        matching = conn.execute(
            "SELECT COUNT(*) FROM players WHERE source_key_hash = ?",
            (SOURCE_HASH,),
        ).fetchone()[0]
    assert player_count_after == player_count_before
    assert matching == 1


def test_channel_refresh_cannot_demote_adopted_human(tmp_path: Path) -> None:
    player_id = _seed_legacy_ai(tmp_path / "league.db")
    app, game_db, _ = _make_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(player_id),
        )
        assert response.status_code == 201, response.text

    adopted = _snapshot(game_db, player_id)
    assert adopted["player"]["kind"] == "human"
    assert adopted["player"]["controller"] == "human"
    assert adopted["player"]["source_kind"] == "local_increment"
    assert adopted["player"]["source_key_hash"] == SOURCE_HASH
    assert adopted["scores"]
    assert adopted["events"]
    assert adopted["memberships"]
    assert adopted["wallet_count"] == 1
    # Adoption leaves the legacy mapping metadata untouched.
    assert adopted["mappings"] == [(CHANNEL_ID, PLAYER_REF, player_id, "ai")]

    store = GameStore(game_db, epoch_reason="test")
    refreshed, created = store.upsert_channel_player(
        CHANNEL_ID,
        PLAYER_REF,
        kind="ai",
        profile={"display_name": "Waka Refreshed"},
        joined_week=WEEK,
        now=NOW,
    )
    assert created is False
    assert refreshed["id"] == player_id
    assert refreshed["kind"] == "human"
    assert refreshed["controller"] == "human"
    assert refreshed["source_kind"] == adopted["player"]["source_kind"]
    assert refreshed["display_name"] == "Waka Refreshed"

    after = _snapshot(game_db, player_id)
    assert after["scores"] == adopted["scores"]
    assert after["events"] == adopted["events"]
    assert after["memberships"] == adopted["memberships"]
    assert after["wallet_count"] == adopted["wallet_count"]
    assert after["mappings"] == [(CHANNEL_ID, PLAYER_REF, player_id, "human")]

    replay, replayed_created = store.upsert_channel_player(
        CHANNEL_ID,
        PLAYER_REF,
        kind="ai",
        profile={"display_name": "Waka Refreshed"},
        joined_week=WEEK,
        now=NOW,
    )
    assert replayed_created is False
    assert replay == refreshed
    assert _snapshot(game_db, player_id) == after

    # A genuinely new legacy roster entry is still allowed to be AI.
    fresh, fresh_created = store.upsert_channel_player(
        CHANNEL_ID,
        "fresh-legacy-ref",
        kind="ai",
        profile={"display_name": "Fresh Legacy"},
        joined_week=WEEK,
        now=NOW,
    )
    assert fresh_created is True
    assert fresh["kind"] == "ai"
    assert fresh["controller"] == "ai"
    assert store.get_channel_player(CHANNEL_ID, "fresh-legacy-ref")["kind"] == "ai"


def test_67_character_legacy_id_can_be_provisioned_and_adopted(
    tmp_path: Path,
) -> None:
    legacy_id = "ch-" + "0123456789abcdef" * 4
    assert len(legacy_id) == 67
    player_id = _seed_legacy_ai_with_id(
        tmp_path / "league.db",
        legacy_id,
        "legacy-ch-source-hash",
    )
    app, game_db, accounts_db = _make_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(player_id),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["account"]["user_id"] == legacy_id
        assert body["token"]

        status_response = client.get(
            "/v1/me/status", headers=_headers(body["token"])
        )
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["user_id"] == legacy_id

    with sqlite3.connect(game_db) as conn:
        kind = conn.execute(
            "SELECT kind FROM players WHERE id = ?", (legacy_id,)
        ).fetchone()[0]
        wallet_count = conn.execute(
            "SELECT COUNT(*) FROM diamond_balance WHERE player_id = ?",
            (legacy_id,),
        ).fetchone()[0]
    with sqlite3.connect(accounts_db) as conn:
        account_count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE user_id = ?", (legacy_id,)
        ).fetchone()[0]
    assert kind == "human"
    assert wallet_count == 1
    assert account_count == 1


def test_adoption_errors_missing_human_owner_and_duplicate(tmp_path: Path) -> None:
    app, game_db, _ = _make_app(tmp_path)
    store = GameStore(game_db, epoch_reason="test")
    store.ensure_week(WEEK)
    human_id = "human-legacy"
    store.ensure_human_player(
        human_id,
        display_name="Legacy Human",
        joined_week=WEEK,
        now=NOW,
    )

    with TestClient(app) as client:
        missing = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload("ai-does-not-exist"),
        )
        assert missing.status_code == 404

        human = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload(human_id),
        )
        assert human.status_code == 409
        assert human.json()["detail"] == "player already human"

        owner = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json=_payload("owner"),
        )
        assert owner.status_code == 422

        # A brand-new ordinary account still uses the v1 path.
        new_account = client.post(
            "/v1/provisioning/accounts",
            headers=_headers(PROVISIONING_TOKEN),
            json={
                "user_id": "sim-new",
                "display_name": "New Sim",
                "activity_label": "练习",
            },
        )
        assert new_account.status_code == 201, new_account.text
        assert new_account.json()["account"]["user_id"] == "sim-new"
