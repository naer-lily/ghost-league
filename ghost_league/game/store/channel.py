"""Channel player mappings, events, and weekly rosters."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from .. import calendar as cal
from .core import SOURCE_CHANNEL


def _channel_player_id(channel_id: str, player_ref: str) -> str:
    digest = hashlib.sha256(
        b"ghost-channel-player-v1\x00"
        + channel_id.encode("utf-8")
        + b"\x00"
        + player_ref.encode("utf-8")
    ).hexdigest()
    return f"ch-{digest}"


class ChannelMixin:
    """Stable Ghost identities and weekly manifests for Channels."""

    @staticmethod
    def _channel_player_id(channel_id: str, player_ref: str) -> str:
        return _channel_player_id(channel_id, player_ref)

    @staticmethod
    def _channel_profile_json(profile: dict[str, Any] | None) -> str:
        return json.dumps(
            profile or {},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _decode_channel_profile(raw: object) -> dict[str, Any]:
        try:
            profile = json.loads(str(raw))
        except (TypeError, ValueError):
            return {}
        return profile if isinstance(profile, dict) else {}

    @staticmethod
    def _channel_display_name(
        *,
        channel_id: str,
        player_ref: str,
        kind: str,
        profile: dict[str, Any] | None,
    ) -> str:
        display_name = (profile or {}).get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
        digest = _channel_player_id(channel_id, player_ref).removeprefix("ch-")
        if kind == "ai":
            return f"AI-{digest[:8].upper()}"
        return f"Player-{digest[:8]}"

    def upsert_channel_player(
        self,
        channel_id: str,
        player_ref: str,
        *,
        kind: str,
        profile: dict[str, Any] | None = None,
        joined_week: date | datetime | str | None = None,
        now: datetime | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create or refresh the stable Ghost player for one channel ref.

        The mapping key is ``(channel_id, player_ref)``; the internal
        ``player_id`` is derived once and never changes.  ``profile`` is a
        display snapshot stored beside the mapping, not a scoring input.
        """

        if not isinstance(channel_id, str) or not channel_id:
            raise ValueError("channel_id must be a non-empty string")
        if not isinstance(player_ref, str) or not player_ref:
            raise ValueError("player_ref must be a non-empty string")
        if kind not in {"human", "ai"}:
            raise ValueError("kind must be human or ai")
        if profile is not None and not isinstance(profile, dict):
            raise ValueError("profile must be an object or null")
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        joined = cal.iso_date(
            cal.week_start(joined_week)
            if joined_week is not None
            else cal.week_start(local_now)
        )
        if conn is not None:
            return self._upsert_channel_player_with(
                conn,
                channel_id=channel_id,
                player_ref=player_ref,
                kind=kind,
                profile=profile,
                joined_week=joined,
                now=local_now,
            )
        with self.transaction() as tx:
            return self._upsert_channel_player_with(
                tx,
                channel_id=channel_id,
                player_ref=player_ref,
                kind=kind,
                profile=profile,
                joined_week=joined,
                now=local_now,
            )

    def _upsert_channel_player_with(
        self,
        conn: sqlite3.Connection,
        *,
        channel_id: str,
        player_ref: str,
        kind: str,
        profile: dict[str, Any] | None,
        joined_week: str,
        now: datetime,
    ) -> tuple[dict[str, Any], bool]:
        updated_at = cal.iso_ts(now)
        profile_json = self._channel_profile_json(profile)
        display_name = self._channel_display_name(
            channel_id=channel_id,
            player_ref=player_ref,
            kind=kind,
            profile=profile,
        )
        controller = "human" if kind == "human" else "ai"
        mapping = conn.execute(
            "SELECT * FROM channel_players "
            "WHERE channel_id = ? AND player_ref = ?",
            (channel_id, player_ref),
        ).fetchone()
        created = mapping is None
        if mapping is None:
            player_id = self._channel_player_id(channel_id, player_ref)
            conn.execute(
                "INSERT INTO players "
                "(id, kind, controller, source_kind, source_key_hash, "
                "display_name, joined_week, last_seen_week, created_at, is_active) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 1) "
                "ON CONFLICT(id) DO NOTHING",
                (
                    player_id,
                    kind,
                    controller,
                    SOURCE_CHANNEL,
                    display_name,
                    joined_week,
                    joined_week,
                    updated_at,
                ),
            )
            conn.execute(
                "INSERT INTO channel_players "
                "(channel_id, player_ref, player_id, kind, profile_json, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    channel_id,
                    player_ref,
                    player_id,
                    kind,
                    profile_json,
                    updated_at,
                    updated_at,
                ),
            )
        else:
            player_id = str(mapping["player_id"])
            conn.execute(
                "INSERT INTO players "
                "(id, kind, controller, source_kind, source_key_hash, "
                "display_name, joined_week, last_seen_week, created_at, is_active) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 1) "
                "ON CONFLICT(id) DO NOTHING",
                (
                    player_id,
                    kind,
                    controller,
                    SOURCE_CHANNEL,
                    display_name,
                    joined_week,
                    joined_week,
                    updated_at,
                ),
            )
            conn.execute(
                "UPDATE players SET kind = ?, controller = ?, display_name = ?, "
                "last_seen_week = ?, is_active = 1 WHERE id = ?",
                (kind, controller, display_name, joined_week, player_id),
            )
            conn.execute(
                "UPDATE channel_players SET kind = ?, profile_json = ?, "
                "updated_at = ? WHERE channel_id = ? AND player_ref = ?",
                (kind, profile_json, updated_at, channel_id, player_ref),
            )
        return self._get_player_with(conn, player_id), created

    def get_channel_player(
        self, channel_id: str, player_ref: str
    ) -> dict[str, Any] | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM channel_players "
                "WHERE channel_id = ? AND player_ref = ?",
                (channel_id, player_ref),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["profile"] = self._decode_channel_profile(
                item.pop("profile_json")
            )
            return item

    def list_channel_players(self, channel_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM channel_players WHERE channel_id = ? "
                "ORDER BY player_ref",
                (channel_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["profile"] = self._decode_channel_profile(
                item.pop("profile_json")
            )
            items.append(item)
        return items

    def channel_profile_for_player(self, player_id: str) -> dict[str, Any]:
        """Return only the display snapshot stored for one Channel player."""

        with self._reader() as conn:
            row = conn.execute(
                "SELECT profile_json FROM channel_players WHERE player_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (player_id,),
            ).fetchone()
        if row is None:
            return {}
        return self._decode_channel_profile(row["profile_json"])

    def channel_profiles_for_players(
        self, player_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        """Return the latest display snapshot for each Channel player id."""

        ids = sorted({str(player_id) for player_id in player_ids if player_id})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT player_id, profile_json FROM channel_players "
                f"WHERE player_id IN ({placeholders}) "
                "ORDER BY updated_at ASC",
                ids,
            ).fetchall()
        profiles: dict[str, dict[str, Any]] = {}
        for row in rows:
            profiles[str(row["player_id"])] = self._decode_channel_profile(
                row["profile_json"]
            )
        return profiles

    def replace_channel_week_roster(
        self,
        channel_id: str,
        week: date | datetime | str,
        players: list[dict[str, Any]],
        *,
        now: datetime | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """Replace one Channel's full weekly manifest.

        The manifest is authoritative for ``(week_start, channel_id)``: refs
        missing from this call are removed from that week only.  Player
        identities and every earlier week stay untouched.  Replaying the same
        manifest keeps each row's original ``first_seen_at``.
        """

        if not isinstance(channel_id, str) or not channel_id:
            raise ValueError("channel_id must be a non-empty string")
        week_iso = cal.iso_date(cal.week_start(week))
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        first_seen_at = cal.iso_ts(local_now)
        entries: list[tuple[str, str, str, str, str]] = []
        refs: set[str] = set()
        for item in players:
            player_ref = str(item.get("player_ref") or "")
            player_id = str(item.get("player_id") or "")
            if not player_ref or not player_id:
                raise ValueError("roster entries need player_ref and player_id")
            if player_ref in refs:
                continue
            refs.add(player_ref)
            entries.append(
                (week_iso, channel_id, player_ref, player_id, first_seen_at)
            )
        if conn is not None:
            return self._replace_channel_week_roster_with(
                conn, week_iso, channel_id, entries, refs
            )
        with self.transaction() as tx:
            return self._replace_channel_week_roster_with(
                tx, week_iso, channel_id, entries, refs
            )

    def _replace_channel_week_roster_with(
        self,
        conn: sqlite3.Connection,
        week_iso: str,
        channel_id: str,
        entries: list[tuple[str, str, str, str, str]],
        refs: set[str],
    ) -> list[dict[str, Any]]:
        if refs:
            placeholders = ",".join("?" for _ in refs)
            conn.execute(
                "DELETE FROM channel_week_roster WHERE week_start = ? "
                f"AND channel_id = ? AND player_ref NOT IN ({placeholders})",
                (week_iso, channel_id, *sorted(refs)),
            )
        else:
            conn.execute(
                "DELETE FROM channel_week_roster "
                "WHERE week_start = ? AND channel_id = ?",
                (week_iso, channel_id),
            )
        conn.executemany(
            "INSERT INTO channel_week_roster "
            "(week_start, channel_id, player_ref, player_id, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(week_start, channel_id, player_ref) DO UPDATE SET "
            "player_id = excluded.player_id",
            entries,
        )
        return self._list_channel_week_players_with(conn, week_iso, channel_id)

    @staticmethod
    def _list_channel_week_players_with(
        conn: sqlite3.Connection,
        week_iso: str,
        channel_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT r.week_start, r.channel_id, r.player_ref, r.player_id, "
            "r.first_seen_at, p.kind, p.display_name "
            "FROM channel_week_roster r JOIN players p ON p.id = r.player_id "
            "WHERE r.week_start = ?"
        )
        params: list[Any] = [week_iso]
        if channel_id is not None:
            sql += " AND r.channel_id = ?"
            params.append(channel_id)
        sql += " ORDER BY r.channel_id, r.player_ref"
        return [dict(row) for row in conn.execute(sql, params)]

    def list_channel_week_players(
        self,
        week_start: date | datetime | str,
        channel_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List the players on the current-week Channel manifest."""

        week_iso = cal.iso_date(cal.week_start(week_start))
        with self._reader() as conn:
            return self._list_channel_week_players_with(
                conn, week_iso, channel_id
            )
