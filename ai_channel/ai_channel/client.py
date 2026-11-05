"""Small stdlib-only Ghost HTTP client used by the AI channel.

Two token namespaces are kept explicit: the provisioning token only creates
ordinary accounts, while account tokens only call ``/v1/me/*`` and
``/v1/shop*``.  Tokens are never logged or included in error messages.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final
from urllib.parse import urlsplit

USER_AGENT: Final = "ai-channel/1.0"
Transport = Callable[[str, str, Mapping[str, str], bytes | None], Any]


class AIChannelHTTPError(RuntimeError):
    """A Ghost endpoint returned a non-2xx response."""

    def __init__(self, status: int, url: str, body: str) -> None:
        self.status = status
        self.url = url
        self.body = body
        detail = body.strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        super().__init__(f"Ghost request failed ({status}) {url}: {detail}")


class AIChannelTransportError(RuntimeError):
    """The HTTP request failed before any response was received."""


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


def _iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError("occurred_at must be a datetime or ISO-8601 string")


class AIClient:
    """Provision accounts and act through Ghost's public API."""

    def __init__(
        self,
        base_url: str,
        *,
        provisioning_token: str | None = None,
        timeout: float = 15.0,
        transport: Transport | None = None,
    ) -> None:
        parsed = urlsplit(str(base_url).strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute http/https URL")
        self.base_url = str(base_url).strip().rstrip("/")
        self._provisioning_token = provisioning_token
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        self._transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not isinstance(token, str) or not token:
            raise ValueError("a bearer token is required")
        url = f"{self.base_url}{path}"
        body = None
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if payload is not None:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            if self._transport is not None:
                response = self._transport(method, url, headers, body)
            else:
                request = urllib.request.Request(
                    url, data=body, headers=headers, method=method
                )
                response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            text = (
                raw.decode("utf-8", errors="replace")
                if isinstance(raw, bytes)
                else str(raw)
            )
            raise AIChannelHTTPError(int(exc.code), url, text) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AIChannelTransportError(
                f"could not reach Ghost endpoint {url}: {exc}"
            ) from exc
        status, decoded = _decode_response(response)
        if status < 200 or status >= 300:
            raise AIChannelHTTPError(status, url, str(decoded))
        return decoded

    def provision_account(
        self,
        user_id: str,
        display_name: str,
        *,
        activity_label: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be a non-empty string")
        if not isinstance(display_name, str) or not display_name:
            raise ValueError("display_name must be a non-empty string")
        payload: dict[str, Any] = {
            "user_id": user_id,
            "display_name": display_name,
        }
        if activity_label is not None:
            payload["activity_label"] = activity_label
        result = self._request(
            "POST",
            "/v1/provisioning/accounts",
            token=self._provisioning_token,
            payload=payload,
        )
        if not isinstance(result, dict) or not isinstance(result.get("token"), str):
            raise ValueError("provisioning response did not contain a token")
        return result

    def send_increment(
        self,
        token: str,
        event_id: str,
        seconds: int,
        occurred_at: datetime | str,
    ) -> dict[str, Any]:
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id must be a non-empty string")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError("seconds must be a positive integer")
        result = self._request(
            "POST",
            "/v1/me/increments",
            token=token,
            payload={
                "event_id": event_id,
                "seconds": seconds,
                "occurred_at": _iso(occurred_at),
            },
        )
        if not isinstance(result, dict):
            raise ValueError("increment response was not an object")
        return result

    def get_status(self, token: str) -> dict[str, Any]:
        result = self._request("GET", "/v1/me/status", token=token)
        if not isinstance(result, dict):
            raise ValueError("status response was not an object")
        return result

    def get_shop(self, token: str) -> list[dict[str, Any]]:
        result = self._request("GET", "/v1/shop", token=token)
        if not isinstance(result, list):
            raise ValueError("shop response was not a list")
        return result

    def purchase(
        self, token: str, item_id: str, request_id: str
    ) -> dict[str, Any]:
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("item_id must be a non-empty string")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be a non-empty string")
        result = self._request(
            "POST",
            "/v1/shop/purchase",
            token=token,
            payload={
                "item_id": item_id,
                "quantity": 1,
                "request_id": request_id,
            },
        )
        if not isinstance(result, dict):
            raise ValueError("purchase response was not an object")
        return result


__all__ = [
    "AIClient",
    "AIChannelHTTPError",
    "AIChannelTransportError",
    "Transport",
    "USER_AGENT",
]
