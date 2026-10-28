from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from ghost_league.schedule import projected_seconds
from ghost_league.source.normalize import normalize_seconds
from waka_channel import cli
from waka_channel.client import ChannelClient, ChannelHTTPError
from waka_channel.identity import CHANNEL_NAMESPACE, player_ref
from waka_channel.projection import (
    hourly_increments,
    make_event_id,
    parse_at,
    tick_increments,
)
from waka_channel.roster import (
    build_roster,
    effective_targets,
    roster_from_rows,
    rows_from_cache,
)
from waka_channel.state import ChannelState

REAL_CACHE = Path("data/cache/cn-978.json")
WEEK = "2026-10-26"
OTHER_WEEK = "2026-11-02"
TOKEN = "test-channel-token"


def cache(users: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": "wakatime-public",
        "country_code": "CN",
        "range": "last_7_days",
        "users": users,
    }


def user(
    source_id: str,
    seconds: int,
    *,
    name: str | None = None,
    avatar_url: str | None = None,
) -> dict[str, Any]:
    return {
        "id": source_id,
        "name": name or f"Real Name {source_id}",
        "avatar_url": (
            avatar_url
            if avatar_url is not None
            else f"https://wakatime.com/photo/{source_id}"
        ),
        "city": "Private City",
        "country": "China",
        "seconds": seconds,
        "rank": 1,
    }


class FakeResponse:
    def __init__(self, payload: Any = None, *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload if payload is not None else {"ok": True}).encode(
            "utf-8"
        )

    def read(self) -> bytes:
        return self._body


class FakeTransport:
    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.requests: list[dict[str, Any]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> FakeResponse:
        self.requests.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body.decode("utf-8")),
            }
        )
        return FakeResponse(status=self.status)


def test_player_ref_is_stable_uuid5_and_channel_scoped() -> None:
    first = player_ref("source-row-1")
    second = player_ref("source-row-1")
    other = player_ref("source-row-2")

    assert first == second
    assert first != other
    parsed = uuid.UUID(first)
    assert parsed.version == 5
    assert parsed == uuid.uuid5(CHANNEL_NAMESPACE, "source-row-1")
    with pytest.raises(ValueError):
        player_ref("  ")
    with pytest.raises(TypeError):
        player_ref(123)  # type: ignore[arg-type]


def test_real_cache_has_978_unique_stable_anonymous_roster_rows() -> None:
    if not REAL_CACHE.exists():
        pytest.skip("real snapshot cache is not present")

    rows = rows_from_cache(REAL_CACHE)
    roster = build_roster(REAL_CACHE)
    refs = [row.player_ref for row in rows]

    assert len(rows) == len(roster) == 978
    assert len(set(refs)) == 978
    assert all(row.kind == "ai" for row in rows)
    assert all(set(player) == {"player_ref", "kind", "profile"} for player in roster)
    assert all(player["kind"] == "ai" for player in roster)
    assert all(player["profile"]["display_name"] for player in roster)
    assert all(player["profile"]["avatar_url"] for player in roster)

    # Public names/avatars survive; private source fields do not.
    cached = json.loads(REAL_CACHE.read_text(encoding="utf-8"))["users"]
    serialized = json.dumps(roster, ensure_ascii=False)
    profile_by_ref = {
        player["player_ref"]: player["profile"] for player in roster
    }
    for row in cached[:20]:
        profile = profile_by_ref[player_ref(row["id"])]
        assert profile["display_name"] == row["name"]
        assert profile["avatar_url"] == row["avatar_url"]
        assert row["city"] not in serialized
    assert "provider" not in serialized
    assert "raw_seconds" not in serialized
    assert "anchor" not in serialized

    # Re-running the same source rows is byte-for-byte stable.
    assert rows_from_cache(REAL_CACHE) == rows
    assert build_roster(REAL_CACHE) == roster


def test_display_name_change_keeps_identity_and_updates_profile() -> None:
    before = rows_from_cache(cache([user("stable-id", 500, name="Before")]))
    after = rows_from_cache(cache([user("stable-id", 500, name="After")]))

    assert before[0].player_ref == after[0].player_ref == player_ref("stable-id")
    assert before[0].effective_seconds == after[0].effective_seconds
    before_profile = roster_from_rows(before)[0]["profile"]
    after_profile = roster_from_rows(after)[0]["profile"]
    assert before_profile["display_name"] == "Before"
    assert after_profile["display_name"] == "After"
    assert before_profile["avatar_url"] == after_profile["avatar_url"]


def test_new_disappearing_and_returning_rows_reuse_identity() -> None:
    a = user("row-a", 100)
    b = user("row-b", 200)
    c = user("row-c", 300)

    first = build_roster(cache([a, b]))
    refs = {row["player_ref"] for row in first}
    assert len(refs) == 2

    added = build_roster(cache([a, b, c]))
    added_refs = {row["player_ref"] for row in added}
    assert added_refs - refs == {player_ref("row-c")}

    disappeared = build_roster(cache([a, c]))
    disappeared_refs = {row["player_ref"] for row in disappeared}
    assert player_ref("row-b") not in disappeared_refs
    assert disappeared_refs == {player_ref("row-a"), player_ref("row-c")}

    returned = build_roster(cache([a, b, c]))
    assert {row["player_ref"] for row in returned} == added_refs
    assert player_ref("row-b") == player_ref("row-b")


