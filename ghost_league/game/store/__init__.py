"""SQLite persistence for the game core.

All writes live behind :class:`GameStore` transactions.  Business modules call
these methods instead of assembling SQL.  The schema intentionally keeps only
the tables needed by the Phase 1 loop: no journal/audit mega-table.
"""

from __future__ import annotations

from ..rules import (
    CHECKIN_SECONDS,
    GROUP_SIZE,
    TIERS,
    DuplicateIdempotencyKey,
    GameError,
    PlayerNotFound,
    RepairRejected,
    WeekLocked,
    balanced_group_sizes,
    earned_embers_for_week,
    ember_grant_amount,
    group_movement,
    is_valid_repair_day,
    next_tier,
    rank_scores,
    xp_for_seconds,
)
from .activity import ActivityMixin
from .bets import BetsMixin
from .channel import ChannelMixin
from .checkins import CheckinsMixin
from .core import (
    ALGORITHM_VERSION,
    DEFAULT_DB_PATH,
    SCHEMA_VERSION,
    SOURCE_AI,
    SOURCE_CHANNEL,
    SOURCE_HUMAN,
    CoreMixin,
)
from .feed import FeedMixin
from .groups import GroupsMixin
from .history import (
    DEFAULT_HISTORY_LIMIT,
    HISTORY_TYPES,
    MAX_HISTORY_LIMIT,
    HistoryMixin,
)
from .job_runs import (
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    JobRunMixin,
)
from .players import PlayersMixin
from .power import (
    POWER_WEIGHTS,
    POWER_WINDOW_WEEKS,
    PowerMixin,
    compute_power_snapshot,
    power_from_percentile,
)
from .rival import RivalMixin
from ..rival import (
    BetAlreadyPlaced,
    BetError,
    BetRejected,
    BetWindowClosed,
    RivalError,
    RivalNotFound,
    RivalSelectionRejected,
    RivalUnavailable,
    RivalWindowClosed,
)
from .progression import (
    CATALOG_ITEMS,
    CATALOG_TITLES,
    ITEM_BY_ID,
    PROGRESSION_START_META,
    ProgressionMixin,
)
from ..stars import (
    RARITY_BY_TYPE,
    RARITY_LABELS,
    RARITY_TYPE_POOLS,
    RARITY_WEIGHTS,
    STAR_TYPES,
    TYPE_LABELS,
    TYPE_PALETTES,
    generate_star_name,
    make_star_visual,
    roll_star_rarity,
    roll_star_type,
    validate_star_name,
)
from .settlement import ScoreRowLike, SettlementMixin
from .shop import (
    CAP_ITEM_PREFIX,
    DIAMOND_CAP_MAX_LEVEL,
    DIAMOND_CAP_STEP,
    DIAMOND_DECAY_RATE_PER_HOUR,
    DIAMOND_INITIAL_BALANCE,
    DIAMOND_INITIAL_CAP,
    EMBER_ITEM_ID,
    EMBER_PURCHASE_QUANTITY,
    SEASONAL_STAR_ITEM_ID,
    STAR_ITEM_ID,
    STAR_NAME_MAX_LENGTH,
    STAR_PRICE_DIAMONDS,
    ShopMixin,
    compute_diamond_decay,
)


class GameStore(
    CoreMixin,
    PlayersMixin,
    ChannelMixin,
    GroupsMixin,
    ActivityMixin,
    CheckinsMixin,
    FeedMixin,
    ProgressionMixin,
    SettlementMixin,
    PowerMixin,
    ShopMixin,
    RivalMixin,
    BetsMixin,
    JobRunMixin,
    HistoryMixin,
):
    """Transactional access to one ``league.db`` file."""


__all__ = [
    "ALGORITHM_VERSION",
    "BetAlreadyPlaced",
    "BetError",
    "BetRejected",
    "BetWindowClosed",
    "CATALOG_ITEMS",
    "CATALOG_TITLES",
    "CHECKIN_SECONDS",
    "CAP_ITEM_PREFIX",
    "DEFAULT_DB_PATH",
    "DIAMOND_CAP_MAX_LEVEL",
    "DIAMOND_CAP_STEP",
    "DIAMOND_DECAY_RATE_PER_HOUR",
    "DIAMOND_INITIAL_BALANCE",
    "DIAMOND_INITIAL_CAP",
    "DEFAULT_HISTORY_LIMIT",
    "EMBER_ITEM_ID",
    "EMBER_PURCHASE_QUANTITY",
    "GROUP_SIZE",
    "HISTORY_TYPES",
    "ITEM_BY_ID",
    "JOB_STATUS_FAILED",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCEEDED",
    "MAX_HISTORY_LIMIT",
    "POWER_WEIGHTS",
    "POWER_WINDOW_WEEKS",
    "RARITY_BY_TYPE",
    "RARITY_LABELS",
    "RARITY_TYPE_POOLS",
    "RARITY_WEIGHTS",
    "PROGRESSION_START_META",
    "SCHEMA_VERSION",
    "SOURCE_AI",
    "SOURCE_CHANNEL",
    "SEASONAL_STAR_ITEM_ID",
    "SOURCE_HUMAN",
    "STAR_ITEM_ID",
    "STAR_NAME_MAX_LENGTH",
    "STAR_PRICE_DIAMONDS",
    "STAR_TYPES",
    "TYPE_LABELS",
    "TYPE_PALETTES",
    "TIERS",
    "DuplicateIdempotencyKey",
    "GameError",
    "GameStore",
    "PlayerNotFound",
    "RepairRejected",
    "RivalError",
    "RivalNotFound",
    "RivalSelectionRejected",
    "RivalUnavailable",
    "RivalWindowClosed",
    "ScoreRowLike",
    "WeekLocked",
    "balanced_group_sizes",
    "compute_diamond_decay",
    "compute_power_snapshot",
    "earned_embers_for_week",
    "generate_star_name",
    "ember_grant_amount",
    "group_movement",
    "is_valid_repair_day",
    "make_star_visual",
    "next_tier",
    "power_from_percentile",
    "rank_scores",
    "roll_star_rarity",
    "roll_star_type",
    "validate_star_name",
    "xp_for_seconds",
]
