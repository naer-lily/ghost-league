"""Pure rival-selection and betting rules.

All wall-clock decisions are anchored to the Asia/Shanghai calendar helpers so
the store and the API can be tested with an explicit clock.  This module holds
no SQL and no wallet logic; it only defines the windows, prices, and errors
shared by the persistence layer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final

from . import calendar as cal
from .rules import GameError

# Selection opens Monday 00:05 and closes at the end of Monday (Tuesday 00:00).
WEEK_SELECT_OPEN_OFFSET: Final = timedelta(minutes=5)
WEEK_LOCK_OFFSET: Final = timedelta(days=1)
AUTO_SELECT_OFFSET: Final = timedelta(days=1)

# Weekly bets share the Monday window.  Daily bets lock at 20:00 and settle at
# 22:00 so the result never depends on late-night activity.
WEEKLY_BET_LOCK_OFFSET: Final = timedelta(days=1)
DAILY_BET_LOCK_HOUR: Final = 20
DAILY_BET_SETTLE_HOUR: Final = 22

WEEKLY_STAKES: Final[tuple[int, ...]] = (20, 40, 60)
WEEKLY_ODDS: Final = 2.0
DAILY_STAKE: Final = 20
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
    return cal.day_start_at(day) + timedelta(hours=DAILY_BET_LOCK_HOUR)


def daily_bet_settles_at(day: date | datetime | str) -> datetime:
    return cal.day_start_at(day) + timedelta(hours=DAILY_BET_SETTLE_HOUR)


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


__all__ = [
    "AUTO_POWER_BAND_MAX",
    "AUTO_POWER_BAND_MIN",
    "AUTO_SELECT_OFFSET",
    "BetAlreadyPlaced",
    "BetError",
    "BetRejected",
    "BetWindowClosed",
    "DAILY_BET_LOCK_HOUR",
    "DAILY_BET_SETTLE_HOUR",
    "DAILY_STAKE",
    "DAILY_TARGET_ODDS",
    "DAILY_TARGET_PAYOUTS",
    "OUTCOME_DRAW",
    "OUTCOME_LOSS",
    "OUTCOME_WIN",
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
    "rival_outcome",
    "rival_reward",
    "selection_window_open",
    "week_lock_at",
    "week_lock_display",
    "week_open_at",
    "weekly_bet_locks_at",
]
