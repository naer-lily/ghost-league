"""Ghost-owned time-limited tasks: chest tiers, DSL rules, and evaluation.

This module holds only pure rules plus the restricted JSON expression
evaluator.  It never writes XP or weekly scores.  All activity reads go back
through :class:`GameStore`'s daily resolver; task code must not rebuild a
check-in or Channel fallback.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import date, datetime
from typing import Any, Callable

from . import calendar as cal
from .rules import GameError

logger = logging.getLogger(__name__)

# A single authoritative chest table.  Tier numbers are the stored value in
# ``task_instances.chest_tier``; the ranges are inclusive diamond amounts.
CHEST_TIERS: tuple[dict[str, Any], ...] = (
    {"tier": 1, "key": "wood", "name": "木箱", "min": 3, "max": 6},
    {"tier": 2, "key": "copper", "name": "铜箱", "min": 8, "max": 14},
    {"tier": 3, "key": "silver", "name": "银箱", "min": 18, "max": 30},
    {"tier": 4, "key": "gold", "name": "金箱", "min": 45, "max": 70},
    {"tier": 5, "key": "star", "name": "星箱", "min": 100, "max": 100},
)
CHEST_BY_TIER: dict[int, dict[str, Any]] = {
    int(row["tier"]): row for row in CHEST_TIERS
}

# Placeholder tiers written when an active instance is generated.  The real
# tier is rolled from the instance's pool exactly once, at completion.
MANUAL_CHEST_TIER: dict[int, int] = {1: 1, 2: 2, 3: 3}
REPAIR_CHEST_TIER = 1
WEEKEND_CHEST_TIER = 5
CHECKIN_CHEST_TIER = 1

CHEST_POOL_CHECKIN = "checkin"
CHEST_POOL_DAILY_PREFIX = "daily_"
CHEST_POOL_REPAIR = "repair"
CHEST_POOL_WEEKEND = "weekend"
CHEST_POOL_NAMES = (
    CHEST_POOL_CHECKIN,
    "daily_1",
    "daily_2",
    "daily_3",
    CHEST_POOL_REPAIR,
    CHEST_POOL_WEEKEND,
)
MANUAL_CHEST_POOL: dict[int, str] = {
    1: "daily_1",
    2: "daily_2",
    3: "daily_3",
}
# Missing or invalid pool config falls back to the most conservative pool for
# that source.  Claiming a chest must never fail because of a pool row.
CHEST_POOL_FALLBACKS: dict[str, dict[int, int]] = {
    "checkin": {1: 100},
    "daily_1": {1: 100},
    "daily_2": {1: 100},
    "daily_3": {1: 100},
    "repair": {1: 100},
    "weekend": {2: 100},
}

CHECKIN_TASK_SOURCE = "checkin"
CHECKIN_TASK_TITLE = "每日打卡"
CHECKIN_TASK_DESCRIPTION = "画满 10 分钟，开个小宝箱。"
TASK_CHEST_BOOST_CHANCE_KEY = "task_chest_boost_chance"
TASK_CHEST_BOOST_MINUTES_KEY = "task_chest_boost_minutes"
TASK_CHEST_BOOST_CUTOFF_HOUR_KEY = "task_chest_boost_cutoff_hour"
TASK_CHEST_STAR_CHANCE_KEY = "task_chest_star_chance"
TASK_CHEST_POOL_PREFIX = "task_chest_pool_"
CHEST_REWARD_DIAMONDS = "diamonds"
CHEST_REWARD_BOOST = "boost"
CHEST_REWARD_STAR = "star"

REPAIR_XP_THRESHOLD = 100
REPAIR_LOOKBACK_DAYS = 7
WEEKEND_XP_TARGET = 1000
MAX_ACTIVE_TASK_DEFINITIONS = 20

TASK_SOURCES = ("checkin", "daily_manual", "repair", "weekend")
TASK_COMPLETION_MODES = ("manual", "dsl")

MAX_DSL_DEPTH = 64
MAX_DSL_NODES = 64


class TaskNotFound(GameError):
    """The task does not exist or belongs to another user."""


class TaskStateRejected(GameError):
    """The task exists but its lifecycle state forbids this operation."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class TaskLimitReached(GameError):
    """The user already has the maximum number of active definitions."""


