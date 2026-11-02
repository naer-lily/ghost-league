from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.game.rules import (
    DuplicateIdempotencyKey,
    InsufficientDiamonds,
    ShopCooldown,
    ShopNotAllowed,
    ShopQuantityRejected,
    UnknownShopItem,
)
from ghost_league.game.store import GameStore
from ghost_league.schedule import TZ

TOKEN = "shop-token"
CHANNEL_TOKEN = "shop-channel-token"
CHANNEL = "shop-channel"
NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def make_human(store: GameStore, player_id: str = "human-1") -> str:
    store.create_player(
        player_id,
        kind="human",
        joined_week=WEEK_START,
        now=f"{WEEK_START}T00:00:00+08:00",
    )
    return player_id


def make_ai(store: GameStore, player_id: str = "ai-1") -> str:
    store.create_player(
        player_id,
        kind="ai",
        joined_week=WEEK_START,
        now=f"{WEEK_START}T00:00:00+08:00",
    )
    return player_id


# ----------------------------------------------------------------------
# Store
# ----------------------------------------------------------------------
def test_initial_wallet_inventory_and_catalog_are_empty(tmp_path) -> None:
    store = make_store(tmp_path)

    assert store.get_diamond_balance("human-1") == 0
    assert store.get_inventory("human-1") == {"star": 0}
    catalog = {item["id"]: item for item in store.shop_catalog("human-1", now=NOW)}
    assert set(catalog) == {"star", "ember"}
    assert catalog["star"]["price_diamonds"] == 300
    assert catalog["star"]["currency"] == "diamonds"
    assert catalog["star"]["owned_quantity"] == 0
    assert catalog["star"]["cooldown_seconds"] == 0
    assert catalog["star"]["cooldown_until"] is None
    assert catalog["ember"]["price_diamonds"] == 800
    assert catalog["ember"]["cooldown_seconds"] == 259_200
    assert catalog["ember"]["available"] is True

    with sqlite3.connect(tmp_path / "league.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM diamond_balance"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory_items"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_items"
        ).fetchone()[0] == 2


