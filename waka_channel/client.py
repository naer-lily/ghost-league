"""Minimal Ghost Channel client for roster and hourly increments.

Only the documented ingest fields are serialized.  The bearer token comes from
``GHOST_LEAGUE_CHANNEL_TOKEN`` (or an explicit constructor argument) and is
never logged.  Any non-2xx response is raised as :class:`ChannelHTTPError`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from .identity import CHANNEL_ID
from .projection import HourlyIncrement, parse_at

TOKEN_ENV: Final = "GHOST_LEAGUE_CHANNEL_TOKEN"
ALT_TOKEN_ENV: Final = "WAKA_CHANNEL_TOKEN"
DEFAULT_BASE_URL: Final = os.environ.get(
    "GHOST_LEAGUE_BASE_URL", "http://127.0.0.1:8095"
)
USER_AGENT: Final = "waka-channel/1.0"


class ChannelHTTPError(RuntimeError):
    """A Ghost Channel endpoint returned a non-2xx response."""

    def __init__(self, status: int, url: str, body: str) -> None:
        self.status = status
        self.url = url
        self.body = body
        detail = body.strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        super().__init__(f"Ghost Channel request failed ({status}) {url}: {detail}")


class ChannelTransportError(RuntimeError):
    """The HTTP request itself failed before a response was received."""


Transport = Callable[[str, Mapping[str, str], bytes], Any]


def _response_status(response: Any) -> int:
    for attribute in ("status", "status_code", "code"):
        value = getattr(response, attribute, None)
        if isinstance(value, int):
            return value
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        value = getcode()
        if isinstance(value, int):
            return value
    return 200


def _response_body(response: Any) -> Any:
    read = getattr(response, "read", None)
    if callable(read):
        raw = read()
    elif hasattr(response, "__enter__") and hasattr(response, "__exit__"):
        with response as entered:
            return _response_body(entered)
    else:
        raw = response
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def _decode_response(response: Any) -> tuple[int, Any]:
    if isinstance(response, tuple) and len(response) == 2:
        status, payload = response
        if not isinstance(status, int):
            raise TypeError("injected HTTP status must be an integer")
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            if not payload.strip():
                payload = {}
            else:
                try:
                    payload = json.loads(payload)
                except ValueError:
                    pass
        return status, payload
    if isinstance(response, (dict, list)):
        return 200, response
    return _response_status(response), _response_body(response)


class ChannelClient:
    """POST roster and increment payloads to one Ghost Channel namespace."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        token: str | None = None,
        channel: str = CHANNEL_ID,
        timeout: float = 10.0,
        post_fn: Transport | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.channel = channel
        resolved = token
        if resolved is None:
            resolved = os.environ.get(TOKEN_ENV) or os.environ.get(ALT_TOKEN_ENV)
        self._token = resolved
        self.timeout = timeout
        self._post_fn = post_fn or transport

    def _endpoint(self, action: str) -> str:
        channel = urllib.parse.quote(self.channel, safe="")
        return f"{self.base_url}/v1/channels/{channel}/{action}"

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise ValueError(
                f"Channel token is required ({TOKEN_ENV} or explicit token)"
            )
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

    def _post(self, action: str, payload: dict[str, Any]) -> Any:
        url = self._endpoint(action)
        headers = self._headers()
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        try:
            if self._post_fn is not None:
                response = self._post_fn(url, headers, body)
            else:
                request = urllib.request.Request(
                    url, data=body, headers=headers, method="POST"
                )
                response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            raise ChannelHTTPError(int(exc.code), url, text) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ChannelTransportError(
                f"could not reach Ghost Channel endpoint {url}: {exc}"
            ) from exc
        status, decoded = _decode_response(response)
        if status < 200 or status >= 300:
            raise ChannelHTTPError(status, url, str(decoded))
        return decoded

    def post_roster(
        self, players: Iterable[Mapping[str, Any]] | Mapping[str, Any]
    ) -> Any:
        """POST the full weekly roster manifest."""

        if isinstance(players, Mapping):
            wrapped = players.get("players")
            if not isinstance(wrapped, list):
                raise ValueError("roster payload must contain a players array")
            players = wrapped
        clean: list[dict[str, Any]] = []
        seen: set[str] = set()
        for player in players:
            ref = player.get("player_ref")
            if not isinstance(ref, str) or not ref:
                raise ValueError("roster player_ref must be a non-empty string")
            if ref in seen:
                continue
            seen.add(ref)
            kind = player.get("kind", "ai")
            if kind not in {"ai", "human"}:
                raise ValueError("roster kind must be ai or human")
            profile = player.get("profile")
            if profile is not None and not isinstance(profile, Mapping):
                raise ValueError("roster profile must be an object or null")
            clean.append(
                {
                    "player_ref": ref,
                    "kind": kind,
                    "profile": dict(profile) if profile is not None else None,
                }
            )
        if not clean:
            raise ValueError("roster must contain at least one player")
        return self._post("roster", {"players": clean})

    def post_increment(
        self, event: HourlyIncrement | Mapping[str, Any]
    ) -> Any:
        """POST exactly one already-projected hourly increment."""

        if isinstance(event, HourlyIncrement):
            payload = event.as_payload()
        else:
            ref = event.get("player_ref")
            event_id = event.get("event_id")
            seconds = event.get("seconds")
            occurred_at = event.get("occurred_at")
            if not isinstance(ref, str) or not ref:
                raise ValueError("increment player_ref must be a non-empty string")
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("increment event_id must be a non-empty string")
            if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
                raise ValueError("increment seconds must be a positive integer")
            payload = {
                "player_ref": ref,
                "event_id": event_id,
                "seconds": seconds,
                "occurred_at": parse_at(occurred_at).isoformat(timespec="seconds"),
            }
        return self._post("increments", payload)

    def send_increments(
        self, events: Iterable[HourlyIncrement | Mapping[str, Any]]
    ) -> list[Any]:
        """Send every event in order; the first HTTP error aborts the batch."""

        return [self.post_increment(event) for event in events]

    # Convenient aliases for callers that use the contract vocabulary.
    sync_roster = post_roster
    send_increment = post_increment


WakaClient = ChannelClient


__all__ = [
    "ALT_TOKEN_ENV",
    "ChannelClient",
    "ChannelHTTPError",
    "ChannelTransportError",
    "DEFAULT_BASE_URL",
    "TOKEN_ENV",
    "WakaClient",
]