class ConditionError(ValueError):
    """Internal signal for an invalid or disallowed DSL expression."""


def chest_amount_range(tier: int) -> tuple[int, int]:
    if isinstance(tier, bool) or not isinstance(tier, int) or tier not in CHEST_BY_TIER:
        raise ValueError("chest tier must be an integer from 1 to 5")
    row = CHEST_BY_TIER[tier]
    return int(row["min"]), int(row["max"])


def roll_chest_amount(
    tier: int,
    *,
    rng: Callable[[int], int] | None = None,
) -> int:
    """Pick a uniform diamond amount from the tier's inclusive range."""

    low, high = chest_amount_range(tier)
    span = high - low + 1
    draw = rng or secrets.randbelow
    return low + int(draw(span))


def checkin_condition() -> dict[str, Any]:
    """The daily check-in succeeds once today's check-in is verified."""

    return {
        "op": "eq",
        "left": {"fn": "checkin_source", "args": [{"var": "task.start"}]},
        "right": "verified",
    }


def roll_chest_reward(
    tier: int,
    *,
    boost_chance: int = 0,
    boost_minutes: int = 0,
    star_chance: int = 0,
    boost_allowed: bool = True,
    rng: Callable[[int], int] | None = None,
) -> dict[str, Any]:
    """Roll one chest reward.

    Tiers 1-3 may pay a boost before the local cutoff; tiers 4-5 never pay a
    boost.  Tier 5 may pay one normal star instead of its fixed 100 diamonds.
    ``boost_chance`` and ``star_chance`` are integer percentages.  Invalid or
    missing config is normalised to zero by the caller, so the chest still pays
    diamonds.  The returned mapping always has ``reward_type`` and
    ``boost_minutes``; boost and star rewards keep ``amount`` at zero so the
    API field stays an integer.
    """

    chest_amount_range(tier)
    try:
        chance = int(boost_chance)
        minutes = int(boost_minutes)
        star = int(star_chance)
    except (TypeError, ValueError):
        chance, minutes, star = 0, 0, 0
    if isinstance(boost_chance, bool) or isinstance(boost_minutes, bool):
        chance, minutes = 0, 0
    if isinstance(star_chance, bool):
        star = 0
    if not 0 <= chance <= 100 or minutes < 1:
        chance, minutes = 0, 0
    if not 0 <= star <= 100:
        star = 0

    draw = rng or secrets.randbelow
    if tier == 5 and star and int(draw(100)) < star:
        return {
            "reward_type": CHEST_REWARD_STAR,
            "amount": 0,
            "boost_minutes": None,
        }
    if tier <= 3 and boost_allowed and chance and int(draw(100)) < chance:
        return {
            "reward_type": CHEST_REWARD_BOOST,
            "amount": 0,
            "boost_minutes": minutes,
        }
    return {
        "reward_type": CHEST_REWARD_DIAMONDS,
        "amount": roll_chest_amount(tier, rng=draw),
        "boost_minutes": None,
    }


def chest_pool_for_task(source: str, difficulty: int) -> str:
    """Return the chest pool a task instance draws from.

    Daily manual tasks use their difficulty; the other sources have one
    dedicated pool.  Unknown sources fall back to the most conservative daily
    pool so generation and completion never fail on a missing mapping.
    """

    if source == "daily_manual":
        return MANUAL_CHEST_POOL.get(int(difficulty), "daily_1")
    if source in {CHEST_POOL_CHECKIN, CHEST_POOL_REPAIR, CHEST_POOL_WEEKEND}:
        return source
    return "daily_1"


def chest_pool_config_key(pool: str) -> str:
    return f"{TASK_CHEST_POOL_PREFIX}{pool}"


