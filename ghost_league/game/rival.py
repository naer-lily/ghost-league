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
from statistics import NormalDist
from typing import Final

from . import calendar as cal
from .rules import TIERS, GameError, group_quota

# Selection opens Monday 00:05 and closes at the end of Monday (Tuesday 00:00).
WEEK_SELECT_OPEN_OFFSET: Final = timedelta(minutes=5)
WEEK_LOCK_OFFSET: Final = timedelta(days=1)
AUTO_SELECT_OFFSET: Final = timedelta(days=1)

# Weekly bets share the Monday window.  Daily bets lock at 21:00 and settle at
# 22:30 local time so the result uses the evening check-in window.
WEEKLY_BET_LOCK_OFFSET: Final = timedelta(days=1)
DAILY_BET_LOCK_TIME: Final = time(21, 0)
DAILY_BET_SETTLE_TIME: Final = time(22, 30)

# Every bet carries this much free principal.  ``paid_stake`` is the part the
# caller pays from the diamond wallet, so the stored total is
# ``stake = FREE_BET_STAKE + paid_stake``.
MIN_PAID_STAKE: Final = 0
MAX_PAID_STAKE: Final = 500
FREE_BET_STAKE: Final = 20

GROUP_TARGET_RANK: Final = 3
GROUP_MARKETS: Final = ("top3", "promote", "no_demote")
GROUP_MARKET_LABELS: Final = {
    "top3": "押前三",
    "promote": "押升段",
    "no_demote": "押不降段",
}
# Group odds are deterministic and server-owned.  The fixed order is
# ``top3 > promote > no_demote``; rank/XP cushion only moves the magnitude.
GROUP_ODDS_MIN: Final = 1.1
GROUP_ODDS_MAX: Final = 8.0
GROUP_ODDS_STEP: Final = 0.1
GROUP_ODDS_XP_SCALE: Final = 80.0
GROUP_ODDS_EDGE_SCALE: Final = 0.12
GROUP_BET_SETTLE_OFFSET: Final = timedelta(minutes=5)

# Weekly target range: at most twice the rival's estimate, with a floor so the
# first screen always offers a few choices.
WEEKLY_TARGET_FLOOR: Final = 100
WEEKLY_TARGET_STEP: Final = 50

# Daily targets are priced from pure power, not from check-in history and not
# from a same-power-band prior.  Power is the expected daily XP; the spread is
# proportional to it with a floor so weak players still get a usable line.
DAILY_POWER_SIGMA_RATIO: Final = 1.0
DAILY_POWER_SIGMA_FLOOR: Final = 120.0
# The daily screen displays a fixed odds axis; the server inverts each price to
# the XP margin needed for that payout.  ``expected_xp`` previews the total XP
# at the rival's power plus the margin.
DAILY_ODDS_AXIS: Final[tuple[float, ...]] = (2.0, 3.0, 4.0, 5.0)
DAILY_EXPECTED_XP_STEP: Final = 10
# Daily bets are the small, frequent loop; weekly and group bets keep the
# larger 500-diamond cap.
DAILY_MAX_PAID_STAKE: Final = 100

# Weekly odds are fixed when the bet is placed.  Weekly uses the rival's
# estimated XP, floored, then adjusted for the current power gap.  Daily odds
# are the fixed display axis above, not a recomputed survival probability.
WEEKLY_REFERENCE_FLOOR: Final = 500
POWER_RATIO_MIN: Final = 0.5
POWER_RATIO_MAX: Final = 2.0
POWER_GAP_SCALE: Final = 4000

# Weekly dynamic target anchor.  The player's power gap scales the middle of
# the target range between 0.5x and 1.5x, so a stronger player is offered
# higher margins than a weaker one on the same rival estimate.  The remaining
# options interpolate between 0, the anchor, and the upper bound.
POWER_ANCHOR_MIN: Final = 0.5
POWER_ANCHOR_MAX: Final = 1.5
TARGET_ANCHOR_RATIO: Final = 0.5
TARGET_OPTION_INTERVALS: Final = 3
ODDS_MIN: Final = 1.2
ODDS_MAX: Final = 15.0
ODDS_BASE: Final = 1.2
ODDS_SLOPE: Final = 0.8
ODDS_EXPONENT: Final = 1.4

# Projection constants.  These only shape the betting-screen estimate; final
# settlement always uses the real weekly/daily XP.
PROJECTION_POWER_SCALE: Final = 2000
PROJECTION_WEEK_STEP: Final = 100

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


