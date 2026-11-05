from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.game.jobs import run_power_refresh, run_weekly_settlement
from ghost_league.game.store import GameStore, compute_power_snapshot

TOKEN = "power-token"
CHANNEL_TOKEN = "power-channel-token"
CHANNEL = "power-channel"
NOW = datetime(2026, 10, 26, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CURRENT_WEEK = "2026-10-26"
PREV_WEEKS = ("2026-10-19", "2026-10-12", "2026-10-05")
SETTLE_AT = "2026-10-26T00:05:00+08:00"


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_store(tmp_path: Path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def add_players(store: GameStore, player_ids: list[str], *, week: str) -> None:
    for player_id in player_ids:
        store.create_player(
            player_id,
            kind="human",
            joined_week=week,
            now=f"{week}T00:00:00+08:00",
        )


def set_scores(
    store: GameStore, week: str, scores: dict[str, int]
) -> None:
    with store.transaction() as conn:
        for player_id, xp in scores.items():
            conn.execute(
                "INSERT INTO weekly_scores "
                "(week_start, player_id, seconds, xp) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(week_start, player_id) DO UPDATE SET "
                "seconds = excluded.seconds, xp = excluded.xp",
                (week, player_id, xp * 6, xp),
            )


def target_week(store: GameStore, week: str, position: str) -> None:
    """Give ``target`` a known percentile with three distinct XP rows."""

    values = {
        "high": {"target": 30, "a": 20, "b": 10},
        "middle": {"target": 20, "a": 30, "b": 10},
        "low": {"target": 10, "a": 30, "b": 20},
    }[position]
    set_scores(store, week, values)


def test_one_week_is_final_and_not_provisional(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["target", "a", "b"], week=CURRENT_WEEK)
    target_week(store, CURRENT_WEEK, "high")

    result = store.recompute_power(now=f"{CURRENT_WEEK}T12:00:00+08:00")
    player = store.get_player("target")

    assert result["week_start"] == CURRENT_WEEK
    assert result["rated"] == 3
    assert player["power"] == 1667
    assert player["power_percentile"] == 5 / 6
    assert player["power_week"] == CURRENT_WEEK
    assert player["power_provisional"] == 0


def test_two_to_four_week_weights_and_renormalization(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["target", "a", "b"], week=CURRENT_WEEK)
    at = f"{CURRENT_WEEK}T12:00:00+08:00"

    target_week(store, CURRENT_WEEK, "high")
    target_week(store, PREV_WEEKS[0], "middle")
    store.recompute_power(now=at)
    player = store.get_player("target")
    assert player["power"] == 1381
    assert abs(player["power_percentile"] - 29 / 42) < 1e-12

    target_week(store, PREV_WEEKS[1], "low")
    store.recompute_power(now=at)
    player = store.get_player("target")
    assert player["power"] == 1148
    assert abs(player["power_percentile"] - 31 / 54) < 1e-12

    target_week(store, PREV_WEEKS[2], "high")
    store.recompute_power(now=at)
    player = store.get_player("target")
    assert player["power"] == 1200
    assert abs(player["power_percentile"] - 0.6) < 1e-12


def test_tied_xp_uses_mid_rank_percentile(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["p1", "p2", "p3", "p4"], week=CURRENT_WEEK)
    set_scores(store, CURRENT_WEEK, {"p1": 50, "p2": 50, "p3": 50, "p4": 50})

    with store._reader() as conn:
        snapshot = compute_power_snapshot(
            conn, now=f"{CURRENT_WEEK}T12:00:00+08:00"
        )
    assert {row["percentile"] for row in snapshot.values()} == {0.5}
    assert {row["power"] for row in snapshot.values()} == {1000}

    set_scores(store, CURRENT_WEEK, {"p1": 10, "p2": 0, "p3": 10, "p4": 30})
    store.recompute_power(now=f"{CURRENT_WEEK}T12:00:00+08:00")
    player = store.get_player("p1")
    assert player["power"] == 1000
    assert player["power_percentile"] == 0.5


def test_zero_xp_does_not_crash_and_no_data_stays_null(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["z1", "z2", "empty"], week=CURRENT_WEEK)
    set_scores(store, CURRENT_WEEK, {"z1": 0, "z2": 0})

    store.recompute_power(now=f"{CURRENT_WEEK}T12:00:00+08:00")
    for player_id in ("z1", "z2"):
        player = store.get_player(player_id)
        assert player["power"] == 1000
        assert player["power_percentile"] == 0.5
        assert player["power_provisional"] == 0
    empty = store.get_player("empty")
    assert empty["power"] is None
    assert empty["power_percentile"] is None
    assert empty["power_provisional"] == 1


def test_changed_current_week_xp_changes_power(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["target", "a", "b", "c", "d"], week=CURRENT_WEEK)
    set_scores(
        store,
        CURRENT_WEEK,
        {"target": 10, "a": 20, "b": 30, "c": 40, "d": 50},
    )
    store.recompute_power(now=f"{CURRENT_WEEK}T12:00:00+08:00")
    before = store.get_player("target")
    assert before["power"] == 200

    set_scores(
        store,
        CURRENT_WEEK,
        {"target": 60, "a": 20, "b": 30, "c": 40, "d": 50},
    )
    store.recompute_power(now=f"{CURRENT_WEEK}T13:00:00+08:00")
    after = store.get_player("target")
    assert after["power"] == 1800
    assert after["power_updated_at"] == "2026-10-26T13:00:00+08:00"


def test_old_schema_is_migrated_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE players ("
            "id TEXT PRIMARY KEY, "
            "kind TEXT NOT NULL CHECK (kind IN ('human', 'ai')), "
            "controller TEXT NOT NULL CHECK (controller IN ('human', 'ai')), "
            "source_kind TEXT NOT NULL, "
            "source_key_hash TEXT, "
            "display_name TEXT NOT NULL, "
            "joined_week TEXT NOT NULL, "
            "last_seen_week TEXT NOT NULL DEFAULT '', "
            "created_at TEXT NOT NULL, "
            "is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)))"
        )
        conn.execute(
            "INSERT INTO players "
            "(id, kind, controller, source_kind, display_name, joined_week, "
            "last_seen_week, created_at, is_active) VALUES "
            "('old-player', 'human', 'human', 'local_increment', 'Old', "
            "'2026-10-26', '', '2026-10-26T00:00:00+08:00', 1)"
        )
        conn.commit()
    finally:
        conn.close()

    store = GameStore(path, epoch_reason="test")
    old = store.get_player("old-player")
    assert old["power"] is None
    assert old["power_provisional"] == 1
    with store._reader() as reader:
        columns = {
            str(row["name"])
            for row in reader.execute("PRAGMA table_info(players)")
        }
        history = reader.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'player_power_history'"
        ).fetchone()
    assert {
        "power",
        "power_percentile",
        "power_week",
        "power_updated_at",
        "power_provisional",
    } <= columns
    assert history is not None

    # Re-opening the migrated database must be safe and preserve the row.
    GameStore(path, epoch_reason="test")
    assert store.get_player("old-player")["power_provisional"] == 1


def test_power_job_is_repeatable_and_writes_no_history(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["target", "a", "b"], week=CURRENT_WEEK)
    target_week(store, CURRENT_WEEK, "high")
    at = f"{CURRENT_WEEK}T12:00:00+08:00"

    first = run_power_refresh(store.path, at=at)
    after_first = store.get_player("target")
    second = run_power_refresh(store.path, at=at)
    after_second = store.get_player("target")

    assert first == second
    assert after_first["power"] == after_second["power"] == 1667
    assert after_first["power_percentile"] == after_second["power_percentile"]
    assert (
        after_first["power_updated_at"]
        == after_second["power_updated_at"]
        == at
    )
    with store._reader() as conn:
        history_count = conn.execute(
            "SELECT COUNT(*) AS n FROM player_power_history"
        ).fetchone()["n"]
    assert history_count == 0


def test_settlement_writes_final_power_history(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    players = ["p1", "p2", "p3"]
    add_players(store, players, week="2026-10-19")
    store.create_group(
        "2026-10-19",
        tier="Bronze",
        player_ids=players,
        now="2026-10-19T00:00:00+08:00",
    )
    for index, player_id in enumerate(players):
        store.ingest_activity(
            player_id,
            event_id=f"event-{player_id}",
            seconds=9_000 - index * 3_000,
            occurred_at="2026-10-24T12:00:00+08:00",
            source="local_increment",
            now="2026-10-24T12:00:00+08:00",
        )

    settled = store.settle_week("2026-10-19", now=SETTLE_AT)
    assert settled["already_settled"] is False
    with store._reader() as conn:
        rows = {
            str(row["player_id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM player_power_history WHERE week_start = ?",
                ("2026-10-19",),
            )
        }
    assert set(rows) == set(players)
    assert [rows[player]["power"] for player in players] == [1667, 1000, 333]
    assert all(row["weeks_used"] == 1 for row in rows.values())
    expected_raw = {"p1": 1500, "p2": 1000, "p3": 500}
    assert {player: rows[player]["raw_xp"] for player in players} == expected_raw

    replay = store.settle_week("2026-10-19", now="2026-10-26T00:06:00+08:00")
    assert replay["already_settled"] is True
    with store._reader() as conn:
        replayed = {
            str(row["player_id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM player_power_history WHERE week_start = ?",
                ("2026-10-19",),
            )
        }
    assert replayed == rows


def test_status_and_standings_return_power_fields(tmp_path: Path) -> None:
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    clock = {"now": NOW}
    accounts_db = api_dir / "accounts.db"
    accounts = AccountsStore(accounts_db, now_fn=lambda: clock["now"])
    accounts.initialize()
    accounts.create("owner", "You", token=TOKEN)
    app = create_app(
        game_db_path=api_dir / "league.db",
        cache_path=tmp_path / "cache.json",
        avatars_path=api_dir / "avatars.json",
        api_dir=api_dir,
        accounts_db=accounts_db,
        social_db=api_dir / "social.db",
        webhooks_db=api_dir / "webhooks.db",
        start_webhook_worker=False,
        token=TOKEN,
        channel_token=CHANNEL_TOKEN,
        now_fn=lambda: clock["now"],
    )

    with TestClient(app) as client:
        roster = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=auth(CHANNEL_TOKEN),
            json={
                "players": [
                    {"player_ref": f"ai-{index:02d}"}
                    for index in range(14)
                ]
            },
        )
        assert roster.status_code == 200, roster.text

        service = client.app.state.game_service
        store = service.store
        assert store is not None
        group = store.group_for_player("owner", NOW.date())
        assert group is not None
        members = [
            str(row["player_id"])
            for row in store.group_members(int(group["id"]))
        ]
        missing_id = next(
            player_id for player_id in members if player_id != "owner"
        )
        with store.transaction() as conn:
            conn.execute(
                "DELETE FROM weekly_scores WHERE week_start = ? "
                "AND player_id = ?",
                (CURRENT_WEEK, missing_id),
            )
            for index, player_id in enumerate(members):
                if player_id == missing_id:
                    continue
                xp = 1000 if player_id == "owner" else index * 10
                conn.execute(
                    "INSERT INTO weekly_scores "
                    "(week_start, player_id, seconds, xp) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(week_start, player_id) DO UPDATE SET "
                    "xp = excluded.xp",
                    (CURRENT_WEEK, player_id, xp * 6, xp),
                )
        store.recompute_power(now=NOW)

        status_response = client.get("/v1/me/status", headers=auth())
        assert status_response.status_code == 200
        status = status_response.json()
        assert status["power"] is not None
        assert status["power_percentile"] is not None
        assert status["power_week"] == CURRENT_WEEK
        assert status["power_updated_at"] == "2026-10-26T10:00:00+08:00"
        assert status["power_provisional"] is False
        for old_field in ("user_id", "xp", "rank", "gems", "streak", "embers"):
            assert old_field in status

        league_response = client.get("/v1/league/standings", headers=auth())
        assert league_response.status_code == 200
        league = league_response.json()
        assert league["me"]["power"] == status["power"]
        assert len(league["standings"]) == 15
        for row in league["standings"]:
            assert "power" in row
            assert "xp" in row
            assert "display_name" in row
        assert any(row["power"] is None for row in league["standings"])

        ai_id = next(
            row["user_id"]
            for row in league["standings"]
            if row["user_id"] != "owner" and row["power"] is not None
        )
        ai_status = service.status_for_user(ai_id)
        assert ai_status is not None
        assert ai_status["power"] is not None
        assert ai_status["power_week"] == CURRENT_WEEK
        assert ai_status["power_provisional"] is False


def test_settlement_job_still_returns_unchanged_shape(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["p1", "p2"], week="2026-10-19")
    store.create_group(
        "2026-10-19",
        tier="Bronze",
        player_ids=["p1", "p2"],
        now="2026-10-19T00:00:00+08:00",
    )
    for player_id in ("p1", "p2"):
        store.ingest_activity(
            player_id,
            event_id=f"job-{player_id}",
            seconds=6_000,
            occurred_at="2026-10-24T12:00:00+08:00",
            source="local_increment",
            now="2026-10-24T12:00:00+08:00",
        )

    result = run_weekly_settlement(store.path, at=SETTLE_AT)
    assert result["status"] == "settled"
    assert result["week_start"] == "2026-10-19"
    assert len(result["results"]) == 2