def parse_chest_pool(raw: str | None) -> dict[int, int] | None:
    """Parse one integer-percentage weight row, or return ``None``.

    A pool is valid only when every key is a tier from 1 to 5, every value is
    an integer percentage from 0 to 100, and the weights sum to exactly 100.
    Missing tier keys count as zero so operators may omit empty tiers.
    """

    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    allowed = {str(tier) for tier in CHEST_BY_TIER}
    if not set(payload).issubset(allowed):
        return None
    weights: dict[int, int] = {tier: 0 for tier in CHEST_BY_TIER}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if not 0 <= value <= 100:
            return None
        weights[int(key)] = value
    if sum(weights.values()) != 100:
        return None
    return weights


def roll_chest_tier(
    weights: dict[int, int],
    *,
    rng: Callable[[int], int] | None = None,
) -> int:
    """Draw one tier from integer percentage weights summing to 100."""

    if not isinstance(weights, dict) or set(weights) != set(CHEST_BY_TIER):
        raise ValueError("chest pool must define tiers 1 to 5")
    total = 0
    for tier, weight in weights.items():
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise ValueError("chest pool weights must be integers")
        if weight < 0:
            raise ValueError("chest pool weights must not be negative")
        total += weight
    if total != 100:
        raise ValueError("chest pool weights must sum to 100")
    draw = rng or secrets.randbelow
    pick = int(draw(100))
    if not 0 <= pick < 100:
        raise ValueError("chest pool rng must return a value in [0, 100)")
    cumulative = 0
    for tier in sorted(CHEST_BY_TIER):
        cumulative += int(weights[tier])
        if pick < cumulative:
            return tier
    return max(CHEST_BY_TIER)  # pragma: no cover - sum is 100


def chest_pool_fallback(pool: str, *, source: str = "", difficulty: int = 0) -> dict[int, int]:
    """Return the conservative fallback weights for one pool."""

    if pool in CHEST_POOL_FALLBACKS:
        weights = CHEST_POOL_FALLBACKS[pool]
    else:
        weights = CHEST_POOL_FALLBACKS[chest_pool_for_task(source, difficulty)]
    return {tier: int(weights.get(tier, 0)) for tier in CHEST_BY_TIER}


def repair_condition() -> dict[str, Any]:
    """The system repair task succeeds once the missed date is repaired."""

    return {
        "op": "eq",
        "left": {"fn": "checkin_source", "args": [{"var": "task.missed_date"}]},
        "right": "repaired",
    }


def weekend_condition() -> dict[str, Any]:
    """Saturday plus Sunday must reach the shared XP target."""

    return {
        "op": "gte",
        "left": {
            "fn": "xp_between",
            "args": [
                {"var": "task.start"},
                {"var": "task.end"},
            ],
        },
        "right": WEEKEND_XP_TARGET,
    }


def repair_task_description(xp: int) -> str:
    return f"当天只拿到 {xp} XP；用余烬补上。"


def repair_task_title(missed_day: date) -> str:
    return f"补断联 · {missed_day.strftime('%m/%d')}"


def missed_date_from_system_key(system_key: str | None) -> date | None:
    if not system_key or not str(system_key).startswith("repair:"):
        return None
    raw = str(system_key).split(":", 1)[1]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _date_arg(value: Any) -> date:
    """Accept either an ISO date or an ISO local timestamp for DSL dates."""

    if isinstance(value, str) and "T" in value:
        return cal.parse_datetime(value).date()
    return cal.parse_date(value)


def _task_env(
    task: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, dict[str, Any]]:
    missed = missed_date_from_system_key(task.get("system_key"))
    if missed is None:
        missed = task.get("missed_date")

    def task_day(key: str) -> str | None:
        raw = task.get(key)
        if not raw:
            return None
        try:
            return _date_arg(raw).isoformat()
        except (TypeError, ValueError):
            return None

    return {
        "task": {
            "start": task_day("starts_at"),
            "end": task_day("ends_at"),
            "missed_date": missed.isoformat() if isinstance(missed, date) else missed,
        },
        "now": cal.iso_ts(now),
    }


def _require_keys(node: dict[str, Any], allowed: set[str]) -> None:
    if set(node) != allowed:
        raise ConditionError("unexpected condition fields")


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConditionError("comparison requires a number")
    return value