def group_market_threshold(market: str, group_size: int) -> int:
    """Return the inclusive rank threshold for one group market.

    ``top3`` is always rank 3 (a smaller group simply cannot place anybody
    outside it).  ``promote`` is the top 30% quota and ``no_demote`` is the
    last rank that stays above the bottom 30% quota.
    """

    if market not in GROUP_MARKETS:
        raise ValueError(f"unknown group market: {market}")
    if isinstance(group_size, bool) or not isinstance(group_size, int):
        raise TypeError("group_size must be an integer")
    if group_size < 0:
        raise ValueError("group_size must be non-negative")
    if market == "top3":
        return GROUP_TARGET_RANK
    quota = group_quota(group_size)
    if market == "promote":
        return quota
    return max(0, group_size - quota)


def group_market_allowed(market: str, tier: str) -> bool:
    """Return whether a tier may place this group market at all."""

    if market not in GROUP_MARKETS:
        raise ValueError(f"unknown group market: {market}")
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    if market == "promote":
        return tier != TIERS[-1]
    if market == "no_demote":
        return tier != TIERS[0]
    return True


def group_market_won(
    market: str,
    *,
    rank: int,
    group_size: int,
    tier: str,
) -> bool:
    """Judge one settled group bet by the player's final group rank."""

    if market not in GROUP_MARKETS:
        raise ValueError(f"unknown group market: {market}")
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    if rank < 1 or rank > group_size:
        raise ValueError("rank must be within the group")
    if market == "top3":
        return rank <= GROUP_TARGET_RANK
    quota = group_quota(group_size)
    if market == "promote":
        return rank <= quota and tier != TIERS[-1]
    return rank <= group_size - quota and tier != TIERS[0]


def _group_market_raw_odds(
    market: str,
    *,
    group_size: int,
    rank: int,
    xp_gap: float,
) -> float:
    """Deterministic single-market odds before enforcing the fixed order."""

    threshold = min(group_market_threshold(market, group_size), group_size)
    hardness = (group_size - threshold) / max(1, group_size - 1)
    premium = {"top3": 0.18, "promote": 0.09, "no_demote": 0.0}[market]
    base = 1.2 + 6.0 * hardness + premium
    edge = (threshold - rank) + (xp_gap / GROUP_ODDS_XP_SCALE)
    factor = math.exp(-GROUP_ODDS_EDGE_SCALE * edge)
    return base * factor


def _clamp_group_odds(value: float) -> float:
    return max(GROUP_ODDS_MIN, min(GROUP_ODDS_MAX, value))


def group_market_odds_table(
    *,
    group_size: int,
    rank: int,
    xp_gaps: dict[str, int] | None = None,
) -> dict[str, float]:
    """Return all three group-market odds, ordered by difficulty.

    ``xp_gaps`` maps a market to the player's current XP cushion over the
    first rank outside that market (negative when they are currently outside).
    The server computes this once and the frontend only displays it.  No
    randomness is involved, and ``top3`` is always priced above ``promote``,
    which is always above ``no_demote``.
    """

    if isinstance(group_size, bool) or not isinstance(group_size, int):
        raise TypeError("group_size must be an integer")
    if group_size < 1:
        raise ValueError("group_size must be positive")
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise TypeError("rank must be an integer")
    if rank < 1 or rank > group_size:
        raise ValueError("rank must be within the group")
    gaps = xp_gaps or {}
    raw = {
        market: _group_market_raw_odds(
            market,
            group_size=group_size,
            rank=rank,
            xp_gap=float(gaps.get(market, 0)),
        )
        for market in GROUP_MARKETS
    }
    no_demote = _clamp_group_odds(raw["no_demote"])
    promote = _clamp_group_odds(
        max(raw["promote"], no_demote + GROUP_ODDS_STEP)
    )
    top3 = _clamp_group_odds(max(raw["top3"], promote + GROUP_ODDS_STEP))
    if top3 < promote + GROUP_ODDS_STEP:
        # Both raw prices hit the upper clamp; refit downward so the fixed
        # difficulty order still holds.
        top3 = GROUP_ODDS_MAX
        promote = GROUP_ODDS_MAX - GROUP_ODDS_STEP
        no_demote = min(no_demote, GROUP_ODDS_MAX - 2 * GROUP_ODDS_STEP)
    return {
        "top3": round(top3, 2),
        "promote": round(promote, 2),
        "no_demote": round(no_demote, 2),
    }


def group_market_odds(
    market: str,
    *,
    group_size: int,
    rank: int,
    xp_gaps: dict[str, int] | None = None,
) -> float:
    """Return one market's deterministic odds."""

    return group_market_odds_table(
        group_size=group_size, rank=rank, xp_gaps=xp_gaps
    )[market]


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


