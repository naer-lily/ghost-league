from __future__ import annotations

import json
from datetime import datetime

import pytest

from ghost_league.schedule import TZ

from ghost_league.game.feed import (
    FEED_EMOJIS,
    FEED_TAGS,
    allowed_tags,
    reaction_tag,
)
from ghost_league.game.store import GameStore

WEEK = "2026-10-26"
PREV_WEEK = "2026-10-19"


def make_store(tmp_path) -> GameStore:
    return GameStore(tmp_path / "league.db", epoch_reason="test")


def add_players(store: GameStore, player_ids: list[str], *, week: str = WEEK) -> None:
    for player_id in player_ids:
        store.create_player(
            player_id,
            kind="human" if player_id.endswith("human") else "ai",
            joined_week="2026-10-05",
            now="2026-10-05T00:00:00+08:00",
        )
    store.create_group(
        week,
        tier="Bronze",
        player_ids=player_ids,
        now=f"{week}T00:00:00+08:00",
    )


def add_activity(
    store: GameStore,
    player_id: str,
    *,
    event_id: str,
    seconds: int,
    day: str = WEEK,
) -> dict:
    return store.ingest_activity(
        player_id,
        event_id=event_id,
        seconds=seconds,
        occurred_at=f"{day}T12:00:00+08:00",
        source="local_increment",
        now=f"{day}T12:00:00+08:00",
    )


def event_counts(store: GameStore) -> dict[str, int]:
    with store.transaction() as conn:
        return {
            "events": int(
                conn.execute("SELECT COUNT(*) FROM feed_events").fetchone()[0]
            ),
            "reactions": int(
                conn.execute("SELECT COUNT(*) FROM feed_reactions").fetchone()[0]
            ),
            "tags": int(
                conn.execute("SELECT COUNT(*) FROM feed_tags").fetchone()[0]
            ),
        }


def test_checkin_feed_event_is_written_once(tmp_path) -> None:
    store = make_store(tmp_path)
    players = ["human", "ai-1", "ai-2", "ai-3", "ai-4"]
    add_players(store, players)

    first = add_activity(store, "human", event_id="e-1", seconds=8040)
    assert first["checkin"]["created"] is True
    feed = store.feed_for("human")
    assert len(feed) == 1
    item = feed[0]
    assert item["kind"] == "checkin"
    assert item["day"] == WEEK
    assert item["body"] == "今天点着了 1,340 XP"
    assert item["author"]["id"] == "human"
    assert item["author"]["is_ai"] is False
    assert set(item["author"]) == {"id", "name", "title", "frame", "is_ai"}
    assert 1 <= len(item["reactions"]) <= 3
    assert all(reaction["emoji"] in FEED_EMOJIS for reaction in item["reactions"])
    assert all(tag["tag"] in FEED_TAGS for tag in item["tags"])

    before = event_counts(store)
    replay = add_activity(store, "human", event_id="e-1", seconds=8040)
    assert replay["duplicate"] is True
    assert event_counts(store) == before
    assert len(store.feed_for("human")) == 1

    # A second real increment on the same day keeps the one daily event.
    add_activity(store, "human", event_id="e-2", seconds=600)
    assert event_counts(store) == before
    assert len(store.feed_for("human")) == 1


def test_weekly_events_come_from_settled_results_and_are_idempotent(tmp_path) -> None:
    store = make_store(tmp_path)
    players = [f"p{index:02d}" for index in range(1, 16)]
    add_players(store, players, week=PREV_WEEK)
    for index, player_id in enumerate(players):
        add_activity(
            store,
            player_id,
            event_id=f"{PREV_WEEK}:{player_id}",
            seconds=15000 - index * 500,
            day=PREV_WEEK,
        )

    result = store.settle_week(PREV_WEEK, now="2026-10-26T00:05:00+08:00")
    assert result["already_settled"] is False
    feed = store.feed_for("p01", limit=50)
    kinds = [item["kind"] for item in feed]
    assert "promoted" in kinds
    assert "champion" in kinds
    champion = next(item for item in feed if item["kind"] == "champion")
    assert champion["body"] == "这周在小组拿下第一，2,500 XP"
    promoted = next(item for item in feed if item["kind"] == "promoted")
    assert promoted["body"] == "这周从青铜升到白银"

    before = event_counts(store)
    replay = store.settle_week(PREV_WEEK, now="2026-10-27T00:05:00+08:00")
    assert replay["already_settled"] is True
    assert event_counts(store) == before
    assert [item["id"] for item in store.feed_for("p01", limit=50)] == [
        item["id"] for item in feed
    ]


