"""Anonymous WakaTime leaderboard rows -> stable AI players.

Only the public row ``id`` is used for the source key.  Names, cities, avatars
and profile pages never reach the database.

External rows are normalized once at the source layer.  The raw weekly total is
kept in ``sources.anchor_seconds`` for audit, while the effective value feeds the
league and becomes the opponent's weekly target.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from ..source.normalize import NORMALIZATION_VERSION, normalize_seconds
from . import calendar as cal
from .rules import OPPONENT_COUNT, PlayerNotFound
from .store import SOURCE_AI, SOURCE_CHANNEL, GameStore

DEFAULT_CACHE_PATH: Final = Path("data/cache/cn-978.json")
DEFAULT_SOURCE_SALT: Final = "ghost-league-source-v1"


def source_key_hash(source_id: str, *, salt: str | None = None) -> str:
    """HMAC the public user id; the raw id is never persisted."""

    if not isinstance(source_id, str) or not source_id:
        raise ValueError("source id must be a non-empty string")
    key = salt if salt is not None else os.environ.get("LEAGUE_SOURCE_SALT", DEFAULT_SOURCE_SALT)
    return hmac.new(
        key.encode("utf-8"),
        source_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def normalize_anchor_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate raw anonymous rows and attach snapshot-wide effective values.

    The full snapshot is normalized before any roster decision, so the p75
    threshold does not move with the number of players.  Duplicate source ids
    are collapsed by first occurrence so one stable source cannot become two
    AI.
    """

    if not isinstance(rows, list):
        raise TypeError("cache must contain a users list")
    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_id = row.get("id")
        seconds = row.get("seconds")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            continue
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            continue
        seen.add(source_id)
        anchor = min(seconds, 7 * 24 * 3600)
        anchors.append(
            {
                "source_id": source_id,
                "seconds": anchor,
                "rank": int(row.get("rank") or 0),
            }
        )
    if not anchors:
        raise ValueError("cache contains no usable anonymous anchor rows")
    normalized = normalize_seconds(anchors)
    for anchor, effective in zip(
        anchors, normalized["effective_seconds"], strict=True
    ):
        anchor["effective_seconds"] = int(effective)
        anchor["p75_seconds"] = int(normalized["p75_seconds"])
        anchor["normalization_version"] = str(normalized["version"])
    return anchors


