"""Independent WakaTime source/projection library.

This package owns WakaTime snapshot reading, p75 winsorization, stable anonymous
identity and hourly projection.  The account-backed XP transport lives in
``ai_channel --source waka``; the Channel HTTP client and CLI here remain for the
legacy ingest path and manual diagnostics.  Ghost never imports this package,
and it only borrows Ghost's pure normalization/schedule math.
"""

from .client import (
    ChannelClient,
    ChannelHTTPError,
    ChannelTransportError,
    WakaClient,
)
from .identity import CHANNEL_ID, CHANNEL_NAMESPACE, player_ref
from .projection import (
    HourlyIncrement,
    TickPlan,
    hourly_increments,
    make_event_id,
    tick_increments,
)
from .roster import (
    SourceRow,
    build_roster,
    effective_targets,
    roster_from_cache,
    rows_from_cache,
)
from .state import ChannelState

__all__ = [
    "CHANNEL_ID",
    "CHANNEL_NAMESPACE",
    "ChannelClient",
    "ChannelHTTPError",
    "ChannelState",
    "ChannelTransportError",
    "HourlyIncrement",
    "SourceRow",
    "TickPlan",
    "WakaClient",
    "build_roster",
    "effective_targets",
    "hourly_increments",
    "make_event_id",
    "player_ref",
    "roster_from_cache",
    "rows_from_cache",
    "tick_increments",
]
