"""Minimal stdlib HTTP client for the print queue service."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ApiError(Exception):
    """A print-service request failed."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ApiClient:
    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def claim(self, printer_id: str, lease_seconds: int) -> dict[str, Any] | None:
        data = self._request(
            "POST",
            "/v1/print/claim",
            {"printer_id": printer_id, "lease_seconds": lease_seconds},
        )
        if data is None:
            return None
        job = data.get("job")
        if not isinstance(job, dict):
            raise ApiError("claim response did not include a job")
        return job

    def report_result(
        self,
        job_id: str,
        lease_id: str,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"lease_id": lease_id, "status": status}
        if error is not None:
            body["error"] = error
        data = self._request("POST", f"/v1/print/jobs/{job_id}/result", body)
        if not isinstance(data, dict):
            raise ApiError("result response was not a JSON object")
        return data

    def heartbeat(
        self, printer_id: str, state: str, detail: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"printer_id": printer_id, "state": state}
        if detail is not None:
            body["detail"] = detail
        data = self._request("POST", "/v1/print/heartbeat", body)
        if not isinstance(data, dict):
            raise ApiError("heartbeat response was not a JSON object")
        return data

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        data = None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc.read())
            raise ApiError(
                f"{method} {path} returned HTTP {exc.code}: {detail}",
                status=exc.code,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(f"{method} {path} failed: {exc}") from exc

        if status == 204 or not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(f"{method} {path} returned invalid JSON") from None


def _error_detail(payload: bytes) -> str:
    """Return a short, log-safe error detail from an error response."""
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return "no response body"
    try:
        parsed = json.loads(text)
    except ValueError:
        return text[:500]
    if isinstance(parsed, dict) and "detail" in parsed:
        return str(parsed["detail"])[:500]
    return text[:500]