def weekly_target_upper_bound(rival_week_estimate: int) -> int:
    """Largest weekly target margin offered for this rival estimate."""

    return max(
        WEEKLY_TARGET_FLOOR,
        round_to_step(max(0, int(rival_week_estimate)) * 2, WEEKLY_TARGET_STEP),
    )


def target_upper_bound(
    kind: str,
    rival_week_estimate: int = 0,
    rival_today_estimate: int = 0,
) -> int:
    """Return the inclusive upper bound for one bet kind.

    Daily targets are no longer an interval: they are the discrete tiers
    produced by :func:`daily_target_margins`.  ``rival_today_estimate`` is kept
    in the signature only so older weekly callers do not break.
    """

    if kind == "weekly":
        return weekly_target_upper_bound(rival_week_estimate)
    if kind == "daily":
        raise ValueError("daily targets use daily_target_margins()")
    raise ValueError(f"unsupported bet kind: {kind}")


def target_step(kind: str) -> int:
    """Return the widening step used by one bet kind's target options."""

    if kind == "weekly":
        return WEEKLY_TARGET_STEP
    if kind == "daily":
        raise ValueError("daily targets use daily_target_options()")
    raise ValueError(f"unsupported bet kind: {kind}")


def daily_power_sigma(mu: float) -> float:
    """Return the daily XP spread for one player's power-based mean."""

    return max(
        DAILY_POWER_SIGMA_FLOOR,
        max(0.0, float(mu)) * DAILY_POWER_SIGMA_RATIO,
    )


def daily_power_distribution(
    my_power: int,
    rival_power: int,
) -> tuple[float, float, float, float]:
    """Return ``(mu_me, sigma_me, mu_rival, sigma_rival)`` from pure power.

    Power is both the expected daily XP and the scale for its spread.  This
    path reads no check-in history and no power-band distribution, so two
    players' daily lines depend only on the powers shown on screen.
    """

    mu_me = max(0.0, float(my_power))
    mu_rival = max(0.0, float(rival_power))
    sigma_me = daily_power_sigma(mu_me)
    sigma_rival = daily_power_sigma(mu_rival)
    return mu_me, sigma_me, mu_rival, sigma_rival


def daily_distribution_parameters(
    mu_me: float,
    sd_me: float,
    mu_rival: float,
    sd_rival: float,
) -> tuple[float, float]:
    """Return ``(muD, sigmaD)`` for ``D = my XP - rival XP``."""

    mu_diff = float(mu_me) - float(mu_rival)
    sigma_diff = math.sqrt(
        max(0.0, float(sd_me)) ** 2 + max(0.0, float(sd_rival)) ** 2
    )
    return mu_diff, sigma_diff


def daily_margin_for_odds(
    odds: float,
    mu_diff: float,
    sigma_diff: float,
) -> int:
    """Return the XP margin needed to win a daily bet at ``odds``.

    ``p = 1 / odds`` is the displayed win probability and ``z`` is the normal
    quantile of ``1 - p``.  The margin is at least the narrow-win line ``1``.
    """

    price = float(odds)
    if price <= 1.0:
        raise ValueError("daily odds must be greater than 1")
    probability = 1.0 / price
    z_score = NormalDist().inv_cdf(1.0 - probability)
    raw = float(mu_diff) + z_score * max(0.0, float(sigma_diff))
    return max(1, math.ceil(raw))


def daily_expected_xp(mu_rival: float, margin: int) -> int:
    """Estimated total XP for a daily tier: rival mean plus the margin.

    This is the rival's projected daily XP plus the required gap, not the
    caller's current XP and not a live estimate.
    """

    return round_to_step(
        float(mu_rival) + int(margin), DAILY_EXPECTED_XP_STEP
    )


def daily_target_options(
    mu_me: float,
    sd_me: float,
    mu_rival: float,
    sd_rival: float,
) -> list[dict[str, float | int]]:
    """Return the fixed daily odds axis with its inverted target margins.

    Each option stores the displayed ``odds``, the XP ``margin`` needed to win
    at that price, and the projected total ``expected_xp``.  Options are sorted
    by odds.  A degenerate spread can map two prices to the same raw margin;
    the later margin is bumped by one XP so every price stays selectable and
    the displayed margins remain strictly increasing.
    """

    mu_diff, sigma_diff = daily_distribution_parameters(
        mu_me, sd_me, mu_rival, sd_rival
    )
    options: list[dict[str, float | int]] = []
    previous_margin = 0
    for odds in DAILY_ODDS_AXIS:
        margin = daily_margin_for_odds(odds, mu_diff, sigma_diff)
        margin = max(margin, previous_margin + 1)
        previous_margin = margin
        options.append(
            {
                "odds": float(odds),
                "margin": margin,
                "expected_xp": daily_expected_xp(mu_rival, margin),
            }
        )
    return options


