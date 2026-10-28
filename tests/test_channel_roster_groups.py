from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ghost_league.api import GameService, create_app
from ghost_league.game.roster import ensure_all_groups
from ghost_league.game.store import SOURCE_CHANNEL, GameStore
from ghost_league.schedule import TZ

CHANNEL = "roster-channel"
CHANNEL_TOKEN = "channel-roster-test-token"
USER_TOKEN = "channel-roster-user-token"
WEEK_1 = "2026-10-26"
WEEK_2 = "2026-11-02"
WEEK_3 = "2026-11-09"
AT_1 = datetime(2026, 10, 26, 10, 0, 0, tzinfo=TZ)
AT_2 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=TZ)
AT_3 = datetime(2026, 11, 9, 10, 0, 0, tzinfo=TZ)


def make_service(
    tmp_path: Path,
    clock: dict[str, datetime] | None = None,
) -> GameService:
    now = clock if clock is not None else {"now": AT_1}
    api_dir = tmp_path / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    return GameService(
        game_db_path=tmp_path / "league.db",
        cache_path=tmp_path / "unused-cache.json",
        avatars_path=api_dir / "avatars.json",
        api_dir=api_dir,
        accounts_db=api_dir / "accounts.db",
        channel_token=CHANNEL_TOKEN,
        game_now_fn=lambda: now["now"],
    )


def roster(service: GameService, refs: list[str]) -> dict:
    return service.channel_roster(
        CHANNEL,
        [{"player_ref": ref, "kind": "ai"} for ref in refs],
    )


def group_sizes(groups: list[dict]) -> list[int]:
    return sorted((int(group["member_count"]) for group in groups), reverse=True)


def flat_members(groups: list[dict]) -> list[str]:
    return [
        str(member["player_id"])
        for group in groups
        for member in group["members"]
    ]


def membership_counts(store: GameStore, week: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    with store.transaction() as conn:
        for row in conn.execute(
            "SELECT gm.player_id FROM group_members gm "
            "JOIN groups g ON g.id = gm.group_id WHERE g.week_start = ?",
            (week,),
        ):
            counts[str(row["player_id"])] += 1
    return counts


def table_count(store: GameStore, table: str) -> int:
    with store.transaction() as conn:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])


def test_978_channel_ai_form_66_balanced_groups_and_replay_is_idempotent(
    tmp_path,
) -> None:
    service = make_service(tmp_path)
    refs = [f"channel-ai-{index:04d}" for index in range(978)]
    first = roster(service, refs)
    assert first["week_start"] == WEEK_1
    assert first["count"] == first["created"] == 978
    assert first["existing"] == 0

    store = service.store
    assert store is not None
    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(groups) == 66
    assert group_sizes(groups) == [15] * 54 + [14] * 12
    assert all(group["tier"] == "Bronze" for group in groups)
    members = flat_members(groups)
    assert len(members) == 978
    assert len(set(members)) == 978
    counts = membership_counts(store, WEEK_1)
    assert len(counts) == 978
    assert set(counts.values()) == {1}

    # Replaying the same full manifest must not create identities, groups or
    # memberships, and must keep the same player ids.
    replay = roster(service, refs)
    assert replay["week_start"] == WEEK_1
    assert replay["count"] == 978
    assert replay["created"] == 0
    assert replay["existing"] == 978
    assert [row["player_id"] for row in replay["players"]] == [
        row["player_id"] for row in first["players"]
    ]
    replayed_groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(replayed_groups) == 66
    assert group_sizes(replayed_groups) == [15] * 54 + [14] * 12
    assert membership_counts(store, WEEK_1) == counts
    assert table_count(store, "groups") == 66
    assert table_count(store, "players") == 978
    assert table_count(store, "channel_players") == 978
    assert table_count(store, "channel_week_roster") == 978
    assert table_count(store, "opponent_week_plan") == 0
    assert table_count(store, "sources") == 0

    # One local human rebalances the same 978 AI into 55 full groups and
    # eleven 14-person groups, with the human's group full.
    store.ensure_human_player(
        "human-1",
        display_name="Human One",
        joined_week=WEEK_1,
        now=AT_1,
    )
    with_human = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(with_human) == 66
    assert group_sizes(with_human) == [15] * 55 + [14] * 11
    human_group = store.group_for_player("human-1", WEEK_1)
    assert human_group is not None
    human_members = store.group_members(int(human_group["id"]))
    assert len(human_members) == 15
    assert sum(1 for member in human_members if member["kind"] == "human") == 1
    assert sum(1 for member in human_members if member["kind"] == "ai") == 14
    members = flat_members(with_human)
    assert len(members) == 979
    assert len(set(members)) == 979
    assert set(membership_counts(store, WEEK_1).values()) == {1}