def test_ai_reactions_are_at_most_three_and_tags_match_event_evidence(tmp_path) -> None:
    store = make_store(tmp_path)
    players = ["human", "ai-1", "ai-2", "ai-3", "ai-4", "ai-5"]
    add_players(store, players)
    add_activity(store, "human", event_id="e-1", seconds=8040)

    with store.transaction() as conn:
        event = conn.execute("SELECT * FROM feed_events").fetchone()
        payload = json.loads(str(event["payload_json"]))
        actors = [
            str(row["actor_id"])
            for row in conn.execute(
                "SELECT actor_id FROM feed_reactions WHERE event_id = ?",
                (int(event["id"]),),
            )
        ]
        tag_rows = conn.execute(
            "SELECT actor_id, tag FROM feed_tags WHERE event_id = ?",
            (int(event["id"]),),
        ).fetchall()
        per_actor_emoji = conn.execute(
            "SELECT actor_id, COUNT(*) FROM feed_reactions WHERE event_id = ? "
            "GROUP BY actor_id",
            (int(event["id"]),),
        ).fetchall()
        per_actor_tag = conn.execute(
            "SELECT actor_id, COUNT(*) FROM feed_tags WHERE event_id = ? "
            "GROUP BY actor_id",
            (int(event["id"]),),
        ).fetchall()

    assert 1 <= len(actors) <= 3
    assert len(set(actors)) == len(actors)
    assert all(int(row[1]) == 1 for row in per_actor_emoji)
    assert all(int(row[1]) == 1 for row in per_actor_tag)
    allowed = set(allowed_tags(str(event["kind"]), payload))
    assert {str(row["tag"]) for row in tag_rows} <= allowed
    assert payload["xp"] == 1340

    # A newly joined AI never backfills reactions for an existing event.
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO players "
            "(id, kind, controller, source_kind, display_name, joined_week, "
            "last_seen_week, created_at, is_active) "
            "VALUES ('ai-new', 'ai', 'ai', 'channel_ingest', 'ai-new', ?, ?, ?, 1)",
            (WEEK, WEEK, "2026-10-26T13:00:00+08:00"),
        )
        conn.execute(
            "INSERT INTO group_members "
            "(group_id, player_id, tier_at_start, is_human, joined_at) "
            "VALUES (1, 'ai-new', 'Bronze', 0, ?)",
            ("2026-10-26T13:00:00+08:00",),
        )
    assert len(store.feed_for("human")[0]["reactions"]) <= 3
    assert event_counts(store) == {
        "events": 1,
        "reactions": len(actors),
        "tags": len(tag_rows),
    }


def test_zero_xp_never_gets_explosive_tags(tmp_path) -> None:
    store = make_store(tmp_path)
    players = ["human", "ai-1", "ai-2", "ai-3"]
    add_players(store, players)
    with store.transaction() as conn:
        store._insert_feed_event_with(
            conn,
            player_id="human",
            kind="champion",
            day=WEEK,
            week_start=WEEK,
            body="这周在小组拿下第一，0 XP",
            payload={"xp": 0, "rank": 1},
            now=datetime(2026, 10, 26, 12, 0, tzinfo=TZ),
        )
    item = store.feed_for("human")[0]
    assert "爆发" not in {tag["tag"] for tag in item["tags"]}
    assert allowed_tags("checkin", {"xp": 0}) == ("慢热",)
    assert allowed_tags("champion", {"xp": 0}) == ()
    for event_id in range(1, 30):
        for actor_id in ("ai-1", "ai-2", "ai-3"):
            assert (
                reaction_tag(
                    event_id,
                    actor_id,
                    kind="checkin",
                    payload={"xp": 0},
                )
                != "爆发"
            )


