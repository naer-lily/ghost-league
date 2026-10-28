"""Tier icon theme registry shared by accounts and badge rendering.

The registry is intentionally data-only: adding a new theme means adding one
mapping entry here, adding the corresponding theme asset directory, and
extending the PWA renderer.  Unknown or legacy values are treated as the
default theme by every read path.
"""

from __future__ import annotations

DEFAULT_ICON_THEME = "classic"

# The value is the asset subdirectory beneath ``web/assets/tiers``.  Classic
# lives at the root; future styles get their own subdirectory without changing
# the account or badge APIs.
ICON_THEME_DIRECTORIES: dict[str, str] = {
    "classic": "",
    "material": "material",
}

ICON_THEMES: tuple[str, ...] = tuple(ICON_THEME_DIRECTORIES)


def normalize_icon_theme(value: object) -> str:
    """Validate a theme supplied by a writing caller."""

    if not isinstance(value, str) or value not in ICON_THEME_DIRECTORIES:
        allowed = ", ".join(ICON_THEMES)
        raise ValueError(f"icon_theme must be one of: {allowed}")
    return value


def icon_theme_or_default(value: object) -> str:
    """Coerce stored or projected values, including legacy invalid values."""

    if isinstance(value, str) and value in ICON_THEME_DIRECTORIES:
        return value
    return DEFAULT_ICON_THEME


__all__ = [
    "DEFAULT_ICON_THEME",
    "ICON_THEME_DIRECTORIES",
    "ICON_THEMES",
    "icon_theme_or_default",
    "normalize_icon_theme",
]
