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
from ghost_league.game.jobs import run_diamond_decay
from ghost_league.game.rules import (
    ShopNotAllowed,
    ShopNotAvailable,
    ShopQuantityRejected,
)
from ghost_league.game.store import GameStore, compute_diamond_decay
from ghost_league.schedule import TZ

TOKEN = "shop-token"
CHANNEL_TOKEN = "shop-channel-token"
CHANNEL = "shop-channel"
NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def make_human(
    store: GameStore,
    player_id: str = "human-1",
    *,
    now: datetime | str = NOW,
) -> str:
    store.create_player(
        player_id,
        kind="human",
        joined_week=WEEK_START,
        now=now,
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


def catalog(store: GameStore, player_id: str, *, now: datetime = NOW):
    return {item["id"]: item for item in store.shop_catalog(player_id, now=now)}


# ----------------------------------------------------------------------
# Wallet and soft cap
# ----------------------------------------------------------------------
def test_new_human_wallet_and_catalog(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    wallet = store.get_diamond_wallet(human, now=NOW)
    assert wallet == {
        "balance": 1000,
        "diamond_cap": 1000,
        "diamond_cap_level": 0,
        "diamond_excess": 0,
        "last_decay_at": "2026-11-02T12:00:00+08:00",
    }
    assert store.get_diamond_balance(human, now=NOW) == 1000
    assert store.get_inventory(human) == {"star": 0, "seasonal_star": 0}

    items = catalog(store, human)
    assert set(items) == {
        "star",
        "seasonal_star",
        "ember",
        "diamond_cap_1",
    }
    assert items["star"]["kind"] == "star"
    assert items["star"]["price_diamonds"] == 300
    assert items["seasonal_star"]["kind"] == "seasonal_star"
    assert items["seasonal_star"]["season_key"] == "2026-11"
    assert items["seasonal_star"]["price_diamonds"] == 500
    assert items["ember"]["kind"] == "ember"
    assert items["diamond_cap_1"]["kind"] == "cap"
    assert items["diamond_cap_1"]["required_cap_level"] == 0
    assert items["diamond_cap_1"]["price_diamonds"] == 500
    assert items["diamond_cap_1"]["available"] is True


def test_ai_has_no_wallet_inventory_or_stars(tmp_path) -> None:
    store = make_store(tmp_path)
    ai = make_ai(store)

    assert store.get_diamond_wallet(ai, now=NOW)["balance"] == 0
    assert store.get_diamond_wallet(ai, now=NOW)["diamond_cap"] == 0
    assert store.get_inventory(ai) == {"star": 0, "seasonal_star": 0}
    assert store.list_player_stars(ai) == []
    with pytest.raises(ShopNotAllowed):
        store.purchase_shop_item(ai, "star", 1, "ai-star", name="AI", now=NOW)
    with sqlite3.connect(tmp_path / "league.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM diamond_balance WHERE player_id = ?", (ai,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM player_stars WHERE player_id = ?", (ai,)
        ).fetchone()[0] == 0


def test_credit_adds_uncapped_and_one_hour_decay_is_idempotent(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    store.credit_diamonds(
        human, 500, "test", idempotency_key="credit-1", now=NOW
    )
    wallet = store.get_diamond_wallet(human, now=NOW)
    assert wallet["balance"] == 1500
    assert wallet["diamond_cap"] == 1000
    assert wallet["diamond_excess"] == 500

    one_hour = store.get_diamond_wallet(
        human, now=NOW + timedelta(hours=1)
    )
    assert one_hour["balance"] == 1495
    assert one_hour["diamond_excess"] == 495
    assert one_hour["last_decay_at"] == "2026-11-02T13:00:00+08:00"

    same_hour = store.get_diamond_wallet(
        human, now=NOW + timedelta(hours=1, minutes=30)
    )
    assert same_hour["balance"] == 1495
    assert same_hour["last_decay_at"] == "2026-11-02T13:00:00+08:00"

    two_hours = store.get_diamond_wallet(
        human, now=NOW + timedelta(hours=2)
    )
    assert two_hours["balance"] == 1490

    ledger = store.diamond_ledger(human)
    decay = [row for row in ledger if row["reason"] == "decay"]
    assert len(decay) == 2
    assert [row["delta"] for row in decay] == [-5, -5]
    assert all(row["balance_after"] >= 1000 for row in decay)
    assert len({row["idempotency_key"] for row in decay}) == 2


def test_offline_decay_uses_compound_formula_and_job(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 500, "test", idempotency_key="credit-1", now=NOW
    )

    # Offline for five complete hours: 500 * 0.99^5 -> 475 excess.
    later = store.get_diamond_wallet(human, now=NOW + timedelta(hours=5))
    assert later["balance"] == 1475
    assert later["last_decay_at"] == "2026-11-02T17:00:00+08:00"

    other = make_human(store, "human-2")
    store.credit_diamonds(
        other, 800, "test", idempotency_key="credit-2", now=NOW
    )
    result = run_diamond_decay(store.path, at=NOW + timedelta(hours=2))
    assert result["status"] == "decayed"
    assert result["decayed"] == 1
    assert result["lost"] == 16
    assert store.get_diamond_balance(other, now=NOW + timedelta(hours=2)) == 1784


def test_balance_at_or_below_cap_never_decays(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    assert store.get_diamond_balance(human, now=NOW + timedelta(hours=48)) == 1000
    assert store.diamond_ledger(human) == []
    store.credit_diamonds(
        human, 500, "test", idempotency_key="credit-1", now=NOW + timedelta(hours=48)
    )
    # Spending the excess back down to the cap stops decay.
    store.purchase_shop_item(
        human,
        "diamond_cap_1",
        1,
        "cap-1",
        now=NOW + timedelta(hours=48),
    )
    assert store.get_diamond_balance(human, now=NOW + timedelta(hours=96)) == 1000
    assert not [
        row for row in store.diamond_ledger(human) if row["reason"] == "decay"
    ]


def test_pure_decay_function_is_shared_and_monotonic() -> None:
    balance, lost, anchor = compute_diamond_decay(
        1500, 1000, NOW, NOW + timedelta(hours=1)
    )
    assert (balance, lost, anchor) == (
        1495,
        5,
        NOW + timedelta(hours=1),
    )
    # Same hour: no second charge and no anchor movement.
    assert compute_diamond_decay(1495, 1000, anchor, anchor) == (
        1495,
        0,
        anchor,
    )
    # Two whole hours are charged together.
    assert compute_diamond_decay(1500, 1000, NOW, NOW + timedelta(hours=2))[0] == 1490
    # At or below the cap nothing is lost.
    assert compute_diamond_decay(1000, 1000, NOW, NOW + timedelta(hours=9))[0] == 1000


def test_old_wallet_is_migrated_and_missing_human_wallet_is_backfilled(tmp_path) -> None:
    path = tmp_path / "league.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE diamond_balance ("
            "player_id TEXT PRIMARY KEY, balance INTEGER NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO diamond_balance (player_id, balance, updated_at) "
            "VALUES ('legacy', 4321, '2026-10-01T00:00:00+08:00')"
        )
        connection.commit()

    store = GameStore(path, epoch_reason="test")
    make_human(store, "legacy")
    wallet = store.get_diamond_wallet("legacy", now=NOW)
    assert wallet["balance"] == 4321
    assert wallet["diamond_cap"] == 1000
    assert wallet["diamond_cap_level"] == 0
    assert wallet["last_decay_at"] is not None

    human = make_human(store, "human-2")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM diamond_balance WHERE player_id = ?", (human,)
        )
        connection.commit()
    reopened = GameStore(path, epoch_reason="test")
    backfilled = reopened.get_diamond_wallet(human, now=NOW)
    assert backfilled["balance"] == 1000
    assert backfilled["diamond_cap"] == 1000
    assert backfilled["diamond_cap_level"] == 0


# ----------------------------------------------------------------------
# Cap upgrades
# ----------------------------------------------------------------------
def test_cap_upgrade_ladder_only_offers_the_next_level(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 7000, "test", idempotency_key="credit-1", now=NOW
    )

    prices = {1: 500, 2: 800, 3: 1200, 4: 1800, 5: 2600}
    with pytest.raises(ShopNotAvailable):
        store.purchase_shop_item(human, "diamond_cap_2", 1, "skip", now=NOW)
    with pytest.raises(ShopQuantityRejected):
        store.purchase_shop_item(
            human, "diamond_cap_1", 2, "double", now=NOW
        )

    for level, price in prices.items():
        items = catalog(store, human)
        cap_ids = [item_id for item_id in items if item_id.startswith("diamond_cap_")]
        assert cap_ids == [f"diamond_cap_{level}"]
        assert items[f"diamond_cap_{level}"]["price_diamonds"] == price
        result = store.purchase_shop_item(
            human, f"diamond_cap_{level}", 1, f"cap-{level}", now=NOW
        )
        assert result["diamond_cap"] == 1000 + level * 500
        assert result["diamond_cap_level"] == level
        assert result["diamond_excess"] == max(
            0, result["diamonds"] - result["diamond_cap"]
        )

    final = store.get_diamond_wallet(human, now=NOW)
    assert final["diamond_cap"] == 3500
    assert final["diamond_cap_level"] == 5
    assert final["balance"] == 1100
    assert not [
        item_id
        for item_id in catalog(store, human)
        if item_id.startswith("diamond_cap_")
    ]
    with pytest.raises(ShopNotAvailable):
        store.purchase_shop_item(human, "diamond_cap_1", 1, "again", now=NOW)


def test_cap_upgrade_absorbs_excess_and_stops_decay(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 500, "test", idempotency_key="credit-1", now=NOW
    )
    assert store.get_diamond_wallet(human, now=NOW)["diamond_excess"] == 500

    upgraded = store.purchase_shop_item(
        human, "diamond_cap_1", 1, "cap-1", now=NOW
    )
    assert upgraded["diamonds"] == 1000
    assert upgraded["diamond_cap"] == 1500
    assert upgraded["diamond_cap_level"] == 1
    assert upgraded["diamond_excess"] == 0

    assert store.get_diamond_balance(human, now=NOW + timedelta(hours=5)) == 1000
    assert not [
        row for row in store.diamond_ledger(human) if row["reason"] == "decay"
    ]


# ----------------------------------------------------------------------
# Named stars and seasonal stars
# ----------------------------------------------------------------------
def test_normal_stars_require_a_name_and_are_independent_records(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 1000, "test", idempotency_key="credit-1", now=NOW
    )
    before_ledger = len(store.diamond_ledger(human))

    for index, name in enumerate(
        (None, "", "   ", "x" * 41, "line\nbreak", "tab\tname")
    ):
        with pytest.raises(ShopQuantityRejected) as exc:
            store.purchase_shop_item(
                human,
                "star",
                1,
                f"bad-{index}",
                name=name,
                now=NOW,
            )
        assert exc.value.code == "invalid_star_name"
    with pytest.raises(ShopQuantityRejected):
        store.purchase_shop_item(human, "star", 2, "two", name="双子", now=NOW)

    assert len(store.diamond_ledger(human)) == before_ledger
    assert store.list_player_stars(human) == []
    assert store.get_inventory(human) == {"star": 0, "seasonal_star": 0}

    first = store.purchase_shop_item(
        human, "star", 1, "star-1", name="  给妈妈的星  ", now=NOW
    )
    second = store.purchase_shop_item(
        human, "star", 1, "star-2", name="给妈妈的星", now=NOW
    )
    assert first["star"]["name"] == "给妈妈的星"
    assert first["star"]["kind"] == "normal"
    assert first["star"]["season_key"] is None
    assert first["star"]["id"] != second["star"]["id"]
    stars = store.list_player_stars(human)
    assert [star["name"] for star in stars] == ["给妈妈的星", "给妈妈的星"]
    assert store.get_inventory(human) == {"star": 2, "seasonal_star": 0}

    replay = store.purchase_shop_item(
        human, "star", 1, "star-1", name="另一个名字", now=NOW
    )
    assert replay["replayed"] is True
    assert replay["star"]["id"] == first["star"]["id"]
    assert len(store.list_player_stars(human)) == 2
    assert [row["delta"] for row in store.diamond_ledger(human)][-2:] == [
        -300,
        -300,
    ]


def test_seasonal_star_is_monthly_and_persistent(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    november = NOW
    december = datetime(2026, 12, 2, 12, 0, 0, tzinfo=TZ)

    items = catalog(store, human, now=november)
    assert items["seasonal_star"]["season_key"] == "2026-11"
    assert items["seasonal_star"]["available"] is True

    bought = store.purchase_shop_item(
        human, "seasonal_star", 1, "season-11", name="十一月", now=november
    )
    assert bought["star"]["kind"] == "seasonal"
    assert bought["star"]["season_key"] == "2026-11"
    assert bought["star"]["acquired_at"] == "2026-11-02T12:00:00+08:00"
    assert bought["diamonds"] == 500
    assert store.get_inventory(human) == {"star": 0, "seasonal_star": 1}
    assert catalog(store, human, now=november)["seasonal_star"]["available"] is False

    before = store.diamond_ledger(human)
    with pytest.raises(ShopNotAvailable) as exc:
        store.purchase_shop_item(
            human, "seasonal_star", 1, "season-11-again", name="第二颗", now=november
        )
    assert exc.value.code == "seasonal_star_owned"
    assert exc.value.extra == {"season_key": "2026-11"}
    assert store.diamond_ledger(human) == before
    assert len(store.list_player_stars(human)) == 1

    december_items = catalog(store, human, now=december)
    assert december_items["seasonal_star"]["season_key"] == "2026-12"
    assert december_items["seasonal_star"]["available"] is True
    second = store.purchase_shop_item(
        human, "seasonal_star", 1, "season-12", name="十二月", now=december
    )
    assert second["star"]["season_key"] == "2026-12"
    assert second["diamonds"] == 0
    assert store.get_inventory(human) == {"star": 0, "seasonal_star": 2}
    assert [star["season_key"] for star in store.list_player_stars(human)] == [
        "2026-11",
        "2026-12",
    ]


# ----------------------------------------------------------------------
# Legacy / table migration
# ----------------------------------------------------------------------
def test_old_database_gets_new_tables_and_seeds_idempotently(tmp_path) -> None:
    path = tmp_path / "league.db"
    store = GameStore(path, epoch_reason="test")
    make_human(store)
    with sqlite3.connect(path) as connection:
        for table in (
            "inventory_items",
            "player_stars",
            "shop_items",
            "shop_cap_upgrades",
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
            "player_stars",
            "shop_items",
            "shop_cap_upgrades",
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
        ).fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_cap_upgrades"
        ).fetchone()[0] == 5

    reopened.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_items"
        ).fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM shop_cap_upgrades"
        ).fetchone()[0] == 5
    assert reopened.get_inventory("human-1") == {"star": 0, "seasonal_star": 0}
    assert reopened.get_diamond_balance("human-1", now=NOW) == 1000


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

    def test_own_status_has_wallet_inventory_and_stars(self) -> None:
        with self.client() as client:
            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["diamonds"], 1000)
            self.assertEqual(status["diamond_cap"], 1000)
            self.assertEqual(status["diamond_cap_level"], 0)
            self.assertEqual(status["diamond_excess"], 0)
            self.assertEqual(
                status["inventory"],
                {"star": 0, "seasonal_star": 0, "ember": 0},
            )
            self.assertEqual(status["stars"], [])

            response = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "quantity": 1,
                    "name": "  给妈妈的星  ",
                    "request_id": "api-star-1",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            star = response.json()["star"]
            self.assertEqual(star["name"], "给妈妈的星")

            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["diamonds"], 700)
            self.assertEqual(status["diamond_excess"], 0)
            self.assertEqual(status["inventory"]["star"], 1)
            self.assertEqual(
                status["stars"],
                [
                    {
                        "id": star["id"],
                        "name": "给妈妈的星",
                        "kind": "normal",
                        "season_key": None,
                        "acquired_at": "2026-11-02T12:00:00+08:00",
                    }
                ],
            )

    def test_other_views_have_no_private_wallet_inventory_or_stars(self) -> None:
        with self.client() as client:
            client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "name": "只给自己看",
                    "request_id": "private-star",
                },
            )
            with sqlite3.connect(self.game_db_path) as connection:
                channel_player = str(
                    connection.execute(
                        "SELECT player_id FROM channel_players LIMIT 1"
                    ).fetchone()[0]
                )
            private = {
                "diamonds",
                "diamond_cap",
                "diamond_cap_level",
                "diamond_excess",
                "inventory",
                "stars",
            }
            service = client.app.state.game_service
            for user_id in ("owner", channel_player):
                snapshot = service.status_for_user(user_id)
                self.assertIsNotNone(snapshot)
                self.assertFalse(private & set(snapshot))

            public = client.get("/v1/users/owner", headers=auth())
            self.assertEqual(public.status_code, 200, public.text)
            self.assertFalse(private & set(public.json()))
            standings = client.get("/v1/league/standings", headers=auth()).json()
            for row in standings["standings"]:
                self.assertFalse(private & set(row))

    def test_shop_catalog_and_purchase_contract(self) -> None:
        with self.client() as client:
            shop = client.get("/v1/shop", headers=auth())
            self.assertEqual(shop.status_code, 200, shop.text)
            items = {item["id"]: item for item in shop.json()}
            self.assertEqual(
                set(items),
                {"star", "seasonal_star", "ember", "diamond_cap_1"},
            )
            self.assertEqual(items["star"]["kind"], "star")
            self.assertEqual(items["seasonal_star"]["kind"], "seasonal_star")
            self.assertEqual(items["seasonal_star"]["season_key"], "2026-11")
            self.assertEqual(items["diamond_cap_1"]["kind"], "cap")
            self.assertEqual(items["diamond_cap_1"]["required_cap_level"], 0)
            self.assertNotIn("season_key", items["star"])

            missing_name = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "request_id": "missing-name"},
            )
            self.assertEqual(missing_name.status_code, 422, missing_name.text)
            self.assertEqual(
                missing_name.json()["detail"]["code"], "invalid_star_name"
            )

            purchase = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "quantity": 1,
                    "name": "给妈妈的星",
                    "request_id": "shop-20261102-001",
                },
            )
            self.assertEqual(purchase.status_code, 200, purchase.text)
            body = purchase.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["diamonds"], 700)
            self.assertEqual(body["diamond_cap"], 1000)
            self.assertEqual(body["inventory"]["star"], 1)
            self.assertEqual(body["star"]["name"], "给妈妈的星")

            replay = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "quantity": 1,
                    "name": "给妈妈的星",
                    "request_id": "shop-20261102-001",
                },
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertTrue(replay.json()["replayed"])
            self.assertEqual(replay.json()["diamonds"], 700)
            self.assertEqual(replay.json()["star"]["id"], body["star"]["id"])

    def test_purchase_errors_and_seasonal_conflict(self) -> None:
        with self.client() as client:
            unknown = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "nope", "request_id": "unknown"},
            )
            self.assertEqual(unknown.status_code, 404, unknown.text)

            zero = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "quantity": 0,
                    "name": "零",
                    "request_id": "zero",
                },
            )
            self.assertEqual(zero.status_code, 422, zero.text)
            many = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "quantity": 2,
                    "name": "两颗",
                    "request_id": "two",
                },
            )
            self.assertEqual(many.status_code, 422, many.text)
            self.assertEqual(many.json()["detail"]["code"], "quantity_must_be_one")

            first = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "seasonal_star",
                    "quantity": 1,
                    "name": "十一月",
                    "request_id": "season-11",
                },
            )
            self.assertEqual(first.status_code, 200, first.text)
            second = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "seasonal_star",
                    "name": "再来一颗",
                    "request_id": "season-11-again",
                },
            )
            self.assertEqual(second.status_code, 409, second.text)
            self.assertEqual(second.json()["code"], "seasonal_star_owned")
            self.assertEqual(second.json()["season_key"], "2026-11")

            # 1000 - 500 = 500, so a 300 star still works and leaves 200.
            star = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "name": "最后一颗",
                    "request_id": "last-star",
                },
            )
            self.assertEqual(star.status_code, 200, star.text)
            self.assertEqual(star.json()["diamonds"], 200)
            ember = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "request_id": "no-ember-money"},
            )
            self.assertEqual(ember.status_code, 409, ember.text)
            self.assertEqual(ember.json()["code"], "insufficient_diamonds")
            self.assertEqual(ember.json()["balance"], 200)
            self.assertEqual(ember.json()["detail"]["balance"], 200)

    def test_ember_cooldown_is_enforced_over_http(self) -> None:
        with self.client() as client:
            self.credit(client, 2000)
            first = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "request_id": "ember-1"},
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["diamonds"], 2200)
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
            self.credit(client, 1000, key="credit-72")
            second = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "request_id": "ember-3"},
            )
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["inventory"]["ember"], 2)

            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["inventory"]["ember"], 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
