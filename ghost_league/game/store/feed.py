"""Persistence and deterministic fan-out for the in-group activity feed."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

from .. import calendar as cal
from ..feed import (
    FEED_CHAMPION,
    FEED_CHECKIN,
    FEED_EMOJIS,
    FEED_PROMOTED,
    FEED_TAGS,
    ai_actor_rank,
    champion_body,
    checkin_body,
    promoted_body,
    reaction_emoji,
    reaction_tag,
)
from ..rules import next_tier
from .core import _row_to_dict


class FeedMixin:
    """Write real events once and expose the viewer-scoped feed."""

    # -- event writes --------------------------------------------------
    def _insert_feed_event_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        kind: str,
        day: date | datetime | str,
        week_start: date | datetime | str,
        body: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any] | None:
        day_iso = cal.iso_date(day)
        week_iso = cal.iso_date(cal.week_start(week_start))
        cursor = conn.execute(
            "INSERT OR IGNORE INTO feed_events "
            "(player_id, kind, day, week_start, body, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                player_id,
                kind,
                day_iso,
                week_iso,
                body,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                cal.iso_ts(now),
            ),
        )
        if cursor.rowcount == 0:
            return None
        event_id = int(cursor.lastrowid)
        self._generate_feed_ai_with(conn, event_id, now=now)
        return _row_to_dict(
            conn.execute(
                "SELECT * FROM feed_events WHERE id = ?", (event_id,)
            ).fetchone()
        )

    def _record_checkin_feed_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        day: date | datetime | str,
        week_start: date | datetime | str,
        xp: int,
        source: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        return self._insert_feed_event_with(
            conn,
            player_id=player_id,
            kind=FEED_CHECKIN,
            day=day,
            week_start=week_start,
            body=checkin_body(xp),
            payload={
                "xp": int(xp),
                "checkin_source": str(source),
            },
            now=now,
        )

    def _sync_weekly_feed_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        *,
        now: datetime,
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM weekly_results WHERE week_start = ? "
            "ORDER BY group_id, rank",
            (week_iso,),
        ).fetchall()
        for row in rows:
            player_id = str(row["player_id"])
            tier = str(row["tier"])
            rank = int(row["rank"])
            xp = int(row["xp"])
            if bool(row["promoted"]):
                to_tier = next_tier(tier, promoted=True, demoted=False)
                self._insert_feed_event_with(
                    conn,
                    player_id=player_id,
                    kind=FEED_PROMOTED,
                    day=week_iso,
                    week_start=week_iso,
                    body=promoted_body(tier, to_tier),
                    payload={
                        "xp": xp,
                        "rank": rank,
                        "from_tier": tier,
                        "to_tier": to_tier,
                    },
                    now=now,
                )
            if rank == 1:
                self._insert_feed_event_with(
                    conn,
                    player_id=player_id,
                    kind=FEED_CHAMPION,
                    day=week_iso,
                    week_start=week_iso,
                    body=champion_body(xp),
                    payload={"xp": xp, "rank": rank},
                    now=now,
                )

    def _generate_feed_ai_with(
        self,
        conn: sqlite3.Connection,
        event_id: int,
        *,
        now: datetime,
    ) -> None:
        event = conn.execute(
            "SELECT * FROM feed_events WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return
        author_id = str(event["player_id"])
        group = conn.execute(
            "SELECT gm.group_id FROM group_members gm "
            "JOIN groups g ON g.id = gm.group_id "
            "WHERE gm.player_id = ? AND g.week_start = ? "
            "ORDER BY gm.group_id LIMIT 1",
            (author_id, str(event["week_start"])),
        ).fetchone()
        if group is None:
            return
        candidates = [
            str(row["id"])
            for row in conn.execute(
                "SELECT p.id FROM group_members gm "
                "JOIN players p ON p.id = gm.player_id "
                "WHERE gm.group_id = ? AND p.kind = 'ai' AND p.id != ?",
                (int(group["group_id"]), author_id),
            )
        ]
        ranked = sorted(
            candidates,
            key=lambda actor_id: (-ai_actor_rank(event_id, actor_id), actor_id),
        )[:3]
        if not ranked:
            return
        try:
            payload = json.loads(str(event["payload_json"]))
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        created_at = cal.iso_ts(now)
        for actor_id in ranked:
            conn.execute(
                "INSERT OR IGNORE INTO feed_reactions "
                "(event_id, actor_id, emoji, created_at) VALUES (?, ?, ?, ?)",
                (
                    event_id,
                    actor_id,
                    reaction_emoji(event_id, actor_id),
                    created_at,
                ),
            )
            tag = reaction_tag(
                event_id,
                actor_id,
                kind=str(event["kind"]),
                payload=payload,
            )
            if tag is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO feed_tags "
                    "(event_id, actor_id, tag, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, actor_id, tag, created_at),
                )

    # -- read models ---------------------------------------------------
    @staticmethod
    def _feed_visibility(
        conn: sqlite3.Connection,
        viewer_id: str,
        followed_ids: list[str],
        *,
        include_groups: bool,
    ) -> tuple[str, list[Any]]:
        has_group = bool(
            include_groups
            and conn.execute(
                "SELECT 1 FROM group_members WHERE player_id = ? LIMIT 1",
                (viewer_id,),
            ).fetchone()
        )
        # Without a group the feed is self-only, even when the viewer follows
        # other players.
        if not has_group:
            return "e.player_id = ?", [viewer_id]
        clauses = ["e.player_id = ?"]
        params: list[Any] = [viewer_id]
        followed = sorted({str(item) for item in followed_ids if item})
        if followed:
            placeholders = ", ".join("?" for _ in followed)
            clauses.append(f"e.player_id IN ({placeholders})")
            params.extend(followed)
        clauses.append(
            "EXISTS ("
            " SELECT 1 FROM group_members author_gm"
            " JOIN groups g ON g.id = author_gm.group_id"
            " JOIN group_members viewer_gm ON viewer_gm.group_id = g.id"
            " WHERE author_gm.player_id = e.player_id"
            " AND g.week_start = e.week_start"
            " AND viewer_gm.player_id = ?"
            ")"
        )
        params.append(viewer_id)
        return "(" + " OR ".join(clauses) + ")", params

    def _feed_item_with(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        viewer_id: str,
    ) -> dict[str, Any]:
        event_id = int(row["id"])
        author = conn.execute(
            "SELECT p.id, p.display_name, p.kind, "
            "ct.name AS title_name, cf.name AS frame_name "
            "FROM players p "
            "LEFT JOIN loadouts l ON l.player_id = p.id "
            "LEFT JOIN catalog_titles ct ON ct.id = l.title_id "
            "LEFT JOIN catalog_items cf ON cf.id = l.frame_id "
            "WHERE p.id = ?",
            (str(row["player_id"]),),
        ).fetchone()
        reaction_rows = conn.execute(
            "SELECT emoji, COUNT(*) AS n, "
            "MAX(CASE WHEN actor_id = ? THEN 1 ELSE 0 END) AS mine "
            "FROM feed_reactions WHERE event_id = ? GROUP BY emoji",
            (viewer_id, event_id),
        ).fetchall()
        emoji_order = {emoji: index for index, emoji in enumerate(FEED_EMOJIS)}
        reactions = [
            {
                "emoji": str(item["emoji"]),
                "count": int(item["n"]),
                "mine": bool(item["mine"]),
            }
            for item in reaction_rows
        ]
        reactions.sort(
            key=lambda item: (
                -int(item["count"]),
                emoji_order.get(str(item["emoji"]), len(FEED_EMOJIS)),
                str(item["emoji"]),
            )
        )
        tag_rows = conn.execute(
            "SELECT tag, COUNT(*) AS n FROM feed_tags "
            "WHERE event_id = ? GROUP BY tag",
            (event_id,),
        ).fetchall()
        tag_order = {tag: index for index, tag in enumerate(FEED_TAGS)}
        tags = [
            {"tag": str(item["tag"]), "count": int(item["n"])}
            for item in tag_rows
        ]
        tags.sort(
            key=lambda item: (
                tag_order.get(str(item["tag"]), len(FEED_TAGS)),
                str(item["tag"]),
            )
        )
        return {
            "id": event_id,
            "kind": str(row["kind"]),
            "day": str(row["day"]),
            "body": str(row["body"]),
            "author": {
                "id": str(row["player_id"]),
                "name": (
                    str(author["display_name"]) if author is not None else ""
                ),
                "title": (
                    author["title_name"] if author is not None else None
                ),
                "frame": (
                    author["frame_name"] if author is not None else None
                ),
                "is_ai": bool(
                    author is not None and str(author["kind"]) == "ai"
                ),
            },
            "reactions": reactions,
            "tags": tags,
            "created_at": str(row["created_at"]),
        }

    def feed_for(
        self,
        viewer_id: str,
        *,
        limit: int = 20,
        followed_ids: list[str] | None = None,
        include_groups: bool = True,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        limit = min(limit, 50)
        with self._reader() as conn:
            where, params = self._feed_visibility(
                conn,
                viewer_id,
                list(followed_ids or []),
                include_groups=include_groups,
            )
            rows = conn.execute(
                "SELECT e.* FROM feed_events e "
                f"WHERE {where} "
                "ORDER BY e.created_at DESC, e.id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [self._feed_item_with(conn, row, viewer_id) for row in rows]

    def feed_item_for(
        self,
        viewer_id: str,
        event_id: int,
        *,
        followed_ids: list[str] | None = None,
        include_groups: bool = True,
    ) -> dict[str, Any] | None:
        with self._reader() as conn:
            where, params = self._feed_visibility(
                conn,
                viewer_id,
                list(followed_ids or []),
                include_groups=include_groups,
            )
            row = conn.execute(
                "SELECT e.* FROM feed_events e "
                f"WHERE e.id = ? AND {where}",
                [int(event_id), *params],
            ).fetchone()
            if row is None:
                return None
            return self._feed_item_with(conn, row, viewer_id)

    def add_feed_reaction(
        self,
        viewer_id: str,
        event_id: int,
        emoji: str,
        *,
        followed_ids: list[str] | None = None,
        include_groups: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if emoji not in FEED_EMOJIS:
            raise ValueError(f"unknown emoji: {emoji}")
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        followed = list(followed_ids or [])
        with self.transaction() as conn:
            where, params = self._feed_visibility(
                conn,
                viewer_id,
                followed,
                include_groups=include_groups,
            )
            row = conn.execute(
                "SELECT e.* FROM feed_events e "
                f"WHERE e.id = ? AND {where}",
                [int(event_id), *params],
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "INSERT OR IGNORE INTO feed_reactions "
                "(event_id, actor_id, emoji, created_at) VALUES (?, ?, ?, ?)",
                (int(event_id), viewer_id, emoji, cal.iso_ts(local_now)),
            )
            return self._feed_item_with(conn, row, viewer_id)


__all__ = ["FeedMixin"]
