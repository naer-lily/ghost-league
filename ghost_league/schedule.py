"""Deterministic, pure-function weekly projection.

The projection never calls ``random``.  Every decision is derived from a
BLAKE2b digest of the player id and the ISO week start.  A player therefore
keeps the same broad schedule archetype across processes, machines and
restarts.

The weekly allocation is deliberately *not* a flat ``total / 168`` line:

1. build 168 non-negative integer preference weights;
2. water-fill the requested total by weight while enforcing 3600 seconds/hour;
3. use integer largest-remainder apportionment to hit the exact total.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import HourPoint

try:
    TZ: Final = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:  # Minimal containers without the IANA database.
    # Shanghai has observed UTC+08:00 without DST since 1991.
    TZ: Final = timezone(timedelta(hours=8), name="Asia/Shanghai")
HOURS_PER_WEEK: Final = 168
SECONDS_PER_HOUR: Final = 3600
SECONDS_PER_WEEK: Final = HOURS_PER_WEEK * SECONDS_PER_HOUR
BASELINE_WEIGHT: Final = 0

PROTOTYPES: Final[tuple[str, ...]] = (
    "steady_weekday",
    "night_owl",
    "sporadic",
    "weekend",
    "front_loaded",
    "fragmented",
)

PROTOTYPE_LABELS: Final[dict[str, str]] = {
    "steady_weekday": "工作日稳态",
    "night_owl": "夜猫型",
    "sporadic": "零星爆发",
    "weekend": "周末型",
    "front_loaded": "周初冲量",
    "fragmented": "碎片多段",
}

_MASK64: Final = (1 << 64) - 1


def _hash_int(*parts: object) -> int:
    """Return a stable 256-bit integer derived from domain-separated parts."""

    digest = hashlib.blake2b(digest_size=32)
    digest.update(b"ghost-league-v1\x00")
    for part in parts:
        encoded = str(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(b"\x00")
    return int.from_bytes(digest.digest(), "big")


def _splitmix64(value: int) -> int:
    """A tiny integer mixer; deterministic on every Python implementation."""

    value = (value + 0x9E3779B97F4A7C15) & _MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
    return (value ^ (value >> 31)) & _MASK64


def _week_start_date(week_start: date | datetime | str) -> date:
    if isinstance(week_start, datetime):
        return week_start.date()
    if isinstance(week_start, date):
        return week_start
    if isinstance(week_start, str):
        try:
            return date.fromisoformat(week_start)
        except ValueError as exc:
            raise ValueError(
                "week_start must be an ISO date such as 2026-10-19"
            ) from exc
    raise TypeError("week_start must be a date, datetime, or ISO date string")


def _to_shanghai(at: datetime) -> datetime:
    """Normalize an aware datetime to Asia/Shanghai.

    Naive datetimes are interpreted as UTC, matching the documented "UTC time"
    input convenience.  Aware datetimes may use any timezone.
    """

    if not isinstance(at, datetime):
        raise TypeError("at must be a datetime")
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(TZ)


def _validate_total(total_seconds: int) -> int:
    if isinstance(total_seconds, bool) or not isinstance(total_seconds, int):
        raise ValueError("total_seconds must be an integer")
    if total_seconds < 0 or total_seconds > SECONDS_PER_WEEK:
        raise ValueError(
            f"total_seconds must be in 0..{SECONDS_PER_WEEK}, got {total_seconds}"
        )
    return total_seconds


def prototype_for_user(user_id: str) -> str:
    """Return the user's stable schedule archetype."""

    if not isinstance(user_id, str) or not user_id:
        raise ValueError("user_id must be a non-empty string")
    return PROTOTYPES[_hash_int("prototype", user_id) % len(PROTOTYPES)]