def daily_target_margins(
    mu_me: float,
    sd_me: float,
    mu_rival: float,
    sd_rival: float,
) -> list[int]:
    """Compatibility helper: margins of :func:`daily_target_options`."""

    return [
        int(option["margin"])
        for option in daily_target_options(mu_me, sd_me, mu_rival, sd_rival)
    ]


def power_anchor_factor(my_power: int, rival_power: int) -> float:
    """Scale the dynamic target anchor by the power gap, clamped to 0.5–1.5.

    Equal power gives 1.0; being stronger raises the factor and being weaker
    lowers it, independently of the rival's XP estimate.
    """

    delta = int(my_power) - int(rival_power)
    raw = 1 + delta / POWER_GAP_SCALE
    return max(POWER_ANCHOR_MIN, min(POWER_ANCHOR_MAX, raw))


def target_anchor(
    kind: str,
    rival_week_estimate: int = 0,
    rival_today_estimate: int = 0,
    my_power: int = 0,
    rival_power: int = 0,
) -> int:
    """Return the dynamic middle weekly target.

    The upper bound follows the rival's estimate; the power factor moves the
    anchor between a quarter and three quarters of that range.  The result is
    clamped to ``0..weekly_target_upper_bound()`` and rounded to the weekly
    step.  ``rival_today_estimate`` is accepted only for older callers.
    """

    if kind != "weekly":
        raise ValueError("daily targets use daily_target_margins()")
    limit = weekly_target_upper_bound(rival_week_estimate)
    step = WEEKLY_TARGET_STEP
    factor = power_anchor_factor(my_power, rival_power)
    raw = limit * TARGET_ANCHOR_RATIO * factor
    return max(0, min(limit, round_to_step(raw, step)))


def target_in_range(
    kind: str,
    target_margin: int,
    rival_week_estimate: int = 0,
    rival_today_estimate: int = 0,
) -> bool:
    """True when a weekly ``target_margin`` is inside the offered range.

    Daily bets validate against the projection's discrete
    ``daily_target_margins`` instead.
    """

    if isinstance(target_margin, bool) or not isinstance(target_margin, int):
        return False
    if kind != "weekly":
        raise ValueError("daily targets use daily_target_margins()")
    return 0 <= target_margin <= weekly_target_upper_bound(rival_week_estimate)


def odds_reference(
    kind: str,
    rival_week_estimate: int = 0,
    rival_today_estimate: int = 0,
) -> int:
    """Floored weekly reference XP used by the odds formula."""

    if kind != "weekly":
        raise ValueError("daily odds use daily_target_options()")
    return max(WEEKLY_REFERENCE_FLOOR, int(rival_week_estimate))


def power_ratio(my_power: int, rival_power: int) -> float:
    """Scale the reference by the power gap, clamped to 0.5–2.0."""

    raw = 1 + (int(rival_power) - int(my_power)) / POWER_GAP_SCALE
    return max(POWER_RATIO_MIN, min(POWER_RATIO_MAX, raw))


def bet_odds(
    kind: str,
    target_margin: int,
    rival_week_estimate: int = 0,
    rival_today_estimate: int = 0,
    my_power: int = 0,
    rival_power: int = 0,
) -> float:
    """Return the fixed weekly odds for one target margin.

    ``odds = clamp(1.2, 15.0, 1.2 + 0.8 * (target / effective_reference) ** 1.4)``
    where ``effective_reference = reference * power_ratio``.  The function is
    monotonically non-decreasing in ``target_margin`` and rounds to 2 decimals.
    Daily bets use :func:`daily_target_options` instead.
    """

    if kind != "weekly":
        raise ValueError("daily odds use daily_target_options()")
    reference = odds_reference(kind, rival_week_estimate)
    effective_reference = reference * power_ratio(my_power, rival_power)
    ratio = max(0, int(target_margin)) / effective_reference
    raw = ODDS_BASE + ODDS_SLOPE * ratio**ODDS_EXPONENT
    return round(max(ODDS_MIN, min(ODDS_MAX, raw)), 2)