def test_zero_second_rows_are_still_roster_players() -> None:
    zero = user("zero-row", 0)
    active = user("active-row", 120)
    roster = build_roster(cache([zero, active]))
    rows = rows_from_cache(cache([zero, active]))

    assert {row["player_ref"] for row in roster} == {
        player_ref("zero-row"),
        player_ref("active-row"),
    }
    assert len(roster) == 2
    assert effective_targets(rows)[player_ref("zero-row")] == 0
    assert [event.seconds for event in hourly_increments(
        player_ref("zero-row"), WEEK, 0
    )] == [0] * 168


def test_hourly_increments_sum_exactly_to_effective_target() -> None:
    ref = player_ref("sum-row")
    for target in (0, 1, 137, 12_345):
        events = hourly_increments(ref, WEEK, target)
        assert len(events) == 168
        assert sum(event.seconds for event in events) == target
        assert all(0 <= event.seconds <= 3600 for event in events)
        assert all(event.player_ref == ref for event in events)
        assert events[0].event_id == f"waka:{ref}:{WEEK}:2026-10-26T00:00:00+08:00"
        assert events[-1].event_id == f"waka:{ref}:{WEEK}:2026-11-01T23:00:00+08:00"
        assert events[-1].occurred_at.isoformat(timespec="seconds") == (
            "2026-11-02T00:00:00+08:00"
        )


def test_tick_only_emits_completed_hours_and_repeated_tick_is_empty() -> None:
    ref = player_ref("tick-row")
    rows = [{"player_ref": ref, "effective_seconds": 604_800}]

    before_any_hour = tick_increments(rows, "2026-10-26T00:30:00+08:00")
    assert before_any_hour.events == ()

    first = tick_increments(rows, "2026-10-26T02:30:00+08:00")
    assert {event.hour_start.isoformat(timespec="seconds") for event in first.events} == {
        "2026-10-26T00:00:00+08:00",
        "2026-10-26T01:00:00+08:00",
    }
    assert all(event.occurred_at <= first.boundary for event in first.events)
    assert all(event.seconds > 0 for event in first.events)
    assert all(event.event_id.startswith(f"waka:{ref}:{WEEK}:") for event in first.events)

    state = ChannelState()
    state.mark(WEEK, first.next_hours)
    repeated = tick_increments(
        rows,
        "2026-10-26T02:30:00+08:00",
        cursors=state.cursors(WEEK),
    )
    assert repeated.events == ()
    assert repeated.next_hours == {}

    later = tick_increments(
        rows,
        "2026-10-26T04:30:00+08:00",
        cursors=state.cursors(WEEK),
    )
    assert {event.hour_start.isoformat(timespec="seconds") for event in later.events} == {
        "2026-10-26T02:00:00+08:00",
        "2026-10-26T03:00:00+08:00",
    }
    assert set(event.event_id for event in later.events).isdisjoint(
        event.event_id for event in first.events
    )


def test_full_week_tick_sums_to_target_with_last_hour_remainder() -> None:
    target = 23_456
    ref = player_ref("full-week-row")
    row = {"player_ref": ref, "effective_seconds": target}
    plan = tick_increments(
        [row],
        "2026-11-02T00:00:00+08:00",
        week_start=WEEK,
    )

    assert len(plan.events) <= 168
    assert sum(event.seconds for event in plan.events) == target
    assert sum(event.seconds for event in plan.events) == projected_seconds(
        ref, WEEK, target, parse_at("2026-11-02T00:00:00+08:00")
    )
    assert plan.next_hours[ref] == "2026-11-01T23:00:00+08:00"


def test_fake_http_receives_roster_and_increment_with_token_and_event_id() -> None:
    transport = FakeTransport()
    client = ChannelClient(
        "http://ghost.test:8095",
        token=TOKEN,
        post_fn=transport,
    )
    rows = rows_from_cache(cache([user("http-a", 900), user("http-b", 0)]))
    roster = roster_from_rows(rows)

    client.post_roster(roster)
    roster_request = transport.requests[-1]
    assert roster_request["url"] == "http://ghost.test:8095/v1/channels/waka/roster"
    assert roster_request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert set(roster_request["body"]) == {"players"}
    assert len(roster_request["body"]["players"]) == 2
    assert all(
        set(player) == {"player_ref", "kind", "profile"}
        for player in roster_request["body"]["players"]
    )
    sent_profiles = [
        player["profile"] for player in roster_request["body"]["players"]
    ]
    assert all(
        profile["display_name"].startswith("Real Name")
        for profile in sent_profiles
    )
    assert all(
        profile["avatar_url"].startswith("https://")
        for profile in sent_profiles
    )
    assert "raw_seconds" not in json.dumps(roster_request["body"])

    event = hourly_increments(rows[0].player_ref, WEEK, rows[0].effective_seconds)[0]
    client.post_increment(event)
    increment_request = transport.requests[-1]
    assert increment_request["url"] == (
        "http://ghost.test:8095/v1/channels/waka/increments"
    )
    assert increment_request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert set(increment_request["body"]) == {
        "player_ref",
        "event_id",
        "seconds",
        "occurred_at",
    }
    assert increment_request["body"]["event_id"] == make_event_id(
        event.player_ref, WEEK, event.hour_start
    )
    assert increment_request["body"]["event_id"].startswith(
        f"waka:{event.player_ref}:{WEEK}:"
    )
    assert increment_request["body"]["seconds"] == event.seconds
    assert increment_request["body"]["occurred_at"] == "2026-10-26T01:00:00+08:00"
    assert "provider" not in json.dumps(increment_request["body"])


