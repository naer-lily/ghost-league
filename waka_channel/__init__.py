"""Independent WakaTime -> Ghost Channel.

This package owns WakaTime snapshot reading, p75 winsorization, stable anonymous
identity, hourly projection and the Ghost Channel HTTP client.  Ghost never
imports it, and it only borrows Ghost's pure normalization/schedule math.
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