def _base_hour_weight(prototype: str, hour: int) -> int:
    """Prototype hour preferences before user/week-specific variation."""

    if prototype == "steady_weekday":
        shape = (
            0, 0, 0, 0, 0, 0, 0, 22, 105, 175, 225, 235,
            18, 190, 240, 245, 220, 185, 95, 42, 0, 0, 0, 0,
        )
    elif prototype == "night_owl":
        shape = (
            255, 300, 225, 80, 0, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 25, 90, 160, 255, 335, 350, 305,
        )
    elif prototype == "weekend":
        shape = (
            8, 5, 3, 3, 4, 7, 10, 15, 42, 112, 165, 195,
            175, 160, 185, 205, 218, 225, 205, 180, 155, 125, 72, 30,
        )
    elif prototype == "front_loaded":
        shape = (
            0, 0, 0, 0, 0, 0, 0, 35, 150, 235, 270, 245,
            105, 190, 255, 275, 235, 170, 84, 46, 22, 0, 0, 0,
        )
    elif prototype == "fragmented":
        shape = (
            0, 0, 0, 0, 0, 0, 0, 70, 145, 0, 0, 12,
            125, 205, 0, 0, 24, 165, 225, 0, 0, 105, 160, 0,
        )
    elif prototype == "sporadic":
        # Sporadic's real shape is built from selected active days below.
        shape = (0,) * 24
    else:  # pragma: no cover - guarded by prototype_for_user
        raise ValueError(f"unknown prototype: {prototype}")
    return shape[hour % 24]


def _day_multiplier(prototype: str, day: int) -> int:
    if prototype == "steady_weekday":
        return (100, 100, 100, 75, 105, 15, 10)[day]
    if prototype == "night_owl":
        return (100, 100, 100, 100, 95, 130, 88)[day]
    if prototype == "weekend":
        return (0, 0, 0, 0, 22, 128, 100)[day]
    if prototype == "front_loaded":
        return (230, 150, 175, 95, 140, 45, 28)[day]
    if prototype == "fragmented":
        return (100, 100, 100, 95, 130, 64, 54)[day]
    if prototype == "sporadic":
        return 100
    raise ValueError(f"unknown prototype: {prototype}")


def _sporadic_active_days(seed: int) -> tuple[int, ...]:
    """Pick two or three distinct active weekdays in a stable order."""

    # Three selected days keep "two or three days" behavior while still giving
    # a 20-hour sporadic week enough hourly capacity to avoid spilling into
    # every other day.
    count = 3
    remaining = list(range(7))
    chosen: list[int] = []
    state = seed ^ 0x9FB21C651E98DF25
    for _ in range(count):
        state = _splitmix64(state)
        index = state % len(remaining)
        chosen.append(remaining.pop(index))
    return tuple(sorted(chosen))


def _sporadic_block_weight(seed: int, day: int, hour: int) -> int:
    """One or two concentrated blocks on an active day."""

    day_seed = seed ^ (day * 0xD6E8FEB86659FD93)
    start = 7 + (_splitmix64(day_seed) % 8)  # 07:00..14:00
    length = 7 + (_splitmix64(day_seed ^ 0x1234) % 5)  # 7..11 hours
    first = start <= hour < start + length
    second_start = start + length + 2 + (_splitmix64(day_seed ^ 0x5678) % 3)
    second = second_start <= hour < second_start + 2
    if first:
        return 245 + (_splitmix64(day_seed ^ hour) % 170)
    if second:
        return 130 + (_splitmix64(day_seed ^ (hour + 1)) % 90)
    return 4


