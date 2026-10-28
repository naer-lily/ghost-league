"""API bootstrap is Channel-only: no cache read, no AI before a roster."""

from __future__ import annotations

import ast
import json
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from ghost_league.accounts import AccountsStore
from ghost_league.api import GameService, create_app
from ghost_league.game.roster import ensure_all_groups
from ghost_league.schedule import TZ
from waka_channel import ChannelClient
from waka_channel.cli import sync_roster
from waka_channel.projection import hourly_increments, parse_week_start
from waka_channel.roster import rows_from_cache

USER_TOKEN = "channel-bootstrap-user-token"
CHANNEL_TOKEN = "channel-bootstrap-token"
CHANNEL = "waka"
NOW = datetime(2026, 10, 26, 10, 0, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"


def _auth(token: str = USER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _accounts(base: Path) -> Path:
    api_dir = base / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    accounts_db = api_dir / "accounts.db"
    accounts = AccountsStore(accounts_db, now_fn=lambda: NOW)
    accounts.initialize()
    accounts.create("owner", "You", token=USER_TOKEN)
    return accounts_db


def _make_app(base: Path, *, cache_path: Path | None = None):
    api_dir = base / "api"
    accounts_db = _accounts(base)
    app = create_app(
        game_db_path=base / "league.db",
        cache_path=cache_path or base / "unused-cache" / "cn-978.json",
        avatars_path=base / "avatars.json",
        api_dir=api_dir,
        accounts_db=accounts_db,
        social_db=api_dir / "social.db",
        webhooks_db=api_dir / "webhooks.db",
        start_webhook_worker=False,
        token=USER_TOKEN,
        channel_token=CHANNEL_TOKEN,
        now_fn=lambda: NOW,
        game_now_fn=lambda: NOW,
    )
    return app


def _counts(db_path: Path) -> dict[str, int]:
    tables = (
        "players",
        "groups",
        "group_members",
        "channel_players",
        "channel_week_roster",
        "activity_events",
        "sources",
        "opponent_week_plan",
    )
    with sqlite3.connect(db_path) as connection:
        return {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in tables
        }


def _group_sizes(db_path: Path) -> list[int]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT g.id, COUNT(gm.player_id) AS n FROM groups g "
            "LEFT JOIN group_members gm ON gm.group_id = g.id "
            "GROUP BY g.id ORDER BY n DESC, g.id"
        ).fetchall()
    return [int(row[1]) for row in rows]


def _channel_rows(count: int = 978) -> list[dict]:
    return [
        {
            "id": f"waka-bootstrap-user-{index:04d}",
            "rank": index + 1,
            "seconds": 500_000 - index * 100,
        }
        for index in range(count)
    ]


def _late_service(base: Path) -> tuple[GameService, Path]:
    api_dir = base / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    accounts_db = _accounts(base)
    service = GameService(
        game_db_path=base / "league.db",
        cache_path=base / "unused-cache" / "cn-978.json",
        avatars_path=base / "avatars.json",
        api_dir=api_dir,
        accounts_db=accounts_db,
        channel_token=CHANNEL_TOKEN,
        now_fn=lambda: NOW,
        game_now_fn=lambda: NOW,
    )
    return service, accounts_db


def test_startup_reads_no_cache_and_builds_no_ai_or_groups(tmp_path) -> None:
    api_cache = tmp_path / "unused-cache" / "cn-978.json"
    app = _make_app(tmp_path, cache_path=api_cache)
    with TestClient(app) as client:
        counts = _counts(tmp_path / "league.db")
        assert counts["players"] == 1  # local human only
        assert counts["groups"] == 0
        assert counts["group_members"] == 0
        assert counts["channel_players"] == 0
        assert counts["channel_week_roster"] == 0
        assert counts["activity_events"] == 0
        assert counts["sources"] == 0
        assert counts["opponent_week_plan"] == 0
        assert not api_cache.exists()

        status = client.get("/v1/me/status", headers=_auth())
        assert status.status_code == 200, status.text
        payload = status.json()
        assert payload["group"] is None
        assert payload["group_id"] is None
        assert payload["group_size"] == 0
        assert payload["rank"] is None
        assert payload["xp"] == 0

        standings = client.get("/v1/league/standings", headers=_auth())
        assert standings.status_code == 200, standings.text
        standings_payload = standings.json()
        assert standings_payload["week_start"] == WEEK_START
        assert standings_payload["group"] is None
        assert standings_payload["group_id"] is None
        assert standings_payload["group_size"] == 0
        assert standings_payload["me"] is None
        assert standings_payload["standings"] == []

        history = client.get("/v1/league/history", headers=_auth())
        assert history.status_code == 200
        assert history.json()["results"] == []

        # Even several local humans must stay unplaced until a Channel roster
        # arrives; a read must not create a human-only league.
        app.state.game_service.accounts.create(
            "second-human", "Second", token="second-human-token"
        )
        second = client.get(
            "/v1/me/status",
            headers=_auth("second-human-token"),
        )
        assert second.status_code == 200, second.text
        assert second.json()["group"] is None
        assert second.json()["group_size"] == 0
        assert _counts(tmp_path / "league.db")["groups"] == 0


def test_roster_builds_978_ai_and_late_human_rebalances_without_duplicates(
    tmp_path,
) -> None:
    service, _ = _late_service(tmp_path)
    refs = [f"late-ai-{index:04d}" for index in range(978)]
    result = service.channel_roster(
        CHANNEL, [{"player_ref": ref, "kind": "ai"} for ref in refs]
    )
    assert result["count"] == 978
    store = service.store
    assert store is not None

    ai_groups = ensure_all_groups(store, WEEK_START, now=NOW)
    assert len(ai_groups) == 66
    assert _group_sizes(tmp_path / "league.db") == [15] * 54 + [14] * 12
    assert sum(group["member_count"] for group in ai_groups) == 978

    # The local human arrives after the Channel roster.  The next grouping
    # pass must add it to the existing league, keep 66 groups and never copy
    # an AI into a second group.
    service.initialize()
    account = service.accounts.get("owner")
    assert account is not None
    status = service.status_for(account)
    assert status["group"] is not None
    assert status["group_size"] == 15
    assert status["rank"] is not None
    assert "xp" in status

    groups = ensure_all_groups(store, WEEK_START, now=NOW)
    assert len(groups) == 66
    assert _group_sizes(tmp_path / "league.db") == [15] * 55 + [14] * 11
    human_group = store.group_for_player("owner", WEEK_START)
    assert human_group is not None
    assert len(store.group_members(int(human_group["id"]))) == 15
    with sqlite3.connect(tmp_path / "league.db") as connection:
        players = connection.execute(
            "SELECT kind, COUNT(*) FROM players GROUP BY kind ORDER BY kind"
        ).fetchall()
        memberships = connection.execute(
            "SELECT player_id, COUNT(*) FROM group_members GROUP BY player_id"
        ).fetchall()
    assert players == [("ai", 978), ("human", 1)]
    assert len(memberships) == 979
    assert {int(row[1]) for row in memberships} == {1}


def test_api_source_has_no_legacy_bootstrap_imports() -> None:
    source = Path("ghost_league/api.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").lstrip(".")
            for alias in node.names:
                imported.add((module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add((alias.name, ""))

    assert not any(
        module.endswith("game.projection") or name == "tick"
        for module, name in imported
    )
    assert ("game.roster", "sync_week_roster") not in imported
    assert "sync_week_roster" not in source
    assert "projection.tick" not in source
    assert "waka_channel" not in source
    for module, _ in imported:
        assert not module.endswith("fetch")
        assert not module.endswith("source") and ".source." not in module


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_api(app, port: int):
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("temporary API server exited during startup")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return server, thread
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.05)
    raise RuntimeError("temporary API server did not start")


def _stop_api(server, thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_real_waka_channel_client_end_to_end(tmp_path) -> None:
    channel_cache = tmp_path / "channel" / "cn-978.json"
    channel_cache.parent.mkdir(parents=True)
    channel_cache.write_text(
        json.dumps({"users": _channel_rows()}, ensure_ascii=False),
        encoding="utf-8",
    )
    api_cache = tmp_path / "unused-cache" / "cn-978.json"
    app = _make_app(tmp_path, cache_path=api_cache)
    port = _free_port()
    server, thread = _start_api(app, port)
    base_url = f"http://127.0.0.1:{port}"
    try:
        client = ChannelClient(base_url, token=CHANNEL_TOKEN, channel=CHANNEL)
        roster = sync_roster(client, cache=channel_cache)
        assert roster["count"] == 978
        assert roster["response"]["count"] == 978

        rows = rows_from_cache(channel_cache)
        week = parse_week_start(WEEK_START)
        event = next(
            item
            for item in hourly_increments(
                rows[0].player_ref, week, rows[0].effective_seconds
            )
            if item.seconds > 0 and item.occurred_at <= NOW
        )
        increment = client.post_increment(event)
        assert increment["accepted"] is True
        assert increment["week_xp"] > 0
        assert increment["channel_id"] == CHANNEL

        with urllib.request.urlopen(
            urllib.request.Request(
                f"{base_url}/v1/me/status", headers=_auth()
            ),
            timeout=5,
        ) as response:
            status = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(
            urllib.request.Request(
                f"{base_url}/v1/league/standings", headers=_auth()
            ),
            timeout=5,
        ) as response:
            standings = json.loads(response.read().decode("utf-8"))
    finally:
        _stop_api(server, thread)

    db_path = tmp_path / "league.db"
    with sqlite3.connect(db_path) as connection:
        by_kind = dict(
            connection.execute(
                "SELECT kind, COUNT(*) FROM players GROUP BY kind"
            ).fetchall()
        )
        group_count = int(
            connection.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
        )
        human_group_size = int(
            connection.execute(
                "SELECT COUNT(*) FROM group_members WHERE group_id = "
                "(SELECT group_id FROM group_members WHERE player_id = ?)",
                ("owner",),
            ).fetchone()[0]
        )
        legacy_counts = dict(
            connection.execute(
                "SELECT 'sources', COUNT(*) FROM sources UNION ALL "
                "SELECT 'opponent_week_plan', COUNT(*) FROM opponent_week_plan"
            ).fetchall()
        )

    assert by_kind == {"ai": 978, "human": 1}
    assert group_count == 66
    assert _group_sizes(db_path) == [15] * 55 + [14] * 11
    assert human_group_size == 15
    assert status["group"] is not None
    assert status["group_size"] == 15
    assert isinstance(status["rank"], int)
    assert status["xp"] == 0
    assert len(standings["standings"]) == 15
    assert standings["group_size"] == 15
    assert standings["me"]["rank"] == status["rank"]
    assert legacy_counts == {"sources": 0, "opponent_week_plan": 0}
    assert not api_cache.exists()


def test_bootstrap_only_ensures_owner_and_errors_when_owner_is_missing(
    tmp_path,
) -> None:
    api_dir = tmp_path / "api"
    api_dir.mkdir(parents=True)
    accounts_db = api_dir / "accounts.db"
    accounts = AccountsStore(accounts_db, now_fn=lambda: NOW)
    accounts.initialize()
    accounts.create("other-human", "Other", token="other-token")

    service = GameService(
        game_db_path=tmp_path / "league.db",
        cache_path=tmp_path / "unused-cache" / "cn-978.json",
        avatars_path=tmp_path / "avatars.json",
        api_dir=api_dir,
        accounts_db=accounts_db,
        channel_token=CHANNEL_TOKEN,
        now_fn=lambda: NOW,
        game_now_fn=lambda: NOW,
    )
    try:
        service.initialize()
    except RuntimeError as exc:
        assert "owner account" in str(exc)
    else:  # pragma: no cover - owner must never be fabricated
        raise AssertionError("missing owner must fail startup")

    with sqlite3.connect(tmp_path / "league.db") as connection:
        players = connection.execute(
            "SELECT id FROM players ORDER BY id"
        ).fetchall()
    assert players == []
    assert accounts.get("current-user") is None


def test_bootstrap_does_not_add_other_accounts_to_league(tmp_path) -> None:
    api_dir = tmp_path / "api"
    api_dir.mkdir(parents=True)
    accounts_db = api_dir / "accounts.db"
    accounts = AccountsStore(accounts_db, now_fn=lambda: NOW)
    accounts.initialize()
    accounts.create("owner", "Owner", token=USER_TOKEN)
    accounts.create("second-user", "Second", token="second-user-token")

    service = GameService(
        game_db_path=tmp_path / "league.db",
        cache_path=tmp_path / "unused-cache" / "cn-978.json",
        avatars_path=tmp_path / "avatars.json",
        api_dir=api_dir,
        accounts_db=accounts_db,
        channel_token=CHANNEL_TOKEN,
        now_fn=lambda: NOW,
        game_now_fn=lambda: NOW,
    )
    service.initialize()
    with sqlite3.connect(tmp_path / "league.db") as connection:
        players = connection.execute(
            "SELECT id FROM players ORDER BY id"
        ).fetchall()
        groups = connection.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
    assert players == [("owner",)]
    assert groups == 0
