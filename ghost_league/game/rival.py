"""Pure rival-selection and betting rules.

All wall-clock decisions are anchored to the Asia/Shanghai calendar helpers so
the store and the API can be tested with an explicit clock.  This module holds
no SQL and no wallet logic; it only defines the windows, prices, and errors
shared by the persistence layer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Final

from . import calendar as cal
from .rules import GameError

# Selection opens Monday 00:05 and closes at the end of Monday (Tuesday 00:00).
WEEK_SELECT_OPEN_OFFSET: Final = timedelta(minutes=5)
WEEK_LOCK_OFFSET: Final = timedelta(days=1)
AUTO_SELECT_OFFSET: Final = timedelta(days=1)

# Weekly bets share the Monday window.  Daily bets lock at 21:00 and settle at
# 22:30 local time so the result uses the evening check-in window.
WEEKLY_BET_LOCK_OFFSET: Final = timedelta(days=1)
DAILY_BET_LOCK_TIME: Final = time(21, 0)
DAILY_BET_SETTLE_TIME: Final = time(22, 30)

WEEKLY_STAKES: Final[tuple[int, ...]] = (20, 40, 60)
WEEKLY_ODDS: Final = 2.0
GROUP_STAKES: Final[tuple[int, ...]] = (20, 40, 60)
GROUP_ODDS: Final = 2.0
GROUP_BET_SETTLE_OFFSET: Final = timedelta(minutes=5)
DAILY_STAKE: Final = 20
# Every bet carries this much free principal; only the remainder is debited.
FREE_BET_STAKE: Final = 20
DAILY_TARGET_ODDS: Final[dict[int, float]] = {
    50: 1.5,
    150: 2.5,
    300: 4.0,
}
DAILY_TARGET_PAYOUTS: Final[dict[int, int]] = {
    50: 30,
    150: 50,
    300: 80,
}

# Projection constants.  These only shape the betting-screen estimate; final
# settlement always uses the real weekly/daily XP.
PROJECTION_POWER_SCALE: Final = 2000
PROJECTION_WEEK_STEP: Final = 100
PROJECTION_DAY_STEP: Final = 10
# Extrapolate to the 22:30 daily settlement cutoff, expressed in hours.
PROJECTION_DAY_WINDOW_HOURS: Final = (
    DAILY_BET_SETTLE_TIME.hour + DAILY_BET_SETTLE_TIME.minute / 60
)
PROJECTION_MIN_DAY_RATIO: Final = 0.2
DAILY_PROJECTION_TARGETS: Final[tuple[int, ...]] = (50, 150, 300)

RIVAL_WIN_REWARD: Final = 120
RIVAL_DRAW_REWARD: Final = 40

AUTO_POWER_BAND_MIN: Final = 60
AUTO_POWER_BAND_MAX: Final = 240

OUTCOME_WIN: Final = "win"
OUTCOME_LOSS: Final = "loss"
OUTCOME_DRAW: Final = "draw"


class RivalError(GameError):
    """Expected, player-readable rival rule failure."""

    code = "rival_error"


class RivalWindowClosed(RivalError):
    code = "window_closed"

    def __init__(self, message: str = "宿敌选择已关闭") -> None:
        super().__init__(message)


class RivalNotFound(RivalError):
    code = "candidate_not_found"

    def __init__(self, message: str = "候选不存在") -> None:
        super().__init__(message)


class RivalSelectionRejected(RivalError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.detail = message


class RivalUnavailable(RivalError):
    code = "no_rival"

    def __init__(self, message: str = "本周还没有宿敌，暂时不能下注") -> None:
        super().__init__(message)


class BetError(GameError):
    """Expected, player-readable betting rule failure."""

    code = "bet_error"


class BetWindowClosed(BetError):
    code = "window_closed"

    def __init__(self, message: str = "下注已截止") -> None:
        super().__init__(message)


class BetAlreadyPlaced(BetError):
    code = "already_placed"

    def __init__(self, message: str = "本期已经下注") -> None:
        super().__init__(message)


class BetRejected(BetError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.detail = message


def week_open_at(week: date | datetime | str) -> datetime:
    return cal.week_start_at(week) + WEEK_SELECT_OPEN_OFFSET


def week_lock_at(week: date | datetime | str) -> datetime:
    """Exclusive upper bound: Tuesday 00:00 local time."""

    return cal.week_start_at(week) + WEEK_LOCK_OFFSET


def week_lock_display(week: date | datetime | str) -> datetime:
    """Human-facing lock instant: Monday 23:59:59 local time."""

    return week_lock_at(week) - timedelta(seconds=1)


def auto_select_at(week: date | datetime | str) -> datetime:
    return cal.week_start_at(week) + AUTO_SELECT_OFFSET


def weekly_bet_locks_at(week: date | datetime | str) -> datetime:
    return cal.week_start_at(week) + WEEKLY_BET_LOCK_OFFSET


def daily_bet_locks_at(day: date | datetime | str) -> datetime:
    return cal.day_time_at(day, DAILY_BET_LOCK_TIME)


def daily_bet_settles_at(day: date | datetime | str) -> datetime:
    return cal.day_time_at(day, DAILY_BET_SETTLE_TIME)


def group_bet_settles_at(week: date | datetime | str) -> datetime:
    """Group bets settle with the next Monday 00:05 settlement pass."""

    return cal.week_end_at(week) + GROUP_BET_SETTLE_OFFSET


def selection_window_open(
    now: date | datetime | str,
    week: date | datetime | str,
) -> bool:
    local_now = cal.parse_datetime(now) if not isinstance(now, datetime) else now
    return week_open_at(week) <= local_now < week_lock_at(week)


def rival_outcome(my_xp: int, rival_xp: int) -> str:
    if my_xp > rival_xp:
        return OUTCOME_WIN
    if my_xp < rival_xp:
        return OUTCOME_LOSS
    return OUTCOME_DRAW


def rival_reward(outcome: str, *, is_human: bool) -> int:
    if not is_human:
        return 0
    if outcome == OUTCOME_WIN:
        return RIVAL_WIN_REWARD
    if outcome == OUTCOME_DRAW:
        return RIVAL_DRAW_REWARD
    return 0


def round_to_step(value: float, step: int) -> int:
    """Round a non-negative estimate to the nearest multiple of ``step``."""

    if step <= 0:
        raise ValueError("step must be positive")
    if value <= 0:
        return 0
    return int(value / step + 0.5) * step


def percentile_value(values: Sequence[int], percentile: float) -> float:
    """Linear-interpolated quantile over an unweighted XP distribution."""

    if not values:
        return 0.0
    clamped = max(0.0, min(1.0, float(percentile)))
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = clamped * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def projected_week_xp(
    rival_power: int,
    settled_xps: Sequence[int],
    current_week_xp: int,
) -> int:
    """Estimate the rival's final week XP from power and a settled week.

    ``rival_power / 2000`` is the percentile.  The most recent settled week's
    XP distribution supplies the matching quantile; without one, this falls
    back to the rival's current-week XP.  The result is rounded to hundreds.
    """

    if settled_xps:
        percentile = max(0.0, float(rival_power) / PROJECTION_POWER_SCALE)
        raw = percentile_value(settled_xps, percentile)
    else:
        raw = float(current_week_xp)
    return round_to_step(raw, PROJECTION_WEEK_STEP)


def projected_today_xp(today_xp: int, now: datetime) -> int:
    """Extrapolate today's XP to the 22:30 cutoff, rounded to tens.

    The elapsed fraction is measured against the 22.5-hour window and clamped
    to at least 20% so a very early single event does not explode the estimate.
    """

    if today_xp <= 0:
        return 0
    local_now = cal.as_local(now)
    elapsed = (local_now - cal.day_start_at(local_now.date())).total_seconds()
    ratio = elapsed / (PROJECTION_DAY_WINDOW_HOURS * 3600)
    ratio = max(PROJECTION_MIN_DAY_RATIO, min(1.0, ratio))
    return round_to_step(today_xp / ratio, PROJECTION_DAY_STEP)


__all__ = [
    "AUTO_POWER_BAND_MAX",
    "AUTO_POWER_BAND_MIN",
    "AUTO_SELECT_OFFSET",
    "BetAlreadyPlaced",
    "BetError",
    "BetRejected",
    "BetWindowClosed",
    "DAILY_BET_LOCK_TIME",
    "DAILY_BET_SETTLE_TIME",
    "DAILY_PROJECTION_TARGETS",
    "DAILY_STAKE",
    "DAILY_TARGET_ODDS",
    "DAILY_TARGET_PAYOUTS",
    "FREE_BET_STAKE",
    "GROUP_BET_SETTLE_OFFSET",
    "GROUP_ODDS",
    "GROUP_STAKES",
    "OUTCOME_DRAW",
    "OUTCOME_LOSS",
    "OUTCOME_WIN",
    "PROJECTION_DAY_STEP",
    "PROJECTION_DAY_WINDOW_HOURS",
    "PROJECTION_MIN_DAY_RATIO",
    "PROJECTION_POWER_SCALE",
    "PROJECTION_WEEK_STEP",
    "RIVAL_DRAW_REWARD",
    "RIVAL_WIN_REWARD",
    "RivalError",
    "RivalNotFound",
    "RivalSelectionRejected",
    "RivalUnavailable",
    "RivalWindowClosed",
    "WEEKLY_ODDS",
    "WEEKLY_STAKES",
    "WEEK_SELECT_OPEN_OFFSET",
    "auto_select_at",
    "daily_bet_locks_at",
    "daily_bet_settles_at",
    "group_bet_settles_at",
    "percentile_value",
    "projected_today_xp",
    "projected_week_xp",
    "rival_outcome",
    "rival_reward",
    "round_to_step",
    "selection_window_open",
    "week_lock_at",
    "week_lock_display",
    "week_open_at",
    "weekly_bet_locks_at",
]
