"""Configuration loading and validation for the PC print daemon."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

ENV_TOKEN = "PRINT_DAEMON_TOKEN"
ENV_SERVER_URL = "PRINT_SERVICE_URL"


class ConfigError(ValueError):
    """Raised when the daemon configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    server_url: str
    daemon_token: str = field(repr=False)
    printer_id: str
    printer_host: str
    printer_port: int
    poll_seconds: float = 2.0
    lease_seconds: int = 60
    heartbeat_seconds: float = 30.0
    http_timeout_seconds: float = 15.0
    printer_timeout_seconds: float = 10.0

    @classmethod
    def load(cls, path: str | Path = "config.json") -> "Config":
        config_path = Path(path)
        try:
            raw = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read config file {config_path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ConfigError(f"config file {config_path} is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ConfigError("config file must contain a JSON object")

        # Environment overrides are applied after the file so deployments can
        # keep secrets out of config.json.
        token = os.environ.get(ENV_TOKEN)
        if token:
            data["daemon_token"] = token
        server_url = os.environ.get(ENV_SERVER_URL)
        if server_url:
            data["server_url"] = server_url
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Config":
        if not isinstance(data, Mapping):
            raise ConfigError("config must be a mapping")

        server_url = _required_str(data, "server_url")
        parts = urlsplit(server_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ConfigError("server_url must be an absolute http(s) URL")

        return cls(
            server_url=server_url.rstrip("/"),
            daemon_token=_required_str(data, "daemon_token"),
            printer_id=_required_str(data, "printer_id"),
            printer_host=_required_str(data, "printer_host"),
            printer_port=_required_port(data, "printer_port"),
            poll_seconds=_positive_number(data, "poll_seconds"),
            lease_seconds=_positive_int(data, "lease_seconds"),
            heartbeat_seconds=_positive_number(data, "heartbeat_seconds"),
            http_timeout_seconds=_positive_number(data, "http_timeout_seconds"),
            printer_timeout_seconds=_positive_number(data, "printer_timeout_seconds"),
        )


def _required_str(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"missing or invalid config value: {name}")
    return value.strip()


def _positive_number(data: Mapping[str, Any], name: str) -> float:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"missing or invalid config value: {name}")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ConfigError(f"{name} must be a positive number")
    return number


def _positive_int(data: Mapping[str, Any], name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _required_port(data: Mapping[str, Any], name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ConfigError(f"{name} must be an integer between 1 and 65535")
    return value
