"""Ghost-owned time-limited tasks: chest tiers, DSL rules, and evaluation.

This module holds only pure rules plus the restricted JSON expression
evaluator.  It never writes XP or weekly scores.  All activity reads go back
through :class:`GameStore`'s daily resolver; task code must not rebuild a
check-in or Channel fallback.
"""

from __future__ import annotations

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
    {"tier": 2, "key": "copper", "name": "铜箱", "min": 6, "max": 10},
    {"tier": 3, "key": "silver", "name": "银箱", "min": 10, "max": 16},
    {"tier": 4, "key": "gold", "name": "金箱", "min": 18, "max": 28},
    {"tier": 5, "key": "star", "name": "星箱", "min": 30, "max": 48},
)
CHEST_BY_TIER: dict[int, dict[str, Any]] = {
    int(row["tier"]): row for row in CHEST_TIERS
}

MANUAL_CHEST_TIER: dict[int, int] = {1: 1, 2: 2, 3: 3}
REPAIR_CHEST_TIER = 1
WEEKEND_CHEST_TIER = 5
CHECKIN_CHEST_TIER = 1

CHECKIN_TASK_SOURCE = "checkin"
CHECKIN_TASK_TITLE = "每日打卡"
CHECKIN_TASK_DESCRIPTION = "画满 10 分钟，开个小宝箱。"
TASK_CHEST_BOOST_CHANCE_KEY = "task_chest_boost_chance"
TASK_CHEST_BOOST_MINUTES_KEY = "task_chest_boost_minutes"
CHEST_REWARD_DIAMONDS = "diamonds"
CHEST_REWARD_BOOST = "boost"

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
    rng: Callable[[int], int] | None = None,
) -> dict[str, Any]:
    """Roll one chest reward.

    ``boost_chance`` is an integer percentage.  Invalid or missing config is
    normalised to zero by the caller, so the chest still pays diamonds.  The
    returned mapping always has ``reward_type`` and ``boost_minutes``; boost
    rewards keep ``amount`` at zero so the API field stays an integer.
    """

    chest_amount_range(tier)
    try:
        chance = int(boost_chance)
        minutes = int(boost_minutes)
    except (TypeError, ValueError):
        chance, minutes = 0, 0
    if isinstance(boost_chance, bool) or isinstance(boost_minutes, bool):
        chance, minutes = 0, 0
    if not 0 <= chance <= 100 or minutes < 1:
        chance, minutes = 0, 0

    draw = rng or secrets.randbelow
    if chance and int(draw(100)) < chance:
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
    "CHEST_REWARD_BOOST",
    "CHEST_REWARD_DIAMONDS",
    "CHEST_TIERS",
    "CHECKIN_CHEST_TIER",
    "CHECKIN_TASK_DESCRIPTION",
    "CHECKIN_TASK_SOURCE",
    "CHECKIN_TASK_TITLE",
    "ConditionError",
    "MANUAL_CHEST_TIER",
    "MAX_ACTIVE_TASK_DEFINITIONS",
    "MAX_DSL_DEPTH",
    "MAX_DSL_NODES",
    "REPAIR_CHEST_TIER",
    "REPAIR_LOOKBACK_DAYS",
    "REPAIR_XP_THRESHOLD",
    "TASK_CHEST_BOOST_CHANCE_KEY",
    "TASK_CHEST_BOOST_MINUTES_KEY",
    "TASK_COMPLETION_MODES",
    "TASK_SOURCES",
    "TaskLimitReached",
    "TaskNotFound",
    "TaskStateRejected",
    "WEEKEND_CHEST_TIER",
    "WEEKEND_XP_TARGET",
    "checkin_condition",
    "chest_amount_range",
    "condition_progress",
    "evaluate_condition",
    "missed_date_from_system_key",
    "repair_condition",
    "repair_task_description",
    "repair_task_title",
    "roll_chest_amount",
    "roll_chest_reward",
    "weekend_condition",
]