@lru_cache(maxsize=8192)
def _schedule_weights_cached(user_id: str, week_iso: str) -> tuple[str, tuple[int, ...]]:
    date.fromisoformat(week_iso)
    user_seed = _hash_int("user", user_id)
    week_seed = _hash_int("week", user_id, week_iso)
    prototype = prototype_for_user(user_id)

    user_shift = (_splitmix64(user_seed ^ 0x1F123BB5) % 3) - 1
    week_shift = (_splitmix64(week_seed ^ 0x6A09E667) % 3) - 1
    shift = max(-2, min(2, user_shift + week_shift))

    day_jitter = [
        86 + (_splitmix64(week_seed ^ (day * 0x9E3779B9)) % 30)
        for day in range(7)
    ]
    sporadic_days = _sporadic_active_days(week_seed)
    weights: list[int] = []
    for day in range(7):
        for hour in range(24):
            source_hour = (hour - shift) % 24
            hour_jitter = 80 + (
                _splitmix64(
                    week_seed
                    ^ (day * 24 + hour) * 0xD1B54A32D192ED03
                    ^ user_seed
                )
                % 41
            )
            if prototype == "sporadic":
                if day in sporadic_days:
                    base = _sporadic_block_weight(week_seed, day, source_hour)
                else:
                    base = 0
                weight = (
                    base
                    * day_jitter[day]
                    * hour_jitter
                    // 10_000
                    + BASELINE_WEIGHT
                )
            else:
                base = _base_hour_weight(prototype, source_hour)
                weight = (
                    base
                    * _day_multiplier(prototype, day)
                    * day_jitter[day]
                    * hour_jitter
                    // 1_000_000
                    + BASELINE_WEIGHT
                )
            weights.append(max(0, weight))

    return prototype, tuple(weights)


def schedule_weights(
    user_id: str, week_start: date | datetime | str
) -> tuple[str, tuple[int, ...]]:
    """Public deterministic helper: return ``(prototype, 168 weights)``."""

    week = _week_start_date(week_start)
    return _schedule_weights_cached(user_id, week.isoformat())


def allocate_seconds(weights: list[int] | tuple[int, ...], total_seconds: int) -> list[int]:
    """Apportion ``total_seconds`` over 168 hourly slots exactly.

    The apportionment is weighted, cap-aware, and uses integer arithmetic.
    Every slot receives at least its weighted floor plus a possible 1-second
    largest-remainder adjustment.  Hours already at 3600 are removed from the
    active pool before the next water-filling round.
    """

    total = _validate_total(total_seconds)
    if len(weights) != HOURS_PER_WEEK:
        raise ValueError("weights must contain exactly 168 entries")
    if any(not isinstance(weight, int) or isinstance(weight, bool) or weight < 0 for weight in weights):
        raise ValueError("weights must be non-negative integers")
    if total == 0:
        return [0] * HOURS_PER_WEEK

    active = [index for index, weight in enumerate(weights) if weight > 0]
    allocations = [0] * HOURS_PER_WEEK
    remaining = total

    while remaining > 0:
        if not active:
            # Preferred hours are full.  Very large weekly totals (for example
            # 147 hours) must spill into otherwise dormant hours so the hard
            # 3600-seconds/hour cap can still be respected.
            candidates = [
                index
                for index in range(HOURS_PER_WEEK)
                if allocations[index] < SECONDS_PER_HOUR
            ]
            if not candidates:
                raise ValueError("not enough hourly capacity to allocate total")
            capacity = len(candidates) * SECONDS_PER_HOUR
            if remaining > capacity:
                raise ValueError("not enough hourly capacity to allocate total")
            base, extra = divmod(remaining, len(candidates))
            for position, index in enumerate(candidates):
                allocations[index] += base + (1 if position < extra else 0)
            remaining = 0
            break

        weight_sum = sum(weights[index] for index in active)
        if weight_sum <= 0:
            raise ValueError("not enough positive weight to allocate total")

        capped = [
            index
            for index in active
            if (remaining * weights[index]) // weight_sum >= SECONDS_PER_HOUR
        ]
        if capped:
            for index in capped:
                allocations[index] = SECONDS_PER_HOUR
                remaining -= SECONDS_PER_HOUR
            capped_set = set(capped)
            active = [index for index in active if index not in capped_set]
            continue

        floors: list[int] = []
        remainders: list[tuple[int, int]] = []
        for index in active:
            floor_value, remainder = divmod(remaining * weights[index], weight_sum)
            floors.append(floor_value)
            remainders.append((remainder, index))

        allocated = sum(floors)
        for floor_value, index in zip(floors, active):
            allocations[index] = floor_value

        deficit = remaining - allocated
        # Sort by remainder descending, then hour index for a stable tie-break.
        remainders.sort(key=lambda pair: (-pair[0], pair[1]))
        for _, index in remainders[:deficit]:
            allocations[index] += 1
        remaining = 0

    if sum(allocations) != total:
        raise RuntimeError("internal allocation error: total mismatch")
    if any(seconds < 0 or seconds > SECONDS_PER_HOUR for seconds in allocations):
        raise RuntimeError("internal allocation error: hourly cap violated")
    return allocations