def _eval(
    node: Any,
    *,
    store: Any,
    user_id: str,
    env: dict[str, dict[str, Any]],
    depth: int,
    counter: list[int],
) -> Any:
    counter[0] += 1
    if counter[0] > MAX_DSL_NODES:
        raise ConditionError("condition node limit exceeded")
    if depth > MAX_DSL_DEPTH:
        raise ConditionError("condition depth limit exceeded")

    if isinstance(node, bool):
        raise ConditionError("boolean literals are not allowed")
    if isinstance(node, (int, str)):
        return node
    if not isinstance(node, dict):
        raise ConditionError("condition node must be an object or scalar")

    if "var" in node:
        _require_keys(node, {"var"})
        name = node["var"]
        if not isinstance(name, str) or name.count(".") != 1:
            raise ConditionError("unknown variable")
        namespace, field = name.split(".", 1)
        group = env.get(namespace)
        if group is None or field not in group:
            raise ConditionError(f"unknown variable: {name}")
        return group[field]

    if "fn" in node:
        _require_keys(node, {"fn", "args"})
        fn = node["fn"]
        args = node["args"]
        if not isinstance(args, list):
            raise ConditionError("function args must be a list")
        values = [
            _eval(
                arg,
                store=store,
                user_id=user_id,
                env=env,
                depth=depth + 1,
                counter=counter,
            )
            for arg in args
        ]
        if fn == "xp_between":
            if len(values) != 2:
                raise ConditionError("xp_between requires two arguments")
            try:
                start = _date_arg(values[0])
                end = _date_arg(values[1])
            except (TypeError, ValueError) as exc:
                raise ConditionError("xp_between requires ISO dates") from exc
            if end <= start:
                return 0
            return sum(
                int(value)
                for value in store.daily_xp_between(user_id, start, end).values()
            )
        if fn == "checkin_source":
            if len(values) != 1:
                raise ConditionError("checkin_source requires one argument")
            try:
                day = _date_arg(values[0])
            except (TypeError, ValueError) as exc:
                raise ConditionError("checkin_source requires an ISO date") from exc
            row = store.get_checkin(user_id, day)
            return "" if row is None else str(row["source"])
        raise ConditionError(f"unknown function: {fn}")

    op = node.get("op")
    if op in {"eq", "gte", "lte"}:
        _require_keys(node, {"op", "left", "right"})
        left = _eval(
            node["left"],
            store=store,
            user_id=user_id,
            env=env,
            depth=depth + 1,
            counter=counter,
        )
        right = _eval(
            node["right"],
            store=store,
            user_id=user_id,
            env=env,
            depth=depth + 1,
            counter=counter,
        )
        if op == "eq":
            return left == right
        if op == "gte":
            return _number(left) >= _number(right)
        return _number(left) <= _number(right)
    if op in {"and", "or"}:
        _require_keys(node, {"op", "args"})
        args = node["args"]
        if not isinstance(args, list) or not args:
            raise ConditionError("logical args must be a non-empty list")
        if op == "and":
            for arg in args:
                value = _eval(
                    arg,
                    store=store,
                    user_id=user_id,
                    env=env,
                    depth=depth + 1,
                    counter=counter,
                )
                if not isinstance(value, bool):
                    raise ConditionError("logical operands must be boolean")
                if not value:
                    return False
            return True
        for arg in args:
            value = _eval(
                arg,
                store=store,
                user_id=user_id,
                env=env,
                depth=depth + 1,
                counter=counter,
            )
            if not isinstance(value, bool):
                raise ConditionError("logical operands must be boolean")
            if value:
                return True
        return False
    if op == "not":
        _require_keys(node, {"op", "arg"})
        value = _eval(
            node["arg"],
            store=store,
            user_id=user_id,
            env=env,
            depth=depth + 1,
            counter=counter,
        )
        if not isinstance(value, bool):
            raise ConditionError("logical operand must be boolean")
        return not value
    raise ConditionError("unknown condition operation")