def test_1000_channel_ai_plus_one_human_form_67_groups(tmp_path) -> None:
    service = make_service(tmp_path)
    refs = [f"channel-ai-{index:04d}" for index in range(1000)]
    assert roster(service, refs)["created"] == 1000
    store = service.store
    assert store is not None
    store.ensure_human_player(
        "human-1",
        display_name="Human One",
        joined_week=WEEK_1,
        now=AT_1,
    )

    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(groups) == 67
    assert group_sizes(groups) == [15] * 63 + [14] * 4
    human_group = store.group_for_player("human-1", WEEK_1)
    assert human_group is not None
    human_members = store.group_members(int(human_group["id"]))
    assert len(human_members) == 15
    assert sum(1 for member in human_members if member["kind"] == "ai") == 14
    assert len(set(flat_members(groups))) == 1001


def test_roster_endpoint_returns_week_and_replaces_only_current_manifest(
    tmp_path,
) -> None:
    base = tmp_path / "app"
    base.mkdir()
    cache = base / "cache.json"
    cache.write_text(
        json.dumps({"users": [{"id": "legacy-anchor", "seconds": 6000}]}),
        encoding="utf-8",
    )
    app = create_app(
        game_db_path=base / "league.db",
        cache_path=cache,
        avatars_path=base / "avatars.json",
        api_dir=base,
        accounts_db=base / "accounts.db",
        social_db=base / "social.db",
        webhooks_db=base / "webhooks.db",
        start_webhook_worker=False,
        token=USER_TOKEN,
        channel_token=CHANNEL_TOKEN,
        now_fn=lambda: AT_1,
        game_now_fn=lambda: AT_1,
    )
    headers = {"Authorization": f"Bearer {CHANNEL_TOKEN}"}
    players = [
        {"player_ref": "ref-a", "kind": "ai"},
        {"player_ref": "ref-b", "kind": "ai"},
        {"player_ref": "ref-c", "kind": "ai"},
    ]
    with TestClient(app) as client:
        store = app.state.game_service.store
        baseline_players = table_count(store, "players")
        first = client.post(
            f"/v1/channels/{CHANNEL}/roster", headers=headers, json={"players": players}
        )
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["week_start"] == WEEK_1
        assert payload["count"] == 3
        assert payload["created"] == 3
        assert payload["existing"] == 0
        ids = {row["player_ref"]: row["player_id"] for row in payload["players"]}

        first_seen = {
            row["player_ref"]: row["first_seen_at"]
            for row in store.list_channel_week_players(WEEK_1, CHANNEL)
        }
        assert set(first_seen) == {"ref-a", "ref-b", "ref-c"}

        second = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=headers,
            json={
                "players": [
                    {"player_ref": "ref-a", "kind": "ai"},
                    {
                        "player_ref": "ref-b",
                        "kind": "ai",
                        "profile": {"display_name": "Updated B"},
                    },
                ]
            },
        )
        assert second.status_code == 200, second.text
        payload = second.json()
        assert payload["week_start"] == WEEK_1
        assert payload["count"] == 2
        assert payload["created"] == 0
        assert payload["existing"] == 2
        assert {row["player_ref"]: row["player_id"] for row in payload["players"]} == {
            "ref-a": ids["ref-a"],
            "ref-b": ids["ref-b"],
        }
        current = store.list_channel_week_players(WEEK_1, CHANNEL)
        assert {row["player_ref"] for row in current} == {"ref-a", "ref-b"}
        assert {
            row["player_ref"]: row["first_seen_at"] for row in current
        } == {"ref-a": first_seen["ref-a"], "ref-b": first_seen["ref-b"]}

        # The missing ref leaves this week's manifest but keeps its identity
        # and mapping row for history and a later return.
        assert store.get_channel_player(CHANNEL, "ref-c") is not None
        assert table_count(store, "players") == baseline_players + 3
        assert table_count(store, "channel_players") == 3
        with store.transaction() as conn:
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM opponent_week_plan "
                "WHERE player_id IN (?, ?, ?)",
                (ids["ref-a"], ids["ref-b"], ids["ref-c"]),
            ).fetchone()["n"] == 0
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM players WHERE source_kind = ? "
                "AND is_active = 1",
                (SOURCE_CHANNEL,),
            ).fetchone()["n"] == 3


