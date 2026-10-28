"""Ghost League: a self-hosted, Channel-fed weekly activity league.

Ghost only consumes anonymous roster entries and hourly increments from a
Channel. Game state lives in SQLite; this package intentionally does not know
which Source produced the activity.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