def load_anchor_rows(cache_path: str | Path = DEFAULT_CACHE_PATH) -> list[dict[str, Any]]:
    """Load the complete cache snapshot as normalized anonymous anchor rows."""

    path = Path(cache_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("users") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise TypeError("cache must contain a users list")
    return normalize_anchor_rows(rows)


def anchor_percentiles(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Map each anchor row to its percentile in the anonymous anchor pool.

    Rank 1 is the strongest anchor and therefore sits at the top percentile.
    Ties are broken by source id so the result is reproducible.  This value is
    audit metadata only; it no longer controls the weekly target.
    """

    ordered = sorted(rows, key=lambda row: (row["rank"], row["source_id"]))
    if not ordered:
        return {}
    if len(ordered) == 1:
        return {str(ordered[0]["source_id"]): 0.5}
    denominator = len(ordered) - 1
    return {
        str(row["source_id"]): (len(ordered) - 1 - index) / denominator
        for index, row in enumerate(ordered)
    }


def target_percentiles(count: int) -> tuple[float, ...]:
    """Legacy staged target slots, kept for reference only.

    The default Phase 1 target no longer uses these percentiles.  They remain
    available as a possible future design option, but are never written into an
    opponent plan by :func:`seed_roster`.
    """

    from .rules import OPPONENT_PERCENTILE_SLOTS

    if count <= 0:
        raise ValueError("count must be positive")
    slots = tuple(reversed(OPPONENT_PERCENTILE_SLOTS))
    if count == len(slots):
        return tuple(value / 100 for value in slots)
    if count > len(slots):
        step = (slots[0] - slots[-1]) / (count - 1)
        return tuple((slots[0] - index * step) / 100 for index in range(count))
    if count == 1:
        return (slots[len(slots) // 2] / 100,)
    indices = [
        round(index * (len(slots) - 1) / (count - 1)) for index in range(count)
    ]
    return tuple(slots[index] / 100 for index in indices)


def build_opponent_week_plan(
    *,
    anchor_seconds: int,
    effective_seconds: int | None = None,
    seed: str,
    week: str | datetime,
    percentile: float | None = None,
    p75_seconds: int = 0,
    normalization_version: str = NORMALIZATION_VERSION,
    tier: str | None = None,
) -> dict[str, Any]:
    """Build the pure, deterministic target plan for one AI/week.

    ``anchor_seconds`` is the raw source value for audit.  ``target_seconds`` is
    always the source-normalized effective value; no tier band or week factor
    is applied.  ``tier`` is accepted only for older callers and is ignored.
    """

    week_date = cal.week_start(week)
    if isinstance(anchor_seconds, bool) or anchor_seconds < 0:
        raise ValueError("anchor_seconds must be non-negative")
    effective = anchor_seconds if effective_seconds is None else effective_seconds
    if isinstance(effective, bool) or effective < 0:
        raise ValueError("effective_seconds must be non-negative")
    if percentile is not None and not 0 <= float(percentile) <= 1:
        raise ValueError("percentile must be in 0..1")
    if not normalization_version:
        raise ValueError("normalization_version must be non-empty")
    return {
        "week_start": week_date.isoformat(),
        "anchor_seconds": int(anchor_seconds),
        "effective_seconds": int(effective),
        "target_seconds": int(effective),
        "target_xp": int(effective) // 6,
        "percentile": float(percentile) if percentile is not None else 0.0,
        "p75_seconds": int(p75_seconds),
        "seed": seed,
        "algorithm_version": normalization_version,
        "normalization_version": normalization_version,
    }


def select_anchor_rows(
    rows: list[dict[str, Any]], count: int
) -> list[dict[str, Any]]:
    """Pick a deterministic spread without randomising the binding.

    Rows are ordered by public rank and then id; evenly spaced positions keep
    the roster from being all top-of-board or all bottom-of-board.  The same
    cache and count always select the same rows.
    """

    if count <= 0:
        raise ValueError("count must be positive")
    ordered = sorted(rows, key=lambda row: (row["rank"], row["source_id"]))
    if count >= len(ordered):
        return ordered[:count]
    positions = [index * len(ordered) // count for index in range(count)]
    return [ordered[position] for position in positions]


def seed_roster(
    store: GameStore,
    week: str | datetime,
    *,
    count: int = OPPONENT_COUNT,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    at: datetime | str | None = None,
    salt: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """Create the current week's AI roster and lock each AI's target.

    Every external row stores both its raw and effective value.  The effective
    value is the default target; the returned ``target_seconds`` is always the
    effective value, never the raw WakaTime total.
    """

    week_date = cal.week_start(week)
    week_iso = week_date.isoformat()
    local_at = cal.parse_datetime(at) if at is not None else cal.now_local()
    if week_date != cal.week_start(local_at):
        raise ValueError(
            "seed-roster only creates the current week; "
            f"requested {week_iso}, clock week {cal.week_start(local_at).isoformat()}"
        )
    pool = load_anchor_rows(cache_path)
    percentiles = anchor_percentiles(pool)
    anchors = select_anchor_rows(pool, count)
    store.ensure_week(week_date)

    created = 0
    existing = 0
    players: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors, start=1):
        key_hash = source_key_hash(anchor["source_id"], salt=salt)
        store.upsert_source(
            key_hash,
            anchor_seconds=int(anchor["seconds"]),
            effective_seconds=int(anchor["effective_seconds"]),
            p75_seconds=int(anchor["p75_seconds"]),
            normalization_version=str(anchor["normalization_version"]),
            anchor_week=week_date,
            fetched_at=local_at,
        )
        player_id = f"ai-{key_hash[:12]}"
        try:
            store.get_player(player_id)
            known = True
        except PlayerNotFound:
            known = False
        player = store.create_player(
            player_id,
            kind="ai",
            controller="ai",
            source_kind=SOURCE_AI,
            source_key_hash=key_hash,
            display_name=f"AI-{index:02d}",
            joined_week=week_date,
            now=local_at,
        )
        if known:
            existing += 1
        else:
            created += 1
        chosen_tier = tier or store.tier_for_player(player["id"], week_date)
        plan = build_opponent_week_plan(
            anchor_seconds=int(anchor["seconds"]),
            effective_seconds=int(anchor["effective_seconds"]),
            percentile=percentiles.get(anchor["source_id"], 0.0),
            p75_seconds=int(anchor["p75_seconds"]),
            seed=player["id"],
            week=week_date,
        )
        plan = store.upsert_opponent_week_plan(
            player["id"],
            week_date,
            anchor_seconds=plan["anchor_seconds"],
            target_seconds=plan["target_seconds"],
            target_xp=plan["target_xp"],
            percentile=plan["percentile"],
            seed=plan["seed"],
            algorithm_version=plan["algorithm_version"],
            created_at=local_at,
        )
        players.append(
            {
                "player_id": player["id"],
                "display_name": player["display_name"],
                "source_key_hash": key_hash,
                "tier": chosen_tier,
                "percentile": plan["percentile"],
                "raw_seconds": int(anchor["seconds"]),
                "effective_seconds": int(anchor["effective_seconds"]),
                "target_seconds": int(plan["target_seconds"]),
                "target_xp": int(plan["target_xp"]),
            }
        )

    return {
        "week_start": week_iso,
        "count": len(players),
        "created": created,
        "existing": existing,
        "p75_seconds": int(pool[0]["p75_seconds"]),
        "normalization_version": NORMALIZATION_VERSION,
        "players": players,
    }


def sync_week_roster(
    store: GameStore,
    week: str | datetime,
    cache: str | Path | list[dict[str, Any]] = DEFAULT_CACHE_PATH,
    *,
    at: datetime | str | None = None,
    salt: str | None = None,
) -> dict[str, Any]:
    """Bind the complete anonymous source snapshot to stable AI players.

    Every row in ``cache`` becomes an AI identity keyed by ``source_key_hash``;
    there is no top-14 selection.  A row that is present this week always gets
    a current-week plan, including a zero-second row (target ``0``).  An AI
    that is absent keeps its player row and historical plans but loses the
    current-week plan, so it cannot be placed in this week's groups.
    """

    week_date = cal.week_start(week)
    week_iso = week_date.isoformat()
    local_at = cal.parse_datetime(at) if at is not None else cal.now_local()
    if week_date != cal.week_start(local_at):
        raise ValueError(
            "sync-week-roster only creates the current week; "
            f"requested {week_iso}, clock week {cal.week_start(local_at).isoformat()}"
        )
    if isinstance(cache, list):
        pool = normalize_anchor_rows([dict(row) for row in cache])
    else:
        pool = load_anchor_rows(cache)
    percentiles = anchor_percentiles(pool)
    store.ensure_week(week_date)

    created = 0
    existing = 0
    current_ids: set[str] = set()
    players: list[dict[str, Any]] = []
    prior_plan_ids = {
        str(plan["player_id"])
        for plan in store.list_opponent_week_plans(week_date)
    }
    with store.transaction() as conn:
        for anchor in pool:
            key_hash = source_key_hash(anchor["source_id"], salt=salt)
            store.upsert_source(
                key_hash,
                anchor_seconds=int(anchor["seconds"]),
                effective_seconds=int(anchor["effective_seconds"]),
                p75_seconds=int(anchor["p75_seconds"]),
                normalization_version=str(anchor["normalization_version"]),
                anchor_week=week_date,
                fetched_at=local_at,
                conn=conn,
            )
            player, was_created = store.upsert_ai_player(
                key_hash,
                display_name=f"AI-{key_hash[:8].upper()}",
                joined_week=week_date,
                last_seen_week=week_date,
                now=local_at,
                conn=conn,
            )
            player_id = str(player["id"])
            current_ids.add(player_id)
            if was_created:
                created += 1
            else:
                existing += 1
            plan = build_opponent_week_plan(
                anchor_seconds=int(anchor["seconds"]),
                effective_seconds=int(anchor["effective_seconds"]),
                percentile=percentiles.get(anchor["source_id"], 0.0),
                p75_seconds=int(anchor["p75_seconds"]),
                seed=player_id,
                week=week_date,
            )
            plan = store.upsert_opponent_week_plan(
                player_id,
                week_date,
                anchor_seconds=plan["anchor_seconds"],
                target_seconds=plan["target_seconds"],
                target_xp=plan["target_xp"],
                percentile=plan["percentile"],
                seed=plan["seed"],
                algorithm_version=plan["algorithm_version"],
                created_at=local_at,
                conn=conn,
            )
            players.append(
                {
                    "player_id": player_id,
                    "display_name": player["display_name"],
                    "source_key_hash": key_hash,
                    "raw_seconds": int(anchor["seconds"]),
                    "effective_seconds": int(anchor["effective_seconds"]),
                    "target_seconds": int(plan["target_seconds"]),
                    "target_xp": int(plan["target_xp"]),
                }
            )

        # Any AI with a stale current-week plan is unavailable this week.  The
        # plan is withdrawn instead of reusing an old target or group slot.
        stale_with_plan = prior_plan_ids - current_ids
        for player_id in stale_with_plan:
            conn.execute(
                "DELETE FROM opponent_week_plan "
                "WHERE player_id = ? AND week_start = ?",
                (player_id, week_iso),
            )
            conn.execute(
                "DELETE FROM group_members WHERE player_id = ? AND group_id IN "
                "(SELECT id FROM groups WHERE week_start = ?)",
                (player_id, week_iso),
            )
            conn.execute(
                "UPDATE players SET last_seen_week = COALESCE("
                "(SELECT MAX(week_start) FROM opponent_week_plan "
                " WHERE player_id = ? AND week_start < ?), joined_week) "
                "WHERE id = ?",
                (player_id, week_iso, player_id),
            )

        previous_week = (week_date - timedelta(days=7)).isoformat()
        disappeared_ids = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM players WHERE kind = 'ai' "
                "AND source_kind != ? "
                "AND last_seen_week = ? AND is_active = 1",
                (SOURCE_CHANNEL, previous_week),
            )
            if str(row["id"]) not in current_ids
        }
        disappeared_ids |= stale_with_plan

    for item in players:
        item["tier"] = store.tier_for_player(item["player_id"], week_date)

    return {
        "week_start": week_iso,
        "count": len(players),
        "source_count": len(pool),
        "created": created,
        "existing": existing,
        "disappeared": len(disappeared_ids),
        "disappeared_player_ids": sorted(disappeared_ids),
        "p75_seconds": int(pool[0]["p75_seconds"]),
        "normalization_version": NORMALIZATION_VERSION,
        "players": players,
    }


def ensure_all_groups(
    store: GameStore,
    week: str | datetime,
    *,
    now: datetime | None = None,
    spread_humans: bool = False,
) -> list[dict[str, Any]]:
    """Materialize all current-week groups for humans and planned AI."""

    return store.ensure_all_groups(
        week, now=now, spread_humans=spread_humans
    )