def target_options(
    kind: str,
    rival_week_estimate: int = 0,
    rival_today_estimate: int = 0,
    my_power: int = 0,
    rival_power: int = 0,
) -> list[dict[str, float | int]]:
    """Return sorted weekly preview options with their fixed odds.

    The list always contains 0, the dynamic power-aware anchor, and the range
    upper bound.  Intermediate points interpolate between 0 and the anchor and
    between the anchor and the upper bound.  Margins are unique, strictly
    increasing, and inside ``0..weekly_target_upper_bound()``.  ``daily`` uses
    :func:`daily_target_options` and its discrete, always-positive tiers.
    """

    if kind != "weekly":
        raise ValueError("daily targets use daily_target_options()")
    limit = weekly_target_upper_bound(rival_week_estimate)
    step = WEEKLY_TARGET_STEP
    anchor = target_anchor(
        kind,
        rival_week_estimate,
        rival_today_estimate,
        my_power,
        rival_power,
    )
    margins = {0, anchor, limit}
    for index in range(1, TARGET_OPTION_INTERVALS):
        share = index / TARGET_OPTION_INTERVALS
        below = round_to_step(anchor * share, step)
        above = round_to_step(anchor + (limit - anchor) * share, step)
        margins.add(max(0, min(limit, below)))
        margins.add(max(0, min(limit, above)))
    return [
        {
            "margin": margin,
            "odds": bet_odds(
                kind,
                margin,
                rival_week_estimate,
                rival_today_estimate,
                my_power,
                rival_power,
            ),
        }
        for margin in sorted(margins)
        if 0 <= margin <= limit
    ]


def wager_result(diff: int, target_margin: int) -> str:
    """Outcome of a target-margin wager.

    Reaching the target wins, including a zero-margin tie.  An actual XP tie
    that falls short of a positive target is a push and refunds the paid part;
    everything else loses.
    """

    if int(diff) >= int(target_margin):
        return "won"
    if int(diff) == 0:
        return "void"
    return "lost"


def payout_for_win(stake: int, odds: float) -> int:
    """Payout for a winning wager: total principal × fixed odds, rounded."""

    return int(math.floor(float(stake) * float(odds) + 0.5))


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
    "DAILY_EXPECTED_XP_STEP",
    "DAILY_MAX_PAID_STAKE",
    "DAILY_ODDS_AXIS",
    "DAILY_POWER_SIGMA_FLOOR",
    "DAILY_POWER_SIGMA_RATIO",
    "FREE_BET_STAKE",
    "GROUP_BET_SETTLE_OFFSET",
    "GROUP_MARKETS",
    "GROUP_MARKET_LABELS",
    "GROUP_ODDS_MAX",
    "GROUP_ODDS_MIN",
    "GROUP_TARGET_RANK",
    "MAX_PAID_STAKE",
    "MIN_PAID_STAKE",
    "ODDS_BASE",
    "ODDS_EXPONENT",
    "ODDS_MAX",
    "ODDS_MIN",
    "ODDS_SLOPE",
    "OUTCOME_DRAW",
    "OUTCOME_LOSS",
    "OUTCOME_WIN",
    "POWER_ANCHOR_MAX",
    "POWER_ANCHOR_MIN",
    "POWER_GAP_SCALE",
    "POWER_RATIO_MAX",
    "POWER_RATIO_MIN",
    "PROJECTION_POWER_SCALE",
    "PROJECTION_WEEK_STEP",
    "RIVAL_DRAW_REWARD",
    "RIVAL_WIN_REWARD",
    "RivalError",
    "RivalNotFound",
    "RivalSelectionRejected",
    "RivalUnavailable",
    "RivalWindowClosed",
    "TARGET_ANCHOR_RATIO",
    "TARGET_OPTION_INTERVALS",
    "WEEKLY_REFERENCE_FLOOR",
    "WEEKLY_TARGET_FLOOR",
    "WEEKLY_TARGET_STEP",
    "WEEK_SELECT_OPEN_OFFSET",
    "auto_select_at",
    "bet_odds",
    "daily_bet_locks_at",
    "daily_bet_settles_at",
    "daily_distribution_parameters",
    "daily_expected_xp",
    "daily_margin_for_odds",
    "daily_power_distribution",
    "daily_power_sigma",
    "daily_target_margins",
    "daily_target_options",
    "group_bet_settles_at",
    "group_market_allowed",
    "group_market_odds",
    "group_market_odds_table",
    "group_market_threshold",
    "group_market_won",
    "odds_reference",
    "payout_for_win",
    "percentile_value",
    "power_anchor_factor",
    "power_ratio",
    "projected_week_xp",
    "rival_outcome",
    "rival_reward",
    "round_to_step",
    "selection_window_open",
    "target_anchor",
    "target_in_range",
    "target_options",
    "target_step",
    "target_upper_bound",
    "wager_result",
    "week_lock_at",
    "week_lock_display",
    "week_open_at",
    "weekly_bet_locks_at",
    "weekly_target_upper_bound",
]
