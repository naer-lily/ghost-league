from __future__ import annotations

import base64
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from print_service.app import MAX_PAYLOAD_BYTES, create_app

PRODUCER = "test-producer-token"
DAEMON = "test-daemon-token"
PRODUCER_HEADERS = {"Authorization": f"Bearer {PRODUCER}"}
DAEMON_HEADERS = {"Authorization": f"Bearer {DAEMON}"}


class Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for name in ("PRINT_SERVICE_DB", "PRINT_PRODUCER_TOKEN", "PRINT_DAEMON_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(tmp_path: Path, clock: Clock):
    return create_app(
        db_path=str(tmp_path / "print.db"),
        producer_token=PRODUCER,
        daemon_token=DAEMON,
        now_fn=clock,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _create(client: TestClient, **overrides) -> dict:
    body = {
        "printer_id": "home-80mm",
        "kind": "test",
        "payload_b64": _b64(b"\x1b@hello"),
    }
    body.update(overrides)
    response = client.post("/v1/print/jobs", json=body, headers=PRODUCER_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _claim(client: TestClient, **overrides) -> dict:
    body = {"printer_id": "home-80mm"}
    body.update(overrides)
    response = client.post("/v1/print/claim", json=body, headers=DAEMON_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["job"]


def _result(client: TestClient, job_id: str, lease_id: str, status: str, error=None):
    body = {"lease_id": lease_id, "status": status}
    if error is not None:
        body["error"] = error
    return client.post(
        f"/v1/print/jobs/{job_id}/result", json=body, headers=DAEMON_HEADERS
    )


def _get(client: TestClient, job_id: str) -> dict:
    response = client.get(f"/v1/print/jobs/{job_id}", headers=PRODUCER_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["job"]


def test_health_is_public(client: TestClient, clock: Clock):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["time"].endswith("Z")


def test_missing_and_wrong_tokens_are_rejected(client: TestClient):
    body = {"printer_id": "home-80mm", "kind": "test", "payload_b64": _b64(b"x")}

    assert client.post("/v1/print/jobs", json=body).status_code == 401
    assert (
        client.post(
            "/v1/print/jobs",
            json=body,
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )

    # Producer token must not work on daemon routes.
    claim = client.post(
        "/v1/print/claim",
        json={"printer_id": "home-80mm"},
        headers=PRODUCER_HEADERS,
    )
    assert claim.status_code == 401

    # Malformed Authorization headers are rejected too.
    malformed = client.post(
        "/v1/print/jobs",
        json=body,
        headers={"Authorization": "Basic abc"},
    )
    assert malformed.status_code == 401


def test_missing_server_token_fails_closed(tmp_path: Path):
    app = create_app(
        db_path=str(tmp_path / "print.db"),
        producer_token="",
        daemon_token="",
    )
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        response = client.post(
            "/v1/print/jobs",
            json={"printer_id": "p", "kind": "k", "payload_b64": _b64(b"x")},
            headers={"Authorization": "Bearer anything"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "service_token_not_configured"


def test_create_claim_done_round_trip(client: TestClient, clock: Clock):
    payload = b"\x1b@hello world\x1dV\x00"
    created = _create(client, payload_b64=_b64(payload), source_ref="ticket-1")
    assert created["duplicate"] is False
    job = created["job"]
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert job["payload_sha256"] == hashlib.sha256(payload).hexdigest()

    claimed = _claim(client)
    assert claimed["id"] == job["id"]
    assert claimed["attempts"] == 1
    assert claimed["lease_id"]
    assert claimed["lease_expires_at"]
    assert base64.b64decode(claimed["payload_b64"]) == payload

    response = _result(client, job["id"], claimed["lease_id"], "done")
    assert response.status_code == 200, response.text
    body = response.json()["job"]
    assert body["status"] == "done"
    assert body["printed_at"] is not None
    assert body["lease_id"] is None

    metadata = _get(client, job["id"])
    assert metadata["status"] == "done"
    assert "payload" not in metadata
    assert "payload_b64" not in metadata

    # A finished job is no longer claimable.
    assert (
        client.post(
            "/v1/print/claim",
            json={"printer_id": "home-80mm"},
            headers=DAEMON_HEADERS,
        ).status_code
        == 204
    )


def test_dedupe_returns_existing_job(client: TestClient):
    first = _create(client, dedupe_key="order-42")
    second = _create(client, dedupe_key="order-42", payload_b64=_b64(b"different"))
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["job"]["id"] == first["job"]["id"]
    assert second["job"]["payload_sha256"] == first["job"]["payload_sha256"]

    # Dedupe keys are scoped by printer.
    other = _create(client, printer_id="office-58mm", dedupe_key="order-42")
    assert other["duplicate"] is False
    assert other["job"]["id"] != first["job"]["id"]


def test_wrong_lease_is_conflict(client: TestClient):
    job = _create(client)["job"]
    claimed = _claim(client)

    wrong_lease = _result(client, job["id"], "not-the-lease", "done")
    assert wrong_lease.status_code == 409
    assert wrong_lease.json()["detail"] == "lease_conflict"

    # Unknown job ids are conflicts too, not 404.
    missing = _result(client, "does-not-exist", claimed["lease_id"], "done")
    assert missing.status_code == 409


def test_failed_job_retries_until_max_attempts(client: TestClient):
    job = _create(client, max_attempts=2)["job"]

    first = _claim(client)
    failed = _result(client, job["id"], first["lease_id"], "failed", error="paper jam")
    assert failed.status_code == 200
    retry = failed.json()["job"]
    assert retry["status"] == "pending"
    assert retry["attempts"] == 1
    assert retry["last_error"] == "paper jam"

    second = _claim(client)
    assert second["attempts"] == 2
    final = _result(
        client, job["id"], second["lease_id"], "failed", error="still jammed"
    )
    final_job = final.json()["job"]
    assert final_job["status"] == "failed"
    assert final_job["attempts"] == 2
    assert final_job["last_error"] == "still jammed"

    assert (
        client.post(
            "/v1/print/claim",
            json={"printer_id": "home-80mm"},
            headers=DAEMON_HEADERS,
        ).status_code
        == 204
    )


def test_unknown_result_needs_attention(client: TestClient):
    job = _create(client)["job"]
    claimed = _claim(client)
    response = _result(
        client, job["id"], claimed["lease_id"], "unknown", error="no paper"
    )
    assert response.status_code == 200
    assert response.json()["job"]["status"] == "needs_attention"
    assert response.json()["job"]["last_error"] == "no paper"

    assert (
        client.post(
            "/v1/print/claim",
            json={"printer_id": "home-80mm"},
            headers=DAEMON_HEADERS,
        ).status_code
        == 204
    )


def test_lease_expiry_makes_job_claimable(client: TestClient, clock: Clock):
    job = _create(client)["job"]
    first = _claim(client, lease_seconds=10)
    assert first["attempts"] == 1

    clock.advance(11)
    second = _claim(client, lease_seconds=10)
    assert second["id"] == job["id"]
    assert second["attempts"] == 2
    assert second["lease_id"] != first["lease_id"]


def test_lease_expiry_on_last_attempt_fails_job(client: TestClient, clock: Clock):
    job = _create(client, max_attempts=1)["job"]
    _claim(client, lease_seconds=10)
    clock.advance(11)
    assert (
        client.post(
            "/v1/print/claim",
            json={"printer_id": "home-80mm"},
            headers=DAEMON_HEADERS,
        ).status_code
        == 204
    )
    metadata = _get(client, job["id"])
    assert metadata["status"] == "failed"
    assert metadata["last_error"] == "lease_expired"


def test_reprint_creates_new_pending_job(client: TestClient):
    payload = b"\x1b@reprint-me"
    original = _create(
        client, payload_b64=_b64(payload), dedupe_key="ticket-7"
    )["job"]
    first_claim = _claim(client)
    assert first_claim["id"] == original["id"]
    assert _result(client, original["id"], first_claim["lease_id"], "done").status_code == 200

    response = client.post(
        f"/v1/print/jobs/{original['id']}/reprint", headers=PRODUCER_HEADERS
    )
    assert response.status_code == 200, response.text
    copied = response.json()["job"]
    assert copied["id"] != original["id"]
    assert copied["reprint_of"] == original["id"]
    assert copied["status"] == "pending"
    assert copied["dedupe_key"] is None
    assert copied["payload_sha256"] == original["payload_sha256"]

    claimed = _claim(client)
    assert claimed["id"] == copied["id"]
    assert base64.b64decode(claimed["payload_b64"]) == payload

    # The copy must not occupy the original dedupe slot.
    deduped = _create(
        client, payload_b64=_b64(payload), dedupe_key="ticket-7"
    )
    assert deduped["duplicate"] is True
    assert deduped["job"]["id"] == original["id"]


def test_reprint_unknown_job_is_404(client: TestClient):
    response = client.post(
        "/v1/print/jobs/missing/reprint", headers=PRODUCER_HEADERS
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "job_not_found"


def test_payload_validation(client: TestClient):
    invalid = client.post(
        "/v1/print/jobs",
        json={"printer_id": "p", "kind": "k", "payload_b64": "not base64!!"},
        headers=PRODUCER_HEADERS,
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "payload_b64_invalid"

    empty = client.post(
        "/v1/print/jobs",
        json={"printer_id": "p", "kind": "k", "payload_b64": ""},
        headers=PRODUCER_HEADERS,
    )
    assert empty.status_code == 422
    assert empty.json()["detail"] == "payload_empty"

    oversized = client.post(
        "/v1/print/jobs",
        json={
            "printer_id": "p",
            "kind": "k",
            "payload_b64": _b64(b"x" * (MAX_PAYLOAD_BYTES + 1)),
        },
        headers=PRODUCER_HEADERS,
    )
    assert oversized.status_code == 422
    assert oversized.json()["detail"] == "payload_too_large"


def test_models_forbid_extra_fields(client: TestClient):
    response = client.post(
        "/v1/print/jobs",
        json={
            "printer_id": "p",
            "kind": "k",
            "payload_b64": _b64(b"x"),
            "unexpected": True,
        },
        headers=PRODUCER_HEADERS,
    )
    assert response.status_code == 422

    response = client.post(
        "/v1/print/claim",
        json={"printer_id": "p", "lease_seconds": 5},
        headers=DAEMON_HEADERS,
    )
    assert response.status_code == 422

    response = client.post(
        "/v1/print/claim",
        json={"printer_id": "p", "lease_seconds": 301},
        headers=DAEMON_HEADERS,
    )
    assert response.status_code == 422


def test_heartbeat_upserts_printer_state(client: TestClient, app, clock: Clock):
    first = client.post(
        "/v1/print/heartbeat",
        json={"printer_id": "home-80mm", "state": "online", "detail": "tcp ok"},
        headers=DAEMON_HEADERS,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "ok"
    assert body["time"] == clock().isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )

    stored = app.state.store.get_printer("home-80mm")
    assert stored is not None
    assert stored["state"] == "online"
    assert stored["detail"] == "tcp ok"

    clock.advance(30)
    second = client.post(
        "/v1/print/heartbeat",
        json={"printer_id": "home-80mm", "state": "offline", "detail": "timeout"},
        headers=DAEMON_HEADERS,
    )
    assert second.status_code == 200
    updated = app.state.store.get_printer("home-80mm")
    assert updated["state"] == "offline"
    assert updated["detail"] == "timeout"
    assert updated["last_seen_at"] != stored["last_seen_at"]

    # One row per printer id.
    conn = sqlite3.connect(app.state.store.db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM print_printers").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_heartbeat_rejects_bad_state(client: TestClient):
    response = client.post(
        "/v1/print/heartbeat",
        json={"printer_id": "p", "state": "printing"},
        headers=DAEMON_HEADERS,
    )
    assert response.status_code == 422