def evaluate_condition(
    condition: Any,
    *,
    store: Any,
    user_id: str,
    task: dict[str, Any],
    now: datetime,
) -> bool:
    """Evaluate one system-task condition, failing closed on any error."""

    if not isinstance(condition, dict):
        logger.warning("task condition is not an object; treating as false")
        return False
    try:
        value = _eval(
            condition,
            store=store,
            user_id=user_id,
            env=_task_env(task, now=now),
            depth=1,
            counter=[0],
        )
    except (ConditionError, TypeError, ValueError, KeyError) as exc:
        logger.warning("task condition rejected (%s); treating as false", exc)
        return False
    if not isinstance(value, bool):
        logger.warning("task condition did not produce a boolean; treating as false")
        return False
    return value


def condition_progress(
    condition: Any,
    *,
    store: Any,
    user_id: str,
    task: dict[str, Any],
    now: datetime,
) -> dict[str, int]:
    """Return the display progress for a DSL task.

    Only the two Ghost-authored condition shapes exist.  A weekend task shows
    the summed XP against 1000; a repair task shows 0/1 until the missed date
    has a repaired check-in.
    """

    if (
        isinstance(condition, dict)
        and condition.get("op") == "gte"
        and isinstance(condition.get("left"), dict)
        and condition["left"].get("fn") == "xp_between"
        and isinstance(condition.get("right"), int)
        and not isinstance(condition.get("right"), bool)
    ):
        target = int(condition["right"])
        try:
            start = _date_arg(task.get("starts_at"))
            end = _date_arg(task.get("ends_at"))
            current = sum(
                int(value)
                for value in store.daily_xp_between(user_id, start, end).values()
            )
        except (TypeError, ValueError):
            current = 0
        return {"current": current, "target": target}
    satisfied = evaluate_condition(
        condition,
        store=store,
        user_id=user_id,
        task=task,
        now=now,
    )
    return {"current": 1 if satisfied else 0, "target": 1}


__all__ = [
    "CHEST_BY_TIER",
    "CHEST_POOL_CHECKIN",
    "CHEST_POOL_DAILY_PREFIX",
    "CHEST_POOL_FALLBACKS",
    "CHEST_POOL_NAMES",
    "CHEST_POOL_REPAIR",
    "CHEST_POOL_WEEKEND",
    "CHEST_REWARD_BOOST",
    "CHEST_REWARD_DIAMONDS",
    "CHEST_REWARD_STAR",
    "CHEST_TIERS",
    "CHECKIN_CHEST_TIER",
    "CHECKIN_TASK_DESCRIPTION",
    "CHECKIN_TASK_SOURCE",
    "CHECKIN_TASK_TITLE",
    "ConditionError",
    "MANUAL_CHEST_POOL",
    "MANUAL_CHEST_TIER",
    "MAX_ACTIVE_TASK_DEFINITIONS",
    "MAX_DSL_DEPTH",
    "MAX_DSL_NODES",
    "REPAIR_CHEST_TIER",
    "REPAIR_LOOKBACK_DAYS",
    "REPAIR_XP_THRESHOLD",
    "TASK_CHEST_BOOST_CHANCE_KEY",
    "TASK_CHEST_BOOST_CUTOFF_HOUR_KEY",
    "TASK_CHEST_BOOST_MINUTES_KEY",
    "TASK_CHEST_POOL_PREFIX",
    "TASK_CHEST_STAR_CHANCE_KEY",
    "TASK_COMPLETION_MODES",
    "TASK_SOURCES",
    "TaskLimitReached",
    "TaskNotFound",
    "TaskStateRejected",
    "WEEKEND_CHEST_TIER",
    "WEEKEND_XP_TARGET",
    "checkin_condition",
    "chest_amount_range",
    "chest_pool_config_key",
    "chest_pool_fallback",
    "chest_pool_for_task",
    "condition_progress",
    "evaluate_condition",
    "missed_date_from_system_key",
    "parse_chest_pool",
    "repair_condition",
    "repair_task_description",
    "repair_task_title",
    "roll_chest_amount",
    "roll_chest_reward",
    "roll_chest_tier",
    "weekend_condition",
]
