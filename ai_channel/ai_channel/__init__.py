"""Account-backed AI channel simulator.

Ghost sees ordinary accounts and the public ``/v1/me/*`` API.  This package
owns AI identity, tokens, policy and the local simulation state; it never
writes Ghost's database and never calls private endpoints.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
