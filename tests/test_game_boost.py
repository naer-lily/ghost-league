from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ghost_league.game import calendar as cal
from ghost_league.game.rules import ShopNotAvailable, xp_for_seconds
from ghost_league.game.store import GameStore
from ghost_league.schedule import TZ

NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"
BOOST_25 = "diamond_boost_25"
BOOST_60 = "diamond_boost_60"


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def make_human(store: GameStore, player_id: str = "human-1") -> str:
    store.create_player(
        player_id,
        kind="human",
        joined_week=WEEK_START,
        now=NOW,
    )
    return player_id


def catalog(store: GameStore, player_id: str, *, now: datetime = NOW):
    return {item["id"]: item for item in store.shop_catalog(player_id, now=now)}


def normal_credit(
    store: GameStore,
    player_id: str,
    amount: int,
    *,
    key: str,
    now: datetime = NOW,
):
    with store.transaction() as conn:
        return store._credit_diamonds_with(
            conn,
            player_id=player_id,
            amount=amount,
            reason="rival_reward",
            ref_type="rival",
            ref_id=key,
            idempotency_key=key,
            now=now,
            boost=True,
        )


def test_game_config_and_boost_tables_are_seeded_once(tmp_path) -> None:
    store = make_store(tmp_path)
    assert store.list_game_config() == {
        "diamond_boost_25_active": "1",
        "diamond_boost_25_minutes": "25",
        "diamond_boost_25_price": "25",
        "diamond_boost_60_active": "1",
        "diamond_boost_60_minutes": "60",
        "diamond_boost_60_price": "60",
        "diamond_boost_multiplier": "2",
    }
    with sqlite3.connect(tmp_path / "league.db") as connection:
        config_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(game_config)")
        }
        boost_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(diamond_boosts)")
        }
    assert config_columns == {"key", "value", "updated_at"}
    assert boost_columns == {
        "player_id",
        "multiplier",
        "expires_at",
        "updated_at",
    }

    store.set_game_config("diamond_boost_multiplier", "4", now=NOW)
    store.initialize()
    assert store.get_game_config("diamond_boost_multiplier") == "4"


