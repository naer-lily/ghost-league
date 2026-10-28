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
from .players import PlayersMixin
from .progression import (
    CATALOG_ITEMS,
    CATALOG_TITLES,
    ITEM_BY_ID,
    PROGRESSION_START_META,
    ProgressionMixin,
)
from .settlement import ScoreRowLike, SettlementMixin


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
):
    """Transactional access to one ``league.db`` file."""


__all__ = [
    "ALGORITHM_VERSION",
    "CATALOG_ITEMS",
    "CATALOG_TITLES",
    "CHECKIN_SECONDS",
    "DEFAULT_DB_PATH",
    "GROUP_SIZE",
    "ITEM_BY_ID",
    "PROGRESSION_START_META",
    "SCHEMA_VERSION",
    "SOURCE_AI",
    "SOURCE_CHANNEL",
    "SOURCE_HUMAN",
    "TIERS",
    "DuplicateIdempotencyKey",
    "GameError",
    "GameStore",
    "PlayerNotFound",
    "RepairRejected",
    "ScoreRowLike",
    "WeekLocked",
    "balanced_group_sizes",
    "earned_embers_for_week",
    "ember_grant_amount",
    "group_movement",
    "is_valid_repair_day",
    "next_tier",
    "rank_scores",
    "xp_for_seconds",
]