def test_http_errors_are_exposed_not_swallowed() -> None:
    transport = FakeTransport(status=503)
    client = ChannelClient("http://ghost.test", token=TOKEN, post_fn=transport)
    event = hourly_increments(player_ref("failure-row"), WEEK, 600)[0]

    with pytest.raises(ChannelHTTPError) as raised:
        client.post_increment(event)
    assert raised.value.status == 503
    assert "http://ghost.test/v1/channels/waka/increments" in str(raised.value)

    with pytest.raises(ValueError):
        ChannelClient("http://ghost.test", token=None, post_fn=transport).post_roster(
            [{"player_ref": "x", "kind": "ai"}]
        )


def test_cli_tick_persists_cursor_and_does_not_resend_same_hour(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(cache([user("cli-row", 604_800), user("cli-zero", 0)])),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    transport = FakeTransport()
    client = ChannelClient("http://ghost.test", token=TOKEN, post_fn=transport)

    first = cli.tick(
        client,
        at="2026-10-26T02:30:00+08:00",
        cache=cache_path,
        state_path=state_path,
    )
    assert first["week_start"] == WEEK
    first_count = len(transport.requests)
    assert first_count == first["events"] > 0
    assert first["seconds"] > 0

    second = cli.tick(
        client,
        at="2026-10-26T02:30:00+08:00",
        cache=cache_path,
        state_path=state_path,
    )
    assert second["events"] == 0
    assert len(transport.requests) == first_count

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert saved["weeks"][WEEK][player_ref("cli-row")] == "2026-10-26T01:00:00+08:00"

    later = cli.tick(
        client,
        at="2026-10-26T03:30:00+08:00",
        cache=cache_path,
        state_path=state_path,
    )
    assert later["events"] == 1
    assert len(transport.requests) == first_count + 1


def test_vanished_rows_are_not_ticked_but_regression_reuses_ref() -> None:
    a = user("stay-row", 604_800)
    b = user("gone-row", 604_800)
    rows_with_both = rows_from_cache(cache([a, b]))
    rows_without_b = rows_from_cache(cache([a]))
    ref_b = player_ref("gone-row")

    plan = tick_increments(rows_without_b, "2026-10-26T03:30:00+08:00")
    assert ref_b not in {event.player_ref for event in plan.events}

    returned = rows_from_cache(cache([a, b]))
    assert {row.player_ref for row in returned} == {
        row.player_ref for row in rows_with_both
    }
    assert ref_b in {event.player_ref for event in tick_increments(
        returned, "2026-10-26T03:30:00+08:00"
    ).events}


def test_missing_profile_fields_fall_back_to_stable_anonymous_name() -> None:
    rows = rows_from_cache(
        cache([{"id": "minimal-row", "seconds": 100, "rank": 1}])
    )
    profile = roster_from_rows(rows)[0]["profile"]

    code = rows[0].player_ref.replace("-", "")[:8].upper()
    assert profile == {"display_name": f"Waka-{code}"}
    assert rows_from_cache(
        cache([{"id": "minimal-row", "seconds": 100, "rank": 1}])
    ) == rows


def test_synthetic_cache_normalization_matches_shared_rule() -> None:
    rows = rows_from_cache(cache([user("n-a", 0), user("n-b", 100), user("n-c", 900)]))
    expected = normalize_seconds([0, 100, 900])
    assert [row.raw_seconds for row in rows] == expected["raw_seconds"]
    assert [row.effective_seconds for row in rows] == expected["effective_seconds"]


def test_channel_imports_are_independent_and_ghost_has_no_reverse_import() -> None:
    allowed = {
        "ghost_league.schedule",
        "ghost_league.source.normalize",
    }
    for path in Path("waka_channel").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            for module in modules:
                if module.startswith("ghost_league"):
                    assert module in allowed, (path, module)
                assert not module.startswith("ghost_league.game")
                assert not module.startswith("ghost_league.channels")
                assert module not in {"ghost_league.fetch"}

    for folder in ("ghost_league/game", "ghost_league/channels"):
        for path in Path(folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "waka_channel" not in text, path