@lru_cache(maxsize=8192)
def _allocation_cached(user_id: str, week_iso: str, total_seconds: int) -> tuple[int, ...]:
    _, weights = _schedule_weights_cached(user_id, week_iso)
    return tuple(allocate_seconds(weights, total_seconds))


def hourly_seconds(user_id: str, week_start: date | datetime | str, total_seconds: int) -> list[int]:
    """Return the 168 hourly increments for one projected week."""

    week = _week_start_date(week_start)
    total = _validate_total(total_seconds)
    return list(_allocation_cached(user_id, week.isoformat(), total))


def projected_seconds(
    user_id: str,
    week_start: date | datetime | str,
    total_seconds: int,
    at: datetime,
) -> int:
    """Project a user's cumulative seconds at an arbitrary instant.

    Inputs:
        user_id: stable public identifier.
        week_start: Monday (or any chosen seven-day window start).
        total_seconds: exact end-of-week total, in ``0..604800``.
        at: aware datetime, or a naive datetime interpreted as UTC.

    Week boundaries are computed in Asia/Shanghai.  Before the window the
    result is 0; at or after the end it is exactly ``total_seconds``.  Inside
    the current hour, that hour's allocated seconds are revealed linearly and
    floored to an integer second.
    """

    total = _validate_total(total_seconds)
    if total == 0:
        return 0

    week = _week_start_date(week_start)
    allocations = _allocation_cached(user_id, week.isoformat(), total)
    start_dt = datetime.combine(week, time.min, tzinfo=TZ)
    local_at = _to_shanghai(at)
    elapsed = int((local_at - start_dt).total_seconds())

    if elapsed <= 0:
        return 0
    if elapsed >= SECONDS_PER_WEEK:
        return total

    hour_index, second_in_hour = divmod(elapsed, SECONDS_PER_HOUR)
    prefix = sum(allocations[:hour_index])
    partial = allocations[hour_index] * second_in_hour // SECONDS_PER_HOUR
    return min(total, prefix + partial)


def hourly_series(
    user_id: str, week_start: date | datetime | str, total_seconds: int
) -> list[HourPoint]:
    """Return all 168 HourPoints for one week, with local start timestamps."""

    week = _week_start_date(week_start)
    total = _validate_total(total_seconds)
    increments = hourly_seconds(user_id, week, total)
    start_dt = datetime.combine(week, time.min, tzinfo=TZ)
    points: list[HourPoint] = []
    cumulative = 0
    for index, seconds in enumerate(increments):
        cumulative += seconds
        starts_at = (start_dt + timedelta(hours=index)).isoformat(timespec="seconds")
        points.append(
            HourPoint(
                hour_index=index,
                starts_at=starts_at,
                seconds=seconds,
                cumulative_seconds=cumulative,
            )
        )
    return points


def active_hours_and_streak(hourly_increments: list[int] | tuple[int, ...]) -> tuple[int, int]:
    """Return ``(active_hour_count, longest_consecutive_active_hours)``."""

    active = sum(1 for seconds in hourly_increments if seconds > 0)
    longest = 0
    current = 0
    for seconds in hourly_increments:
        if seconds > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return active, longest


def clear_runtime_caches() -> None:
    """Clear memoization only.  It never changes any computed result."""

    _schedule_weights_cached.cache_clear()
    _allocation_cached.cache_clear()
