"""Local configuration for the account-backed AI channel.

The config file is local secret material: it contains the highly privileged
provisioning token.  Never print it, commit it, or put it in examples.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "http://127.0.0.1:8095"
DEFAULT_STATE_DB = "ai_channel/data/ai_accounts.db"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_SECONDS = 900
PROVISIONING_TOKEN_ENV = "AI_CHANNEL_PROVISIONING_TOKEN"
BASE_URL_ENV = "AI_CHANNEL_BASE_URL"


@dataclass(frozen=True)
class ChannelConfig:
    """Validated runtime settings for one AI channel instance."""

    base_url: str
    provisioning_token: str
    state_db: Path
    request_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    default_seconds: int = DEFAULT_SECONDS


def _positive_number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive number")
    number = float(value)
    if number <= 0 or number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be a positive number")
    return number


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_base_url(value: Any) -> str:
    """Return a normalized absolute http(s) base URL or raise ValueError."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("base_url must be an absolute http/https URL")
    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("base_url must use http or https")
    if not parsed.netloc:
        raise ValueError("base_url must be absolute and include a host")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not include a query or fragment")
    return cleaned


def load_config(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
) -> ChannelConfig:
    """Read and validate ``config.json``, applying documented env overrides."""

    config_path = Path(path)
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read config {config_path}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"invalid JSON in config {config_path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("config must be a JSON object")

    source: dict[str, Any] = dict(loaded)
    environment = os.environ if env is None else env
    if BASE_URL_ENV in environment:
        source["base_url"] = environment[BASE_URL_ENV]
    if PROVISIONING_TOKEN_ENV in environment:
        source["provisioning_token"] = environment[PROVISIONING_TOKEN_ENV]

    base_url = validate_base_url(source.get("base_url", DEFAULT_BASE_URL))

    token = source.get("provisioning_token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("provisioning_token is required")

    state_db_value = source.get("state_db", DEFAULT_STATE_DB)
    if not isinstance(state_db_value, str) or not state_db_value.strip():
        raise ValueError("state_db must be a non-empty path")
    state_db = Path(state_db_value).expanduser()

    timeout = _positive_number(
        "request_timeout_seconds",
        source.get("request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
    )
    default_seconds = _positive_int(
        "default_seconds",
        source.get("default_seconds", DEFAULT_SECONDS),
    )
    return ChannelConfig(
        base_url=base_url,
        provisioning_token=token.strip(),
        state_db=state_db,
        request_timeout_seconds=timeout,
        default_seconds=default_seconds,
    )


__all__ = [
    "BASE_URL_ENV",
    "ChannelConfig",
    "DEFAULT_BASE_URL",
    "DEFAULT_SECONDS",
    "DEFAULT_STATE_DB",
    "DEFAULT_TIMEOUT_SECONDS",
    "PROVISIONING_TOKEN_ENV",
    "load_config",
    "validate_base_url",
]