def test_channel_roster_changes_across_weeks_keep_history_and_reuse_ids(
    tmp_path,
) -> None:
    clock = {"now": AT_1}
    service = make_service(tmp_path, clock)
    first_refs = [f"week-ai-{index:02d}" for index in range(40)]
    first = roster(service, first_refs)
    first_ids = {row["player_ref"]: row["player_id"] for row in first["players"]}
    store = service.store
    assert store is not None
    store.ensure_human_player(
        "human-1",
        display_name="Human One",
        joined_week=WEEK_1,
        now=AT_1,
    )
    week_one_groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(week_one_groups) == 3
    assert group_sizes(week_one_groups) == [14, 14, 13]

    removed_refs = first_refs[30:]
    added_refs = [f"new-ai-{index}" for index in range(5)]
    second_refs = first_refs[:30] + added_refs
    clock["now"] = AT_2
    second = roster(service, second_refs)
    second_ids = {row["player_ref"]: row["player_id"] for row in second["players"]}
    assert second["week_start"] == WEEK_2
    assert second["existing"] == 30
    assert second["created"] == 5
    week_two_groups = ensure_all_groups(store, WEEK_2, now=AT_2)
    assert len(week_two_groups) == 3
    assert group_sizes(week_two_groups) == [12, 12, 12]
    week_two_members = set(flat_members(week_two_groups))
    assert len(week_two_members) == 36  # 35 Channel AI + local human
    assert set(second_ids.values()) == week_two_members - {"human-1"}

    old_week_members = set(flat_members(week_one_groups))
    for ref in removed_refs:
        player_id = first_ids[ref]
        assert player_id not in week_two_members
        assert store.group_for_player(player_id, WEEK_2) is None
        assert store.group_for_player(player_id, WEEK_1) is not None
        player = store.get_player(player_id)
        assert player["is_active"] == 1
        assert player["joined_week"] == WEEK_1
        assert player["last_seen_week"] == WEEK_1
    assert len(store.list_channel_week_players(WEEK_1, CHANNEL)) == 40
    assert {
        row["player_ref"] for row in store.list_channel_week_players(WEEK_2, CHANNEL)
    } == set(second_refs)
    assert table_count(store, "opponent_week_plan") == 0

    for ref in added_refs:
        player_id = second_ids[ref]
        player = store.get_player(player_id)
        assert player["joined_week"] == WEEK_2
        assert player["last_seen_week"] == WEEK_2
        assert store.tier_for_player(player_id, WEEK_2) == "Bronze"
        assert player_id in week_two_members

    # Week 3 brings the disappeared refs back and keeps the week-2 newcomers.
    clock["now"] = AT_3
    third_refs = first_refs + added_refs
    third = roster(service, third_refs)
    third_ids = {row["player_ref"]: row["player_id"] for row in third["players"]}
    assert third["created"] == 0
    assert third["existing"] == 45
    for ref in first_refs:
        assert third_ids[ref] == first_ids[ref]
        assert store.get_player(first_ids[ref])["joined_week"] == WEEK_1
    for ref in added_refs:
        assert third_ids[ref] == second_ids[ref]
        assert store.get_player(second_ids[ref])["joined_week"] == WEEK_2
    assert table_count(store, "players") == 46  # 45 Channel AI + local human
    week_three_groups = ensure_all_groups(store, WEEK_3, now=AT_3)
    assert len(week_three_groups) == 4
    assert group_sizes(week_three_groups) == [12, 12, 11, 11]
    week_three_members = set(flat_members(week_three_groups))
    assert week_three_members == set(third_ids.values()) | {"human-1"}
    assert old_week_members <= set(first_ids.values()) | {"human-1"}
    assert table_count(store, "opponent_week_plan") == 0


