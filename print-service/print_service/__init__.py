"""Standalone thermal-printer queue service.

The public entry point is :func:`print_service.app:create_app`.
"""

from .app import create_app

__all__ = ["create_app"]
__version__ = "0.1.0"
