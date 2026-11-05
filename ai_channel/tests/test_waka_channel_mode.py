"""Tests for the Waka projection transport in ``ai_channel``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_channel.cli import build_parser, serve, tick
from ai_channel.client import AIClient
from ai_channel.store import StateStore
from ai_channel.waka import ghost_user_id, waka_tick
from ghost_league.game.store.channel import _channel_player_id
from waka_channel.identity import player_ref
from waka_channel.projection import tick_increments
from waka_channel.roster import rows_from_cache
from waka_channel.state import ChannelState

AT = "2026-11-02T12:30:00+08:00"
WEEK = "2026-11-02"


class RecordingTransport:
    """Records public API calls; never talks to the network."""

    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.requests: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, Any]]:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        return 200, {"duplicate": self.duplicate, "accepted": True, "week_xp": 1}


def _store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "state" / "ai_accounts.db")
    store.initialize()
    return store


def _cache(tmp_path: Path, users: list[dict[str, Any]]) -> Path:
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps({"source": "wakatime-public", "users": users}),
        encoding="utf-8",
    )
    return path


def _user(source_id: str, seconds: int) -> dict[str, Any]:
    return {
        "id": source_id,
        "name": f"Name {source_id}",
        "seconds": seconds,
        "rank": 1,
    }


def _seed_account(store: StateStore, ref: str, token: str) -> str:
    user_id = ghost_user_id(ref)
    store.save_account(user_id, f"Name {ref[:8]}", token)
    return user_id


def test_ghost_user_id_matches_existing_channel_mapping() -> None:
    for source_id in ("row-a", "9cda48e1-d29d-400b-833e-aea1deb22df2"):
        ref = player_ref(source_id)
        assert ghost_user_id(ref) == _channel_player_id("waka", ref)


def test_waka_tick_sends_projected_events_to_me_increments(
    tmp_path: Path,
) -> None:
    cache_path = _cache(
        tmp_path,
        [_user("row-a", 604_800), _user("row-b", 3_600)],
    )
    rows = rows_from_cache(cache_path)
    store = _store(tmp_path)
    tokens: dict[str, str] = {}
    for row in rows:
        token = f"token-{row.player_ref[:8]}"
        _seed_account(store, row.player_ref, token)
        tokens[row.player_ref] = token

    expected = tick_increments(rows, AT, week_start=WEEK)
    transport = RecordingTransport()
    client = AIClient("http://ghost.test", transport=transport)

    summary = waka_tick(
        client,
        store,
        at=AT,
        cache=cache_path,
        state_path=tmp_path / "waka-state.json",
        out=lambda _line: None,
    )

    assert summary["source"] == "waka"
    assert summary["week_start"] == WEEK
    assert summary["events"] == len(expected.events) > 0
    assert summary["sent"] == len(expected.events)
    assert summary["missing_tokens"] == 0
    assert summary["errors"] == 0
    assert len(transport.requests) == len(expected.events)

    expected_payloads = {
        event.event_id: (
            event.seconds,
            event.occurred_at.isoformat(timespec="seconds"),
            tokens[event.player_ref],
        )
        for event in expected.events
    }
    for request in transport.requests:
        assert request["method"] == "POST"
        assert request["url"] == "http://ghost.test/v1/me/increments"
        assert "/v1/channels/" not in request["url"]
        body = request["body"]
        assert set(body) == {"event_id", "seconds", "occurred_at"}
        seconds, occurred_at, token = expected_payloads[body["event_id"]]
        assert body["seconds"] == seconds
        assert body["occurred_at"] == occurred_at
        assert request["headers"]["Authorization"] == f"Bearer {token}"


def test_missing_token_is_skipped_and_reported_without_creating_account(
    tmp_path: Path,
) -> None:
    cache_path = _cache(tmp_path, [_user("row-without-token", 604_800)])
    store = _store(tmp_path)
    ref = rows_from_cache(cache_path)[0].player_ref
    user_id = ghost_user_id(ref)
    transport = RecordingTransport()
    client = AIClient("http://ghost.test", transport=transport)
    lines: list[str] = []

    summary = waka_tick(
        client,
        store,
        at=AT,
        cache=cache_path,
        state_path=tmp_path / "waka-state.json",
        out=lines.append,
    )

    assert summary["events"] > 0
    assert summary["sent"] == 0
    assert summary["missing_tokens"] == 1
    assert summary["missing"] == [user_id]
    assert summary["missing_player_refs"] == [ref]
    assert summary["skipped"] == 1
    assert transport.requests == []
    assert store.get_account(user_id) is None
    output = "\n".join(lines)
    assert user_id in output
    assert "missing-token" in output
    assert "Bearer" not in output


def test_repeated_waka_tick_sends_no_duplicate_events(tmp_path: Path) -> None:
    cache_path = _cache(tmp_path, [_user("repeat-row", 604_800)])
    store = _store(tmp_path)
    ref = rows_from_cache(cache_path)[0].player_ref
    _seed_account(store, ref, "repeat-token")
    state_path = tmp_path / "waka-state.json"
    transport = RecordingTransport()
    client = AIClient("http://ghost.test", transport=transport)

    first = waka_tick(
        client,
        store,
        at=AT,
        cache=cache_path,
        state_path=state_path,
        out=lambda _line: None,
    )
    first_count = len(transport.requests)
    assert first_count == first["sent"] > 0

    second = waka_tick(
        client,
        store,
        at=AT,
        cache=cache_path,
        state_path=state_path,
        out=lambda _line: None,
    )
    assert second["events"] == 0
    assert second["sent"] == 0
    assert len(transport.requests) == first_count

    state = ChannelState.load(state_path)
    assert state.last_hour(WEEK, ref) == "2026-11-02T11:00:00+08:00"


def test_serve_source_waka_repeats_the_projection_tick(tmp_path: Path) -> None:
    cache_path = _cache(tmp_path, [_user("serve-row", 604_800)])
    store = _store(tmp_path)
    ref = rows_from_cache(cache_path)[0].player_ref
    _seed_account(store, ref, "serve-token")
    transport = RecordingTransport()
    client = AIClient("http://ghost.test", transport=transport)
    lines: list[str] = []

    summary = serve(
        client,
        store,
        interval=3600,
        seconds=900,
        source="waka",
        cache=str(cache_path),
        state_path=str(tmp_path / "waka-state.json"),
        cycles=1,
        at=AT,
        out=lines.append,
    )

    assert summary["source"] == "waka"
    assert summary["cycles"] == 1
    assert summary["events"] > 0
    assert summary["increments"] == len(transport.requests) == summary["events"]
    assert all(
        request["url"] == "http://ghost.test/v1/me/increments"
        for request in transport.requests
    )
    assert "source=waka" in "\n".join(lines)


def test_source_switch_keeps_account_mode_default_and_waka_paths() -> None:
    parser = build_parser()

    default = parser.parse_args(["tick"])
    assert default.source == "accounts"
    assert default.cache == "data/cache/cn-978.json"
    assert default.state == "data/cache/waka-channel-state.json"
    assert default.week_start is None

    waka = parser.parse_args(
        [
            "tick",
            "--source",
            "waka",
            "--cache",
            "cache.json",
            "--state",
            "state.json",
            "--week-start",
            WEEK,
        ]
    )
    assert waka.source == "waka"
    assert waka.cache == "cache.json"
    assert waka.state == "state.json"
    assert waka.week_start == WEEK

    serve_args = parser.parse_args(["serve", "--source", "waka", "--cycles", "1"])
    assert serve_args.source == "waka"
    assert serve_args.cycles == 1

    with pytest.raises(SystemExit):
        parser.parse_args(["tick", "--source", "unknown"])


def test_tick_dispatch_uses_waka_source(tmp_path: Path) -> None:
    cache_path = _cache(tmp_path, [_user("dispatch-row", 604_800)])
    store = _store(tmp_path)
    ref = rows_from_cache(cache_path)[0].player_ref
    _seed_account(store, ref, "dispatch-token")
    transport = RecordingTransport()
    client = AIClient("http://ghost.test", transport=transport)

    summary = tick(
        client,
        store,
        seconds=900,
        source="waka",
        cache=str(cache_path),
        state_path=str(tmp_path / "waka-state.json"),
        at=AT,
        out=lambda _line: None,
    )

    assert summary["source"] == "waka"
    assert summary["increments"] == len(transport.requests) > 0
    assert all(
        request["url"] == "http://ghost.test/v1/me/increments"
        for request in transport.requests
    )