def test_credit_diamonds_is_idempotent_and_ai_is_rejected(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    first = store.credit_diamonds(
        human, 3000, "test", idempotency_key="credit-1", now=NOW
    )
    replay = store.credit_diamonds(
        human, 3000, "test", idempotency_key="credit-1", now=NOW
    )
    assert first["balance"] == 3000
    assert first["duplicate"] is False
    assert replay["duplicate"] is True
    assert store.get_diamond_balance(human) == 3000
    assert len(store.diamond_ledger(human)) == 1
    with pytest.raises(DuplicateIdempotencyKey):
        store.credit_diamonds(
            human, 4000, "test", idempotency_key="credit-1", now=NOW
        )

    ai = make_ai(store)
    assert store.get_diamond_balance(ai) == 0
    assert store.get_inventory(ai) == {"star": 0}
    with pytest.raises(ShopNotAllowed):
        store.credit_diamonds(ai, 100, "test", idempotency_key="ai-credit")
    with sqlite3.connect(tmp_path / "league.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM diamond_balance WHERE player_id = ?", (ai,)
        ).fetchone()[0] == 0


def test_buy_star_deducts_grants_and_replays_once(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 1000, "test", idempotency_key="credit-1", now=NOW
    )

    result = store.purchase_shop_item(
        human, "star", 1, "shop-star-1", now=NOW
    )
    assert result == {
        "ok": True,
        "item_id": "star",
        "quantity": 1,
        "diamonds": 700,
        "inventory": {"star": 1, "ember": 0},
        "cooldown_until": None,
        "replayed": False,
    }
    assert store.get_diamond_balance(human) == 700
    assert store.get_inventory(human) == {"star": 1}
    ledger = store.diamond_ledger(human)
    assert [row["delta"] for row in ledger] == [1000, -300]
    assert ledger[-1]["balance_after"] == 700
    assert ledger[-1]["reason"] == "shop_purchase"
    assert ledger[-1]["ref_id"] == "star"

    replay = store.purchase_shop_item(
        human, "star", 1, "shop-star-1", now=NOW + timedelta(hours=1)
    )
    assert replay["replayed"] is True
    assert replay["diamonds"] == 700
    assert replay["inventory"] == {"star": 1, "ember": 0}
    assert store.get_diamond_balance(human) == 700
    assert len(store.diamond_ledger(human)) == 2
    assert store.get_inventory(human) == {"star": 1}

    with pytest.raises(DuplicateIdempotencyKey):
        store.purchase_shop_item(human, "star", 2, "shop-star-1", now=NOW)


def test_buy_multiple_stars_and_insufficient_balance_rolls_back(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 1000, "test", idempotency_key="credit-1", now=NOW
    )

    multi = store.purchase_shop_item(human, "star", 3, "shop-star-3", now=NOW)
    assert multi["diamonds"] == 100
    assert multi["inventory"] == {"star": 3, "ember": 0}
    assert store.get_inventory(human) == {"star": 3}

    before = store.diamond_ledger(human)
    with pytest.raises(InsufficientDiamonds) as exc:
        store.purchase_shop_item(human, "star", 1, "shop-star-4", now=NOW)
    assert exc.value.balance == 100
    assert store.diamond_ledger(human) == before
    assert store.get_inventory(human) == {"star": 3}
    with sqlite3.connect(tmp_path / "league.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_purchase_requests "
            "WHERE request_id = 'shop-star-4'"
        ).fetchone()[0] == 0

    no_wallet = make_human(store, "human-2")
    with pytest.raises(InsufficientDiamonds):
        store.purchase_shop_item(no_wallet, "star", 1, "shop-none", now=NOW)
    assert store.get_diamond_balance(no_wallet) == 0
    assert store.get_inventory(no_wallet) == {"star": 0}


def test_ember_purchase_updates_balance_ledgers_and_cooldown(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 2000, "test", idempotency_key="credit-1", now=NOW
    )

    result = store.purchase_shop_item(
        human, "ember", 1, "shop-ember-1", now=NOW
    )
    assert result["diamonds"] == 1200
    assert result["inventory"] == {"star": 0, "ember": 1}
    assert result["cooldown_until"] == "2026-11-05T12:00:00+08:00"
    assert store.get_ember_balance(human)["balance"] == 1
    assert store.get_inventory(human) == {"star": 0}

    diamond_ledger = store.diamond_ledger(human)
    assert diamond_ledger[-1]["delta"] == -800
    assert diamond_ledger[-1]["balance_after"] == 1200
    ember_ledger = store.ember_ledger(human)
    assert len(ember_ledger) == 1
    assert ember_ledger[0]["delta"] == 1
    assert ember_ledger[0]["reason"] == "shop_purchase"

    catalog = {item["id"]: item for item in store.shop_catalog(human, now=NOW)}
    assert catalog["ember"]["cooldown_until"] == "2026-11-05T12:00:00+08:00"
    assert catalog["ember"]["available"] is False
    assert catalog["ember"]["owned_quantity"] == 1

    with pytest.raises(ShopCooldown) as exc:
        store.purchase_shop_item(
            human, "ember", 1, "shop-ember-2", now=NOW + timedelta(hours=71, minutes=59)
        )
    assert exc.value.cooldown_until == "2026-11-05T12:00:00+08:00"
    assert store.get_ember_balance(human)["balance"] == 1

    allowed = store.purchase_shop_item(
        human, "ember", 1, "shop-ember-3", now=NOW + timedelta(hours=72)
    )
    assert allowed["diamonds"] == 400
    assert allowed["inventory"] == {"star": 0, "ember": 2}
    assert store.get_ember_balance(human)["balance"] == 2

    replay = store.purchase_shop_item(
        human, "ember", 1, "shop-ember-3", now=NOW + timedelta(hours=96)
    )
    assert replay["replayed"] is True
    assert replay["diamonds"] == 400
    assert replay["cooldown_until"] == "2026-11-08T12:00:00+08:00"
    assert store.get_ember_balance(human)["balance"] == 2


def test_unknown_items_and_bad_quantities_are_rejected(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 10_000, "test", idempotency_key="credit-1", now=NOW
    )
    with pytest.raises(UnknownShopItem):
        store.purchase_shop_item(human, "nope", 1, "unknown-1", now=NOW)
    for quantity in (0, -1):
        with pytest.raises(ShopQuantityRejected):
            store.purchase_shop_item(
                human, "star", quantity, f"bad-{quantity}", now=NOW
            )
    with pytest.raises(ShopQuantityRejected) as exc:
        store.purchase_shop_item(human, "star", 100, "bad-star-100", now=NOW)
    assert exc.value.code == "quantity_too_large"
    with pytest.raises(ShopQuantityRejected) as exc:
        store.purchase_shop_item(human, "ember", 2, "bad-ember-2", now=NOW)
    assert exc.value.code == "ember_quantity"

    assert store.get_diamond_balance(human) == 10_000
    assert store.get_inventory(human) == {"star": 0}
    assert len(store.diamond_ledger(human)) == 1


def test_ai_cannot_purchase_or_get_a_wallet(tmp_path) -> None:
    store = make_store(tmp_path)
    ai = make_ai(store)
    with pytest.raises(ShopNotAllowed):
        store.purchase_shop_item(ai, "star", 1, "ai-shop-1", now=NOW)
    with sqlite3.connect(tmp_path / "league.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM diamond_balance WHERE player_id = ?", (ai,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_purchase_requests WHERE player_id = ?",
            (ai,),
        ).fetchone()[0] == 0


def test_old_database_gets_new_tables_and_seeds_idempotently(tmp_path) -> None:
    path = tmp_path / "league.db"
    store = GameStore(path, epoch_reason="test")
    make_human(store)
    with sqlite3.connect(path) as connection:
        for table in (
            "inventory_items",
            "shop_items",
            "shop_purchase_cooldowns",
            "shop_purchase_requests",
            "diamond_balance",
            "diamond_ledger",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.commit()

    reopened = GameStore(path, epoch_reason="test")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "inventory_items",
            "shop_items",
            "shop_purchase_cooldowns",
            "shop_purchase_requests",
            "diamond_balance",
            "diamond_ledger",
        } <= tables
        assert connection.execute(
            "SELECT COUNT(*) FROM players"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_items"
        ).fetchone()[0] == 2

    reopened.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_items"
        ).fetchone()[0] == 2
    assert reopened.get_inventory("human-1") == {"star": 0}


# ----------------------------------------------------------------------
# HTTP API
# ----------------------------------------------------------------------
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


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ShopAPITests(unittest.TestCase):
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

    def seed_roster(self, client: TestClient) -> None:
        response = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=auth(CHANNEL_TOKEN),
            json={
                "players": [
                    {"player_ref": f"channel-ai-{index:02d}", "kind": "ai"}
                    for index in range(2)
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    @contextmanager
    def client(self):
        with TestClient(self.app()) as client:
            self.seed_roster(client)
            yield client

    def credit(self, client: TestClient, amount: int, key: str = "credit") -> None:
        client.app.state.game_service.store.credit_diamonds(
            "owner", amount, "test", idempotency_key=key, now=self.clock["now"]
        )

    def test_status_both_projections_have_diamonds_and_inventory(self) -> None:
        with self.client() as client:
            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["diamonds"], 0)
            self.assertEqual(status["inventory"], {"star": 0, "ember": 0})
            self.assertIn("gems", status)
            self.assertIn("embers", status)

            with sqlite3.connect(self.game_db_path) as connection:
                channel_player = str(
                    connection.execute(
                        "SELECT player_id FROM channel_players LIMIT 1"
                    ).fetchone()[0]
                )
            channel_status = client.app.state.game_service.status_for_user(
                channel_player
            )
            self.assertIsNotNone(channel_status)
            self.assertEqual(channel_status["diamonds"], 0)
            self.assertEqual(
                channel_status["inventory"], {"star": 0, "ember": 0}
            )
            self.assertIn("gems", channel_status)

            standings = client.get("/v1/league/standings", headers=auth()).json()
            for row in standings["standings"]:
                self.assertNotIn("diamonds", row)
                self.assertNotIn("inventory", row)

    def test_shop_get_and_star_purchase_are_projected(self) -> None:
        with self.client() as client:
            self.credit(client, 3000)
            shop = client.get("/v1/shop", headers=auth())
            self.assertEqual(shop.status_code, 200, shop.text)
            catalog = {item["id"]: item for item in shop.json()}
            self.assertEqual(set(catalog), {"star", "ember"})
            self.assertEqual(catalog["star"]["price_diamonds"], 300)
            self.assertEqual(catalog["star"]["currency"], "diamonds")
            self.assertEqual(catalog["star"]["owned_quantity"], 0)
            self.assertEqual(catalog["star"]["cooldown_seconds"], 0)
            self.assertIsNone(catalog["star"]["cooldown_until"])
            self.assertTrue(catalog["star"]["available"])
            self.assertEqual(catalog["ember"]["price_diamonds"], 800)
            self.assertEqual(catalog["ember"]["cooldown_seconds"], 259200)

            purchase = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "quantity": 1,
                    "request_id": "shop-20261102-001",
                },
            )
            self.assertEqual(purchase.status_code, 200, purchase.text)
            self.assertEqual(
                purchase.json(),
                {
                    "ok": True,
                    "item_id": "star",
                    "quantity": 1,
                    "diamonds": 2700,
                    "inventory": {"star": 1, "ember": 0},
                    "cooldown_until": None,
                    "replayed": False,
                },
            )

            replay = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "quantity": 1,
                    "request_id": "shop-20261102-001",
                },
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertTrue(replay.json()["replayed"])
            self.assertEqual(replay.json()["diamonds"], 2700)

            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["diamonds"], 2700)
            self.assertEqual(status["inventory"]["star"], 1)
            self.assertEqual(status["inventory"]["ember"], 0)

    def test_purchase_error_statuses_and_fields(self) -> None:
        with self.client() as client:
            insufficient = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "request_id": "no-money"},
            )
            self.assertEqual(insufficient.status_code, 409, insufficient.text)
            body = insufficient.json()
            self.assertEqual(body["code"], "insufficient_diamonds")
            self.assertEqual(body["balance"], 0)
            self.assertEqual(body["detail"]["balance"], 0)

            self.credit(client, 2000)
            unknown = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "nope", "request_id": "unknown"},
            )
            self.assertEqual(unknown.status_code, 404, unknown.text)

            zero = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "quantity": 0, "request_id": "zero"},
            )
            self.assertEqual(zero.status_code, 422, zero.text)
            too_many = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "quantity": 100, "request_id": "100"},
            )
            self.assertEqual(too_many.status_code, 422, too_many.text)
            ember_two = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "quantity": 2, "request_id": "e2"},
            )
            self.assertEqual(ember_two.status_code, 422, ember_two.text)
            missing_request_id = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star"},
            )
            self.assertEqual(missing_request_id.status_code, 422)

    def test_ember_cooldown_is_enforced_over_http(self) -> None:
        with self.client() as client:
            self.credit(client, 2000)
            first = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "request_id": "ember-1"},
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["diamonds"], 1200)
            self.assertEqual(
                first.json()["cooldown_until"], "2026-11-05T12:00:00+08:00"
            )

            self.clock["now"] = NOW + timedelta(hours=1)
            blocked = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "request_id": "ember-2"},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            body = blocked.json()
            self.assertEqual(body["code"], "cooldown")
            self.assertEqual(
                body["cooldown_until"], "2026-11-05T12:00:00+08:00"
            )
            self.assertEqual(
                body["detail"]["cooldown_until"], "2026-11-05T12:00:00+08:00"
            )

            with sqlite3.connect(self.game_db_path) as connection:
                assert connection.execute(
                    "SELECT balance FROM ember_balance WHERE player_id = 'owner'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM inventory_items WHERE player_id = 'owner'"
                ).fetchone()[0] == 0

            self.clock["now"] = NOW + timedelta(hours=72)
            second = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "request_id": "ember-3"},
            )
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["diamonds"], 400)
            self.assertEqual(second.json()["inventory"]["ember"], 2)

            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["inventory"]["ember"], 2)

    def test_ai_has_no_shop_presence_in_public_views(self) -> None:
        with self.client() as client:
            with sqlite3.connect(self.game_db_path) as connection:
                ai_id = str(
                    connection.execute(
                        "SELECT player_id FROM channel_players LIMIT 1"
                    ).fetchone()[0]
                )
            store = client.app.state.game_service.store
            self.assertEqual(store.get_diamond_balance(ai_id), 0)
            self.assertEqual(store.get_inventory(ai_id), {"star": 0})
            standings = client.get("/v1/league/standings", headers=auth()).json()
            for row in standings["standings"]:
                self.assertNotIn("diamonds", row)
                self.assertNotIn("inventory", row)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
