from __future__ import annotations

import json
import re
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
from ghost_league.game.stars import (
    RARITY_LABELS,
    RARITY_TYPE_POOLS,
    RARITY_WEIGHTS,
    TYPE_LABELS,
    TYPE_PALETTES,
    make_star_visual,
    roll_star_rarity,
    roll_star_type,
)
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


def assert_star_payload(star: dict) -> None:
    assert {
        "id",
        "name",
        "kind",
        "season_key",
        "star_type",
        "type_label",
        "rarity",
        "rarity_label",
        "palette",
        "visual_seed",
        "companion_count",
        "catalog_code",
        "acquired_at",
        "svg_url",
    } <= set(star)
    assert star["star_type"] in TYPE_PALETTES
    assert star["rarity"] in RARITY_WEIGHTS
    assert star["type_label"] == TYPE_LABELS[star["star_type"]]
    assert star["rarity_label"] == RARITY_LABELS[star["rarity"]]
    assert len(star["palette"]) == 3
    assert 0 < star["visual_seed"] < (1 << 63)
    expected = {"binary_star": 1, "triple_star": 2}.get(
        star["star_type"], 0
    )
    assert star["companion_count"] == expected
    assert re.fullmatch(r"GL-\d{4}-[0-9A-F]{8}", star["catalog_code"])
    assert star["svg_url"] == f"/v1/me/stars/{star['id']}/svg"


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
        "diamond_boost_25",
        "diamond_boost_60",
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
def test_normal_stars_are_gacha_with_optional_generated_names(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    store.credit_diamonds(
        human, 1000, "test", idempotency_key="credit-1", now=NOW
    )
    before_ledger = len(store.diamond_ledger(human))

    for index, name in enumerate(
        ("", "   ", "x" * 41, "line\nbreak", "tab\tname")
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
        store.purchase_shop_item(human, "star", 2, "two", now=NOW)

    assert len(store.diamond_ledger(human)) == before_ledger
    assert store.list_player_stars(human) == []
    assert store.get_inventory(human) == {"star": 0, "seasonal_star": 0}

    first = store.purchase_shop_item(
        human, "star", 1, "star-1", now=NOW
    )
    first_star = first["star"]
    assert_star_payload(first_star)
    assert first_star["name"].strip()
    assert len(first_star["name"]) == 2
    assert first_star["kind"] == "normal"
    assert first_star["season_key"] is None

    second = store.purchase_shop_item(
        human, "star", 1, "star-2", name="  给妈妈的星  ", now=NOW
    )
    second_star = second["star"]
    assert_star_payload(second_star)
    assert second_star["name"] == "给妈妈的星"
    assert first_star["id"] != second_star["id"]
    assert first_star["visual_seed"] != second_star["visual_seed"]

    stars = store.list_player_stars(human)
    assert [star["name"] for star in stars] == [
        first_star["name"],
        "给妈妈的星",
    ]
    assert all("svg_url" in star for star in stars)
    assert store.get_inventory(human) == {"star": 2, "seasonal_star": 0}

    replay = store.purchase_shop_item(
        human, "star", 1, "star-1", name="另一个名字", now=NOW
    )
    assert replay["replayed"] is True
    assert replay["star"] == first_star
    assert len(store.list_player_stars(human)) == 2
    assert [row["delta"] for row in store.diamond_ledger(human)][-2:] == [
        -300,
        -300,
    ]


def test_rarity_weights_type_pools_and_companion_counts() -> None:
    assert sum(RARITY_WEIGHTS.values()) == 1.0
    assert set(RARITY_TYPE_POOLS) == set(RARITY_WEIGHTS)
    all_types = [star_type for pool in RARITY_TYPE_POOLS.values() for star_type in pool]
    assert len(all_types) == len(set(all_types))
    assert set(all_types) == set(TYPE_PALETTES)
    assert all(star_type in TYPE_LABELS for star_type in all_types)
    for rarity, pool in RARITY_TYPE_POOLS.items():
        for _ in range(25):
            assert roll_star_type(rarity) in pool
    for _ in range(200):
        rarity = roll_star_rarity()
        assert rarity in RARITY_WEIGHTS
        assert roll_star_type(rarity) in RARITY_TYPE_POOLS[rarity]

    visuals = {}
    for rarity, pool in RARITY_TYPE_POOLS.items():
        for star_type in pool:
            visual = make_star_visual(star_type, rarity)
            assert len(visual["palette"]) == 3
            assert 0 < visual["visual_seed"] < (1 << 63)
            assert visual["companion_count"] == {
                "binary_star": 1,
                "triple_star": 2,
            }.get(star_type, 0)
            visuals[star_type] = visual
    assert len({visual["visual_seed"] for visual in visuals.values()}) == len(
        visuals
    )
    seasonal = make_star_visual("red_dwarf", "common", "2026-12")
    plain = make_star_visual("red_dwarf", "common")
    assert len(seasonal["palette"]) == 3
    assert seasonal["palette"] != plain["palette"]


def test_rarity_roll_boundaries_follow_exact_weights(monkeypatch) -> None:
    import ghost_league.game.stars as stars

    cases = (
        (0, "common"),
        (499_999, "common"),
        (500_000, "uncommon"),
        (799_999, "uncommon"),
        (800_000, "rare"),
        (949_999, "rare"),
        (950_000, "epic"),
        (994_999, "epic"),
        (995_000, "legendary"),
        (999_999, "legendary"),
    )
    for pick, expected in cases:
        monkeypatch.setattr(stars.secrets, "randbelow", lambda _n, p=pick: p)
        assert roll_star_rarity() == expected


def test_legacy_player_stars_are_backfilled_with_unique_catalog_codes(
    tmp_path,
) -> None:
    path = tmp_path / "league.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE player_stars (
                id TEXT PRIMARY KEY,
                player_id TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('normal', 'seasonal')),
                season_key TEXT,
                price_diamonds INTEGER NOT NULL,
                acquired_at TEXT NOT NULL,
                source TEXT NOT NULL,
                UNIQUE (player_id, season_key)
            );
            """
        )
        connection.executemany(
            "INSERT INTO player_stars "
            "(id, player_id, name, kind, season_key, price_diamonds, "
            "acquired_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, 'shop')",
            (
                (
                    "legacy-a",
                    "human-1",
                    "旧普通星",
                    "normal",
                    None,
                    300,
                    "2025-12-01T00:00:00+08:00",
                ),
                (
                    "legacy-b",
                    "human-1",
                    "旧季节星",
                    "seasonal",
                    "2026-01",
                    500,
                    "2026-01-03T00:00:00+08:00",
                ),
                (
                    "legacy-c",
                    "human-2",
                    "另一颗",
                    "normal",
                    None,
                    300,
                    "2026-02-04T00:00:00+08:00",
                ),
            ),
        )
        connection.commit()

    store = GameStore(path, epoch_reason="test")
    stars = store.list_player_stars("human-1")
    assert [star["name"] for star in stars] == ["旧普通星", "旧季节星"]
    for star in stars:
        assert_star_payload(star)
        assert star["catalog_code"]
        assert star["palette"]
    all_stars = store.list_player_stars("human-1") + store.list_player_stars("human-2")
    assert len({star["catalog_code"] for star in all_stars}) == 3
    assert len({star["visual_seed"] for star in all_stars}) == 3

    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(player_stars)")
        }
        assert {
            "star_type",
            "rarity",
            "palette_json",
            "visual_seed",
            "companion_count",
            "catalog_code",
        } <= columns
        assert connection.execute(
            "SELECT COUNT(*) FROM player_stars WHERE star_type IS NULL "
            "OR rarity IS NULL OR palette_json IS NULL "
            "OR visual_seed IS NULL OR companion_count IS NULL "
            "OR catalog_code IS NULL"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_player_stars_catalog_code'"
        ).fetchone()[0] == 1
        first_snapshot = connection.execute(
            "SELECT id, star_type, rarity, palette_json, visual_seed, "
            "companion_count, catalog_code FROM player_stars ORDER BY id"
        ).fetchall()

    store.initialize()
    with sqlite3.connect(path) as connection:
        second_snapshot = connection.execute(
            "SELECT id, star_type, rarity, palette_json, visual_seed, "
            "companion_count, catalog_code FROM player_stars ORDER BY id"
        ).fetchall()
    assert first_snapshot == second_snapshot


def test_seasonal_star_is_monthly_and_persistent(tmp_path) -> None:
    store = make_store(tmp_path)
    human = make_human(store)
    november = NOW
    december = datetime(2026, 12, 2, 12, 0, 0, tzinfo=TZ)

    items = catalog(store, human, now=november)
    assert items["seasonal_star"]["season_key"] == "2026-11"
    assert items["seasonal_star"]["available"] is True

    bought = store.purchase_shop_item(
        human, "seasonal_star", 1, "season-11", now=november
    )
    assert_star_payload(bought["star"])
    assert bought["star"]["name"].strip()
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
    assert_star_payload(second["star"])
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
                    {"player_ref": f"channel-ai-{index:02d}"}
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
            self.assertEqual(len(status["stars"]), 1)
            listed = status["stars"][0]
            self.assertEqual(listed["id"], star["id"])
            self.assertEqual(listed["name"], "给妈妈的星")
            self.assertEqual(listed["kind"], "normal")
            self.assertIsNone(listed["season_key"])
            self.assertEqual(listed["star_type"], star["star_type"])
            self.assertEqual(listed["type_label"], star["type_label"])
            self.assertEqual(listed["rarity"], star["rarity"])
            self.assertEqual(listed["rarity_label"], star["rarity_label"])
            self.assertEqual(listed["palette"], star["palette"])
            self.assertEqual(listed["visual_seed"], star["visual_seed"])
            self.assertEqual(listed["companion_count"], star["companion_count"])
            self.assertEqual(listed["catalog_code"], star["catalog_code"])
            self.assertEqual(listed["svg_url"], star["svg_url"])
            self.assertEqual(
                listed["acquired_at"], "2026-11-02T12:00:00+08:00"
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
                "diamond_boost",
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
                {
                    "star",
                    "seasonal_star",
                    "ember",
                    "diamond_cap_1",
                    "diamond_boost_25",
                    "diamond_boost_60",
                },
            )
            self.assertEqual(items["star"]["kind"], "star")
            self.assertEqual(items["seasonal_star"]["kind"], "seasonal_star")
            self.assertEqual(items["seasonal_star"]["season_key"], "2026-11")
            self.assertEqual(items["diamond_cap_1"]["kind"], "cap")
            self.assertEqual(items["diamond_cap_1"]["required_cap_level"], 0)
            self.assertNotIn("season_key", items["star"])
            for item_id in ("star", "seasonal_star"):
                self.assertTrue(items[item_id]["gacha"])
                self.assertEqual(
                    items[item_id]["rates"],
                    {
                        "common": 0.5,
                        "uncommon": 0.3,
                        "rare": 0.15,
                        "epic": 0.045,
                        "legendary": 0.005,
                    },
                )
                self.assertEqual(
                    set(items[item_id]["types"]),
                    {
                        "red_dwarf",
                        "orange_dwarf",
                        "yellow_dwarf",
                        "white_dwarf",
                        "blue_white_star",
                        "variable_star",
                        "red_giant",
                        "blue_giant",
                        "binary_star",
                        "triple_star",
                        "neutron_star",
                        "pulsar",
                        "black_hole_relic",
                    },
                )

            empty_name = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "star",
                    "name": "",
                    "request_id": "empty-name",
                },
            )
            self.assertEqual(empty_name.status_code, 422, empty_name.text)
            self.assertEqual(
                empty_name.json()["detail"]["code"], "invalid_star_name"
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

    def test_purchase_without_name_generates_private_default(self) -> None:
        with self.client() as client:
            response = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "request_id": "default-name"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            star = response.json()["star"]
            self.assertTrue(star["name"].strip())
            self.assertEqual(len(star["name"]), 2)
            self.assertEqual(star["kind"], "normal")
            self.assertIsNone(star["season_key"])
            self.assertTrue(star["star_type"])
            self.assertTrue(star["type_label"])
            self.assertTrue(star["rarity"])
            self.assertTrue(star["rarity_label"])
            self.assertEqual(len(star["palette"]), 3)
            self.assertGreater(star["visual_seed"], 0)
            self.assertIn(star["companion_count"], (0, 1, 2))
            self.assertRegex(star["catalog_code"], r"^GL-\d{4}-[0-9A-F]{8}$")
            self.assertEqual(
                star["svg_url"], f"/v1/me/stars/{star['id']}/svg"
            )

            replay = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "request_id": "default-name"},
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json()["star"], star)
            self.assertTrue(replay.json()["replayed"])

    def test_star_svg_is_private_stable_and_seed_specific(self) -> None:
        self.accounts.create("other", "Other", token="other-token")
        with self.client() as client:
            first = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "request_id": "svg-first"},
            ).json()["star"]
            second = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "star", "request_id": "svg-second"},
            ).json()["star"]

            own = client.get(first["svg_url"], headers=auth())
            self.assertEqual(own.status_code, 200, own.text)
            self.assertTrue(
                own.headers["content-type"].startswith("image/svg+xml")
            )
            svg = own.content.decode("utf-8")
            self.assertTrue(svg.startswith("<svg"))
            self.assertTrue(svg.endswith("</svg>"))
            self.assertIn('viewBox="0 0 512 512"', svg)
            self.assertNotIn(first["name"], svg)
            lowered = svg.lower()
            self.assertNotIn("<script", lowered)
            self.assertNotIn("<image", lowered)
            self.assertNotIn("href=", lowered)
            without_namespace = svg.replace(
                'xmlns="http://www.w3.org/2000/svg"', ""
            )
            self.assertNotIn("http://", without_namespace)
            self.assertNotIn("https://", without_namespace)

            repeated = client.get(first["svg_url"], headers=auth())
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.content, own.content)

            other_svg = client.get(second["svg_url"], headers=auth())
            self.assertEqual(other_svg.status_code, 200)
            self.assertNotEqual(other_svg.content, own.content)

            other_star = client.post(
                "/v1/shop/purchase",
                headers=auth("other-token"),
                json={"item_id": "star", "request_id": "other-star"},
            ).json()["star"]
            hidden = client.get(other_star["svg_url"], headers=auth())
            self.assertEqual(hidden.status_code, 404, hidden.text)
            missing = client.get(
                "/v1/me/stars/does-not-exist/svg", headers=auth()
            )
            self.assertEqual(missing.status_code, 404, missing.text)

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
                first.json()["cooldown_until"], "2026-11-09T12:00:00+08:00"
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
                body["cooldown_until"], "2026-11-09T12:00:00+08:00"
            )
            self.assertEqual(
                body["detail"]["cooldown_until"], "2026-11-09T12:00:00+08:00"
            )

            with sqlite3.connect(self.game_db_path) as connection:
                assert connection.execute(
                    "SELECT balance FROM ember_balance WHERE player_id = 'owner'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM inventory_items WHERE player_id = 'owner'"
                ).fetchone()[0] == 0

            self.clock["now"] = NOW + timedelta(days=7)
            self.credit(client, 1000, key="credit-7d")
            second = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "ember", "request_id": "ember-3"},
            )
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["inventory"]["ember"], 2)

            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(status["inventory"]["ember"], 2)


    def test_boost_daily_limit_is_enforced_over_http(self) -> None:
        with self.client() as client:
            for index in (1, 2):
                bought = client.post(
                    "/v1/shop/purchase",
                    headers=auth(),
                    json={
                        "item_id": "diamond_boost_25",
                        "request_id": f"daily-{index}",
                    },
                )
                self.assertEqual(bought.status_code, 200, bought.text)
                self.assertEqual(bought.json()["diamonds"], 1000 - index * 20)

            shop = {
                item["id"]: item
                for item in client.get("/v1/shop", headers=auth()).json()
            }
            boost = shop["diamond_boost_25"]
            self.assertEqual(boost["price_diamonds"], 20)
            self.assertEqual(boost["minutes"], 25)
            self.assertEqual(boost["daily_limit"], 2)
            self.assertEqual(boost["bought_today"], 2)
            self.assertEqual(boost["remaining_today"], 0)
            self.assertFalse(boost["available"])
            self.assertEqual(shop["diamond_boost_60"]["price_diamonds"], 40)
            self.assertEqual(shop["diamond_boost_60"]["daily_limit"], 2)

            blocked = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "diamond_boost_25",
                    "request_id": "daily-3",
                },
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            body = blocked.json()
            self.assertEqual(body["code"], "daily_limit_reached")
            self.assertEqual(body["detail"]["code"], "daily_limit_reached")
            self.assertEqual(body["daily_limit"], 2)
            self.assertEqual(body["bought_today"], 2)
            self.assertEqual(body["remaining_today"], 0)
            self.assertEqual(
                client.get("/v1/me/status", headers=auth()).json()["diamonds"],
                960,
            )

            replay = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "diamond_boost_25",
                    "request_id": "daily-1",
                },
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertTrue(replay.json()["replayed"])

            self.clock["now"] = NOW + timedelta(days=1)
            reset = {
                item["id"]: item
                for item in client.get("/v1/shop", headers=auth()).json()
            }["diamond_boost_25"]
            self.assertEqual(reset["bought_today"], 0)
            self.assertEqual(reset["remaining_today"], 2)
            next_day = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "diamond_boost_25",
                    "request_id": "daily-4",
                },
            )
            self.assertEqual(next_day.status_code, 200, next_day.text)
            self.assertEqual(next_day.json()["diamonds"], 940)

    def test_diamond_boost_shop_purchase_status_and_idempotency(self) -> None:
        with self.client() as client:
            service = client.app.state.game_service
            store = service.store
            store.set_game_config("diamond_boost_multiplier", "3", now=NOW)
            store.set_game_config("diamond_boost_25_price", "30", now=NOW)
            store.set_game_config("diamond_boost_25_minutes", "5", now=NOW)

            shop = client.get("/v1/shop", headers=auth()).json()
            items = {item["id"]: item for item in shop}
            boost = items["diamond_boost_25"]
            self.assertEqual(boost["kind"], "boost")
            self.assertEqual(boost["name"], "经验宝 · 5 分钟")
            self.assertEqual(boost["price_diamonds"], 30)
            self.assertEqual(boost["minutes"], 5)
            self.assertEqual(boost["multiplier"], 3)
            self.assertTrue(boost["active"])
            self.assertEqual(items["diamond_boost_60"]["minutes"], 60)

            status = client.get("/v1/me/status", headers=auth()).json()
            self.assertEqual(
                status["diamond_boost"],
                {
                    "expires_at": None,
                    "remaining_seconds": 0,
                    "multiplier": 1,
                },
            )

            response = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "diamond_boost_25",
                    "quantity": 1,
                    "request_id": "boost-1",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["diamonds"], 970)
            self.assertEqual(
                body["diamond_boost"],
                {
                    "expires_at": "2026-11-02T12:05:00+08:00",
                    "remaining_seconds": 300,
                    "multiplier": 3,
                },
            )

            replay = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={
                    "item_id": "diamond_boost_25",
                    "quantity": 1,
                    "request_id": "boost-1",
                },
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertTrue(replay.json()["replayed"])
            self.assertEqual(replay.json()["diamonds"], 970)

            with store.transaction() as conn:
                boosted = store._credit_diamonds_with(
                    conn,
                    player_id="owner",
                    amount=10,
                    reason="rival_reward",
                    ref_type="rival",
                    ref_id="api-normal",
                    idempotency_key="api-normal",
                    now=NOW,
                    boost=True,
                )
            self.assertEqual(boosted["delta"], 30)
            self.credit(client, 100, key="api-admin")
            self.assertEqual(
                client.get("/v1/me/status", headers=auth()).json()["diamonds"],
                1100,
            )
            self.assertEqual(
                [row["delta"] for row in store.diamond_ledger("owner")],
                [-30, 30, 100],
            )

            store.set_game_config(
                "diamond_boost_60_active", "0", now=NOW
            )
            inactive = {
                item["id"]: item
                for item in client.get("/v1/shop", headers=auth()).json()
            }["diamond_boost_60"]
            self.assertFalse(inactive["active"])
            self.assertFalse(inactive["available"])
            blocked = client.post(
                "/v1/shop/purchase",
                headers=auth(),
                json={"item_id": "diamond_boost_60", "request_id": "off"},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertEqual(blocked.json()["code"], "boost_inactive")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