def test_shop_skus_come_from_config(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    items = catalog(store, human)
    assert {BOOST_25, BOOST_60} <= set(items)
    for item_id, price, minutes in (
        (BOOST_25, 25, 25),
        (BOOST_60, 60, 60),
    ):
        item = items[item_id]
        assert item["kind"] == "boost"
        assert item["name"] == f"经验宝 · {minutes} 分钟"
        assert item["price_diamonds"] == price
        assert item["minutes"] == minutes
        assert item["multiplier"] == 2
        assert item["active"] is True
        assert item["available"] is True

    store.set_game_config("diamond_boost_multiplier", "3")
    store.set_game_config("diamond_boost_25_price", "40")
    store.set_game_config("diamond_boost_25_minutes", "5")
    changed = catalog(store, human)[BOOST_25]
    assert changed["name"] == "经验宝 · 5 分钟"
    assert changed["price_diamonds"] == 40
    assert changed["minutes"] == 5
    assert changed["multiplier"] == 3


def test_purchase_uses_configured_price_duration_and_multiplier(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.set_game_config("diamond_boost_multiplier", "3")
    store.set_game_config("diamond_boost_25_price", "40")
    store.set_game_config("diamond_boost_25_minutes", "5")

    result = store.purchase_shop_item(human, BOOST_25, 1, "boost-1", now=NOW)
    assert result["diamonds"] == 960
    assert result["diamond_boost"] == {
        "expires_at": "2026-11-02T12:05:00+08:00",
        "remaining_seconds": 300,
        "multiplier": 3,
    }
    assert store.get_diamond_balance(human, now=NOW) == 960
    assert [row["delta"] for row in store.diamond_ledger(human)] == [-40]

    boosted = normal_credit(store, human, 10, key="boosted-credit")
    assert boosted["delta"] == 30
    assert boosted["balance"] == 990

    admin = store.credit_diamonds(
        human,
        10,
        "test",
        idempotency_key="admin-credit",
        now=NOW,
    )
    assert admin["delta"] == 10
    assert admin["balance"] == 1000


def test_active_boost_extends_from_stored_expiry(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    first = store.purchase_shop_item(human, BOOST_25, 1, "first", now=NOW)
    assert first["diamond_boost"]["expires_at"] == "2026-11-02T12:25:00+08:00"

    later = NOW + timedelta(minutes=10)
    second = store.purchase_shop_item(human, BOOST_60, 1, "second", now=later)
    assert second["diamond_boost"]["expires_at"] == "2026-11-02T13:25:00+08:00"
    assert second["diamond_boost"]["remaining_seconds"] == 75 * 60
    assert store.get_diamond_balance(human, now=later) == 1000 - 25 - 60


def test_expired_boost_does_not_apply_or_extend_old_expiry(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.purchase_shop_item(human, BOOST_25, 1, "first", now=NOW)

    at_expiry = NOW + timedelta(minutes=25)
    assert store.diamond_boost_state(human, now=at_expiry) == {
        "expires_at": None,
        "remaining_seconds": 0,
        "multiplier": 1,
    }
    regular = normal_credit(store, human, 10, key="expired", now=at_expiry)
    assert regular["delta"] == 10

    rebought = store.purchase_shop_item(
        human,
        BOOST_25,
        1,
        "again",
        now=at_expiry + timedelta(minutes=5),
    )
    assert rebought["diamond_boost"]["expires_at"] == (
        "2026-11-02T12:55:00+08:00"
    )


def test_duplicate_requests_do_not_double_charge_or_double_credit(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    first = store.purchase_shop_item(human, BOOST_25, 1, "same", now=NOW)
    replay = store.purchase_shop_item(human, BOOST_25, 1, "same", now=NOW)
    assert replay["replayed"] is True
    assert replay["diamond_boost"] == first["diamond_boost"]
    assert store.get_diamond_balance(human, now=NOW) == 975
    assert [row["delta"] for row in store.diamond_ledger(human)] == [-25]

    boosted = normal_credit(store, human, 10, key="same-credit")
    duplicate = normal_credit(store, human, 10, key="same-credit")
    assert boosted["delta"] == 20
    assert duplicate["duplicate"] is True
    assert duplicate["balance"] == boosted["balance"]
    assert store.get_diamond_balance(human, now=NOW) == 995


def test_boost_quantity_and_inactive_or_invalid_config_fail_closed(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    with pytest.raises(Exception) as quantity_error:
        store.purchase_shop_item(human, BOOST_25, 2, "double", now=NOW)
    assert getattr(quantity_error.value, "code", None) == "quantity_must_be_one"

    store.set_game_config("diamond_boost_60_active", "0", now=NOW)
    items = catalog(store, human)
    assert items[BOOST_60]["active"] is False
    assert items[BOOST_60]["available"] is False
    with pytest.raises(ShopNotAvailable) as inactive:
        store.purchase_shop_item(human, BOOST_60, 1, "inactive", now=NOW)
    assert inactive.value.code == "boost_inactive"

    store.set_game_config("diamond_boost_25_price", "not-a-number", now=NOW)
    assert BOOST_25 not in catalog(store, human)
    with pytest.raises(ShopNotAvailable) as invalid:
        store.purchase_shop_item(human, BOOST_25, 1, "invalid", now=NOW)
    assert invalid.value.code == "boost_config_invalid"
    assert store.get_diamond_balance(human, now=NOW) == 1000

    with sqlite3.connect(tmp_path / "league.db") as connection:
        connection.execute(
            "DELETE FROM game_config WHERE key = 'diamond_boost_multiplier'"
        )
        connection.commit()
    assert BOOST_25 not in catalog(store, human)
    assert BOOST_60 not in catalog(store, human)
    with pytest.raises(ShopNotAvailable):
        store.purchase_shop_item(human, BOOST_60, 1, "missing", now=NOW)


def test_boost_does_not_change_xp(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)

    before = store.ingest_activity(
        human,
        event_id="before",
        seconds=600,
        occurred_at=NOW,
        source="verified",
        now=NOW,
    )
    store.purchase_shop_item(human, BOOST_25, 1, "boost", now=NOW)
    after = store.ingest_activity(
        human,
        event_id="after",
        seconds=600,
        occurred_at=NOW + timedelta(minutes=1),
        source="verified",
        now=NOW + timedelta(minutes=1),
    )

    assert before["week_xp"] == xp_for_seconds(600)
    assert after["week_xp"] == xp_for_seconds(1200)
    score = store.get_week_score(human, cal.week_start(NOW))
    assert score is not None
    assert score["xp"] == xp_for_seconds(1200)
    assert store.diamond_boost_state(human, now=NOW)["multiplier"] == 2
