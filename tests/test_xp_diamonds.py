from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

from ghost_league.game.store import GameStore
from ghost_league.schedule import TZ

ROOT = Path(__file__).resolve().parents[1]
WEEK = "2026-10-26"
NOW = datetime(2026, 11, 2, 10, 0, 0, tzinfo=TZ)


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def make_player(store: GameStore, player_id: str = "xp-player") -> str:
    store.create_player(
        player_id,
        kind="human",
        joined_week=WEEK,
        now=NOW,
    )
    # The production account under repair started at 0, not the default 1000.
    with store.transaction() as conn:
        conn.execute(
            "UPDATE diamond_balance SET balance = 0 WHERE player_id = ?",
            (player_id,),
        )
    return player_id


def ingest(
    store: GameStore,
    player_id: str,
    *,
    event_id: str = "event-1",
    seconds: int = 60,
    now: datetime = NOW,
) -> dict:
    return store.ingest_activity(
        player_id,
        event_id=event_id,
        seconds=seconds,
        occurred_at=now,
        source="local_increment",
        now=now,
    )


def xp_ledger(store: GameStore, player_id: str) -> list[dict]:
    return [
        row
        for row in store.diamond_ledger(player_id)
        if row["reason"] == "xp_milestone"
    ]


def load_backfill_module():
    path = ROOT / "scripts" / "backfill_xp_diamonds.py"
    spec = importlib.util.spec_from_file_location("backfill_xp_diamonds", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ten_xp_credits_one_diamond(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    player_id = make_player(store)

    result = ingest(store, player_id, seconds=60)

    assert result["week_xp"] == 10
    assert store.get_diamond_balance(player_id, now=NOW) == 1
    ledger = xp_ledger(store, player_id)
    assert len(ledger) == 1
    assert ledger[0]["delta"] == 1
    assert ledger[0]["ref_type"] == "lifetime_xp"
    assert ledger[0]["ref_id"] == "1"
    assert ledger[0]["idempotency_key"] == f"xp-diamond:{player_id}:1"


def test_900_seconds_credits_fifteen_diamonds(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    player_id = make_player(store)

    result = ingest(store, player_id, seconds=900)

    assert result["week_xp"] == 150
    assert store.get_diamond_balance(player_id, now=NOW) == 15
    ledger = xp_ledger(store, player_id)
    assert len(ledger) == 1
    assert ledger[0]["delta"] == 15
    assert ledger[0]["ref_id"] == "15"


def test_duplicate_event_does_not_credit_again(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    player_id = make_player(store)

    first = ingest(store, player_id, event_id="same-event")
    replay = ingest(store, player_id, event_id="same-event")

    assert first["accepted"] is True
    assert replay["duplicate"] is True
    assert store.get_diamond_balance(player_id, now=NOW) == 1
    assert len(xp_ledger(store, player_id)) == 1


def test_boost_multiplies_xp_diamonds_without_changing_xp(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    player_id = make_player(store)
    with store.transaction() as conn:
        conn.execute(
            "UPDATE diamond_balance SET balance = 1000 WHERE player_id = ?",
            (player_id,),
        )
    store.purchase_shop_item(
        player_id, "diamond_boost_25", 1, "buy-boost", now=NOW
    )
    before_boost = store.diamond_boost_state(player_id, now=NOW)
    assert before_boost["multiplier"] == 2

    ingest(store, player_id, seconds=60)

    # 10 XP earns 1 base diamond, doubled to 2 while the boost is active.
    assert store.get_diamond_balance(player_id, now=NOW) == 982
    assert store.get_week_score(player_id, NOW)["xp"] == 10
    ledger = xp_ledger(store, player_id)
    assert [row["delta"] for row in ledger] == [2]
    after_boost = store.diamond_boost_state(player_id, now=NOW)
    assert after_boost == before_boost


def test_backfill_credits_105_for_1056_xp_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    player_id = make_player(store)
    with store.transaction() as conn:
        conn.execute(
            "UPDATE diamond_balance SET balance = 1000 WHERE player_id = ?",
            (player_id,),
        )
    store.purchase_shop_item(
        player_id, "diamond_boost_25", 1, "buy-boost", now=NOW
    )
    assert store.diamond_boost_state(player_id, now=NOW)["multiplier"] == 2
    with store.transaction() as conn:
        conn.execute(
            "UPDATE diamond_balance SET balance = 0 WHERE player_id = ?",
            (player_id,),
        )
        conn.execute(
            "INSERT INTO weekly_scores "
            "(week_start, player_id, seconds, xp) VALUES (?, ?, ?, ?)",
            (WEEK, player_id, 6336, 1056),
        )

    backfill = load_backfill_module()

    dry = backfill.backfill_xp_diamonds(store, dry_run=True, now=NOW)
    assert dry["credited"] == 105
    assert store.get_diamond_balance(player_id, now=NOW) == 0
    assert xp_ledger(store, player_id) == []

    first = backfill.backfill_xp_diamonds(store, now=NOW)
    assert first["credited"] == 105
    assert first["players_credited"] == 1
    assert first["results"][0]["status"] == "credited"
    # Historical catch-up is never retroactively boosted.
    assert store.get_diamond_balance(player_id, now=NOW) == 105
    assert store.diamond_boost_state(player_id, now=NOW)["multiplier"] == 2

    second = backfill.backfill_xp_diamonds(store, now=NOW)
    assert second["credited"] == 0
    assert second["players_credited"] == 0
    assert second["results"][0]["status"] == "up_to_date"
    assert store.get_diamond_balance(player_id, now=NOW) == 105

    # The next 150 XP is a new 120 milestone and earns the normal 15 diamonds;
    # the boost bought above has expired by then.
    later = NOW + timedelta(hours=1)
    assert store.diamond_boost_state(player_id, now=later)["multiplier"] == 1
    ingest(
        store,
        player_id,
        event_id="after-backfill",
        seconds=900,
        now=later,
    )
    assert store.get_diamond_balance(player_id, now=later) == 120
    ledger = xp_ledger(store, player_id)
    assert [(row["ref_id"], row["delta"]) for row in ledger] == [
        ("105", 105),
        ("120", 15),
    ]
    assert ledger[0]["idempotency_key"] == (
        f"xp-diamond-backfill-v1:{player_id}:105"
    )
    assert ledger[1]["idempotency_key"] == f"xp-diamond:{player_id}:120"


def test_backfill_skips_ai_players(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.create_player("ai-xp", kind="ai", joined_week=WEEK, now=NOW)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO weekly_scores "
            "(week_start, player_id, seconds, xp) VALUES (?, ?, ?, ?)",
            (WEEK, "ai-xp", 600, 100),
        )

    backfill = load_backfill_module()
    result = backfill.backfill_xp_diamonds(store, now=NOW)

    assert result["credited"] == 0
    assert result["results"][0]["status"] == "skipped_non_human"
    assert store.get_diamond_wallet("ai-xp", now=NOW)["balance"] == 0
    assert store.diamond_ledger("ai-xp") == []