def test_zero_second_channel_ai_stays_in_group_and_ranks_last(tmp_path) -> None:
    clock = {"now": AT_1}
    service = make_service(tmp_path, clock)
    refs = ["zero-ai", "fast-ai", "slow-ai"]
    result = roster(service, refs)
    ids = {row["player_ref"]: row["player_id"] for row in result["players"]}
    store = service.store
    assert store is not None
    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(groups) == 1
    assert groups[0]["member_count"] == 3
    assert set(flat_members(groups)) == set(ids.values())

    clock["now"] = datetime(2026, 10, 28, 12, 0, 0, tzinfo=TZ)
    service.channel_increment(
        CHANNEL,
        player_ref="fast-ai",
        event_id="fast-event",
        seconds=600,
        occurred_at=datetime(2026, 10, 28, 10, 0, 0, tzinfo=TZ),
    )
    service.channel_increment(
        CHANNEL,
        player_ref="slow-ai",
        event_id="slow-event",
        seconds=300,
        occurred_at=datetime(2026, 10, 28, 11, 0, 0, tzinfo=TZ),
    )
    zero_id = ids["zero-ai"]
    assert store.get_week_score(zero_id, WEEK_1)["seconds"] == 0
    assert store.get_player(zero_id)["is_active"] == 1

    settled = store.settle_week(WEEK_1, now=AT_2)
    ranks = {
        row["player_id"]: row["rank"]
        for row in settled["results"]
        if row["player_id"] in set(ids.values())
    }
    assert ranks[ids["fast-ai"]] == 1
    assert ranks[ids["slow-ai"]] == 2
    assert ranks[zero_id] == 3
    assert store.group_for_player(zero_id, WEEK_1) is not None

    # Absence is expressed only by "not in this week's manifest"; no extra
    # dormant/absent/inactive status column was introduced.
    with store.transaction() as conn:
        columns: set[str] = set()
        for table in ("players", "channel_players", "channel_week_roster"):
            columns.update(
                str(row["name"]).lower()
                for row in conn.execute(f"PRAGMA table_info({table})")
            )
    assert not any(
        token in column
        for column in columns
        for token in ("dormant", "absent", "inactive")
    )


def test_channel_grouping_does_not_require_legacy_source_tables(tmp_path) -> None:
    service = make_service(tmp_path)
    refs = ["independent-ai"]
    roster(service, refs)
    store = service.store
    assert store is not None
    assert table_count(store, "sources") == 0
    assert table_count(store, "opponent_week_plan") == 0
    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    # A lone player is unplaced rather than getting a one-person group.
    assert groups == []
    assert table_count(store, "groups") == 0
    assert table_count(store, "opponent_week_plan") == 0

    second_id = roster(service, ["independent-ai", "second-ai"])["players"][1][
        "player_id"
    ]
    groups = ensure_all_groups(store, WEEK_1, now=AT_1)
    assert len(groups) == 1
    assert groups[0]["member_count"] == 2
    assert second_id in set(flat_members(groups))
    assert table_count(store, "sources") == 0
    assert table_count(store, "opponent_week_plan") == 0
