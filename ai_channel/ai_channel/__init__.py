"""Account-backed Channel client for Ghost League.

Ghost sees ordinary accounts and the public ``/v1/me/*`` API.  This package
owns local tokens, policy and simulation state; it never writes Ghost's database
and never calls private endpoints.  The Waka source mode reads the existing
``waka_channel`` cache/projection library and sends the same events through the
matching ordinary account tokens.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
