"""Pure game rules: XP, tiers, grouping, embers, and settlement ordering."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

TIERS: Final[tuple[str, ...]] = (
    "Bronze",
    "Silver",
    "Gold",
    "Sapphire",
    "Ruby",
    "Emerald",
    "Amethyst",
    "Pearl",
    "Obsidian",
    "Diamond",
)
TIER_INDEX: Final[dict[str, int]] = {tier: index for index, tier in enumerate(TIERS)}
GROUP_SIZE: Final = 15
MIN_GROUP_SIZE: Final = 2
OPPONENT_COUNT: Final = GROUP_SIZE - 1


def balanced_group_sizes(count: int) -> tuple[int, ...]:
    """Return the deterministic, balanced group sizes for ``count`` players.

    The number of groups is fixed first (``ceil(count / 15)``), then every
    group receives ``base`` or ``base + 1`` players.  Larger groups come first
    so human-first placement naturally favours the extra seats.  A single
    player is deliberately unplaced: a league group needs at least two people.
    """

    if isinstance(count, bool) or count < 0:
        raise ValueError("count must be a non-negative integer")
    if count < MIN_GROUP_SIZE:
        return ()
    group_count = (count + GROUP_SIZE - 1) // GROUP_SIZE
    base, remainder = divmod(count, group_count)
    return tuple(
        [base + 1] * remainder + [base] * (group_count - remainder)
    )
CHECKIN_SECONDS: Final = 600
CHECKIN_XP: Final = CHECKIN_SECONDS // 6
SECONDS_PER_XP: Final = 6
EMBER_XP_PER_EMBER: Final = 2000
EMBER_WEEK_CAP: Final = 2
EMBER_BALANCE_CAP: Final = 3
REPAIR_COST: Final = 1
REPAIR_WINDOW_DAYS: Final = 7
REPAIR_SOURCE: Final = "repaired"
VERIFIED_SOURCE: Final = "verified"
# Kept for API compatibility; source normalization is the default target path.
TARGET_ALGORITHM_VERSION: Final = "p75-soft-0.2-v1"


@dataclass(frozen=True, slots=True)
class TierBand:
    """Weekly AI target band for one tier (XP and internal seconds)."""

    xp_floor: int
    xp_cap: int

    @property
    def seconds_floor(self) -> int:
        return self.xp_floor * SECONDS_PER_XP

    @property
    def seconds_cap(self) -> int:
        return self.xp_cap * SECONDS_PER_XP


def _band(xp_floor: int, xp_cap: int) -> TierBand:
    return TierBand(xp_floor=xp_floor, xp_cap=xp_cap)


# Future option only: tier bands are not used by the default Phase 1 target path.
# Design 5.3.  XP bands are the source of truth; seconds are derived at 6s/XP.
TIER_BANDS: Final[dict[str, TierBand]] = {
    "Bronze": _band(600, 5_000),
    "Silver": _band(3_000, 9_000),
    "Gold": _band(6_000, 14_000),
    "Sapphire": _band(10_000, 20_000),
    "Ruby": _band(15_000, 27_000),
    "Emerald": _band(20_000, 35_000),
    "Amethyst": _band(26_000, 44_000),
    "Pearl": _band(32_000, 54_000),
    "Obsidian": _band(40_000, 66_000),
    "Diamond": _band(50_000, 80_000),
}

# Fixed, no-replacement percentile slots for the 14 AI in a 15-person group.
OPPONENT_PERCENTILE_SLOTS: Final[tuple[int, ...]] = (
    8,
    14,
    22,
    30,
    38,
    46,
    54,
    62,
    70,
    76,
    82,
    86,
    90,
    93,
)


def tier_band(tier: str) -> TierBand:
    try:
        return TIER_BANDS[tier]
    except KeyError as exc:
        raise ValueError(f"unknown tier: {tier}") from exc


def _target_hash_int(*parts: object) -> int:
    """Stable, domain-separated hash for target plans (never uses ``random``)."""

    digest = hashlib.blake2b(digest_size=32)
    digest.update(b"ghost-league-target-v1\x00")
    for part in parts:
        encoded = str(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(b"\x00")
    return int.from_bytes(digest.digest(), "big")


def week_factor(seed: object, week_start: date | datetime | str) -> float:
    """Return the deterministic 0.90-1.10 target week factor."""

    week = week_start.date() if isinstance(week_start, datetime) else week_start
    week_iso = week.isoformat() if isinstance(week, date) else str(week)
    return 0.90 + (_target_hash_int(seed, week_iso, "week") % 21) / 100


def target_seconds_for_percentile(
    *,
    tier: str,
    percentile: float,
    seed: object,
    week_start: date | datetime | str,
) -> int:
    """Future option: scale an anchor percentile into a tier band.

    The default Phase 1 target is the source-layer effective anchor and never
    calls this helper.  It is retained for a possible later tier-band design.

    ``anchor_seconds`` is deliberately not an input: raw WakaTime totals remain
    audit data and only determine the within-tier percentile.
    """

    band = tier_band(tier)
    if percentile < 0 or percentile > 1:
        raise ValueError("percentile must be in 0..1")
    base = band.seconds_floor + (
        band.seconds_cap - band.seconds_floor
    ) * float(percentile)
    target = round(base * week_factor(seed, week_start))
    return max(band.seconds_floor, min(band.seconds_cap, target))


class GameError(Exception):
    """Base class for expected, user-facing game rule errors."""


class PlayerNotFound(GameError):
    pass


class ChannelRosterMissing(PlayerNotFound):
    """An increment named a player this Channel has not announced."""

    pass


class WeekLocked(GameError):
    pass


class DuplicateIdempotencyKey(GameError):
    pass


class RepairRejected(GameError):
    """A repair request failed a business rule.

    ``code`` is stable for CLI/API mapping; ``detail`` is safe to show.
    """

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def xp_for_seconds(seconds: int) -> int:
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    return seconds // SECONDS_PER_XP


def earned_embers_for_week(week_seconds: int) -> int:
    week_xp = xp_for_seconds(week_seconds)
    return min(EMBER_WEEK_CAP, week_xp // EMBER_XP_PER_EMBER)


def ember_grant_amount(
    *,
    week_seconds: int,
    granted_this_week: int,
    balance: int,
) -> int:
    earned = earned_embers_for_week(week_seconds)
    potential = earned - granted_this_week
    return max(0, min(potential, EMBER_BALANCE_CAP - balance))


def is_valid_repair_day(
    *,
    day: date,
    today: date,
    now: datetime,
) -> tuple[bool, str]:
    """Validate the seven-day repair window.

    The window is measured from the end of the repair day: D+1 00:00 local
    plus seven days, so every completed day from D-1 through D-7 is reachable
    while D-8 and older are always rejected.
    """

    from .calendar import day_end_at

    age = (today - day).days
    if age < 1:
        return False, "today_or_future"
    if age > REPAIR_WINDOW_DAYS:
        return False, "outside_window"
    if now >= day_end_at(day) + timedelta(days=REPAIR_WINDOW_DAYS):
        return False, "outside_window"
    return True, ""


def group_quota(group_size: int) -> int:
    """Return this group's weekly promotion/demotion quota.

    One seat per five players, rounded half up, with a minimum of one:
    ``max(1, round_half_up(group_size * 0.2))``.  The integer form
    ``(2 * n + 5) // 10`` is exactly that formula for a non-negative size.
    ``group_movement`` handles groups smaller than two players.
    """

    if isinstance(group_size, bool) or not isinstance(group_size, int):
        raise TypeError("group_size must be an integer")
    if group_size < 0:
        raise ValueError("group_size must be non-negative")
    return max(1, (group_size * 2 + 5) // 10)


def group_movement(
    rank: int, tier: str, group_size: int
) -> tuple[bool, bool]:
    """Return ``(promoted, demoted)`` for one player's within-group rank.

    Every group settles independently: its top ``quota`` promote and its
    bottom ``quota`` demote.  ``rank`` is the group rank (seconds descending,
    player id ascending), not a tier-wide rank.  The same player can never be
    both promoted and demoted, and a group with fewer than two players does
    not move.  Bronze never demotes and Diamond never promotes.
    """

    if tier not in TIER_INDEX:
        raise ValueError(f"unknown tier: {tier}")
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise TypeError("rank must be an integer")
    if isinstance(group_size, bool) or not isinstance(group_size, int):
        raise TypeError("group_size must be an integer")
    if group_size < 2:
        return False, False
    if rank < 1 or rank > group_size:
        raise ValueError("rank must be within the group")
    quota = group_quota(group_size)
    promoted = rank <= quota and tier != TIERS[-1]
    demoted = rank > group_size - quota and tier != TIERS[0]
    return promoted, demoted


def next_tier(tier: str, *, promoted: bool, demoted: bool) -> str:
    index = TIER_INDEX[tier]
    if promoted:
        index = min(index + 1, len(TIERS) - 1)
    elif demoted:
        index = max(index - 1, 0)
    return TIERS[index]


@dataclass(frozen=True, slots=True)
class ScoreRow:
    player_id: str
    seconds: int
    xp: int


def rank_scores(rows: list[ScoreRow]) -> list[ScoreRow]:
    """Sort by XP desc, then player_id asc (stable, reproducible)."""

    return sorted(rows, key=lambda row: (-row.xp, row.player_id))