def test_feed_visibility_is_group_follows_and_self_only(tmp_path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["human", "ai-a"])
    add_players(store, ["outsider", "ai-b"])
    add_activity(store, "human", event_id="mine", seconds=600)
    add_activity(store, "outsider", event_id="theirs", seconds=600)

    mine = store.feed_for("human")
    assert {item["author"]["id"] for item in mine} == {"human"}
    followed = store.feed_for("human", followed_ids=["outsider"])
    assert {item["author"]["id"] for item in followed} == {"human", "outsider"}
    outsider_view = store.feed_for("outsider")
    assert {item["author"]["id"] for item in outsider_view} == {"outsider"}

    lonely = make_store(tmp_path / "lonely")
    lonely.create_player(
        "solo",
        kind="human",
        joined_week=WEEK,
        now=f"{WEEK}T00:00:00+08:00",
    )
    lonely.create_player(
        "other",
        kind="human",
        joined_week=WEEK,
        now=f"{WEEK}T00:00:00+08:00",
    )
    add_activity(lonely, "solo", event_id="solo-event", seconds=600)
    add_activity(lonely, "other", event_id="other-event", seconds=600)
    assert [item["author"]["id"] for item in lonely.feed_for("solo")] == ["solo"]
    assert [
        item["author"]["id"]
        for item in lonely.feed_for("solo", followed_ids=["other"])
    ] == ["solo"]
    assert lonely.feed_for("solo", limit=1)


def test_human_and_ai_feed_items_share_the_same_public_shape(tmp_path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["human", "ai-1", "ai-2", "ai-3"])
    add_activity(store, "human", event_id="human-event", seconds=600)
    add_activity(store, "ai-1", event_id="ai-event", seconds=600)

    feed = store.feed_for("human")
    assert len(feed) == 2
    human_item = next(item for item in feed if not item["author"]["is_ai"])
    ai_item = next(item for item in feed if item["author"]["is_ai"])
    assert set(human_item) == set(ai_item)
    assert set(human_item["author"]) == set(ai_item["author"])
    assert set(human_item["reactions"][0]) == set(ai_item["reactions"][0])
    assert set(human_item["tags"][0]) == set(ai_item["tags"][0])
    assert "kind" not in human_item["author"]

    public = json.dumps(feed, ensure_ascii=False).lower()
    for forbidden in (
        "seconds",
        "minutes",
        "ghost",
        "synthetic",
        "模拟",
        "真人",
        "channel_id",
        "source_ref",
    ):
        assert forbidden not in public


def test_human_reaction_is_idempotent_and_validated(tmp_path) -> None:
    store = make_store(tmp_path)
    add_players(store, ["human", "ai-1", "ai-2", "ai-3"])
    add_activity(store, "human", event_id="e-1", seconds=600)
    item = store.feed_for("human")[0]
    before = next(
        (reaction["count"] for reaction in item["reactions"] if reaction["emoji"] == "盯"),
        0,
    )

    first = store.add_feed_reaction("human", item["id"], "盯")
    second = store.add_feed_reaction("human", item["id"], "盯")
    assert first is not None and second is not None
    mine = next(reaction for reaction in first["reactions"] if reaction["emoji"] == "盯")
    assert mine["mine"] is True
    assert mine["count"] == before + 1
    assert second["reactions"] == first["reactions"]

    with pytest.raises(ValueError):
        store.add_feed_reaction("human", item["id"], "不存在")
    assert store.add_feed_reaction("outsider", item["id"], "盯") is None
