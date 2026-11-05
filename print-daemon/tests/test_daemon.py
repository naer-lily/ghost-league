from __future__ import annotations

import base64
import hashlib
import json
import socket
import socketserver
import threading
from pathlib import Path

import pytest

from print_daemon.api import ApiError
from print_daemon.cli import run_once, verify_payload
from print_daemon.config import Config, ConfigError
from print_daemon.printer import (
    PrinterClient,
    PrinterError,
    test_page as make_test_page,
)

BASE_CONFIG = {
    "server_url": "http://127.0.0.1:8096",
    "daemon_token": "test-daemon-token",
    "printer_id": "home-80mm",
    "printer_host": "127.0.0.1",
    "printer_port": 9100,
    "poll_seconds": 2.0,
    "lease_seconds": 60,
    "heartbeat_seconds": 30,
    "http_timeout_seconds": 15,
    "printer_timeout_seconds": 10,
}


def make_config(**overrides) -> Config:
    data = dict(BASE_CONFIG)
    data.update(overrides)
    return Config.from_dict(data)


def make_job(payload: bytes, **overrides) -> dict:
    job = {
        "id": "job-1",
        "printer_id": "home-80mm",
        "kind": "test",
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "attempts": 1,
        "max_attempts": 3,
        "lease_id": "lease-1",
        "lease_expires_at": "2026-01-01T12:01:00.000000Z",
    }
    job.update(overrides)
    return job


class FakeApi:
    def __init__(self, jobs: list[dict | None]) -> None:
        self.jobs = list(jobs)
        self.results: list[tuple] = []
        self.heartbeats: list[tuple] = []

    def claim(self, printer_id: str, lease_seconds: int) -> dict | None:
        if not self.jobs:
            return None
        return self.jobs.pop(0)

    def report_result(self, job_id, lease_id, status, error=None):
        self.results.append((job_id, lease_id, status, error))
        return {"job": {"id": job_id, "status": status}}

    def heartbeat(self, printer_id, state, detail=None):
        self.heartbeats.append((printer_id, state, detail))
        return {"status": "ok"}


class FakePrinter:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[bytes] = []
        self.fail = fail

    def send(self, payload: bytes) -> None:
        if self.fail:
            raise PrinterError("printer offline")
        self.sent.append(payload)

    def probe(self) -> None:
        if self.fail:
            raise PrinterError("printer offline")


class _TCPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        chunks = []
        while True:
            data = self.request.recv(4096)
            if not data:
                break
            chunks.append(data)
        self.server.received = b"".join(chunks)
        self.server.done.set()


class _TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received = b""
        self.done = threading.Event()


@pytest.fixture
def tcp_server():
    server = _TCPServer(("127.0.0.1", 0), _TCPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _closed_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def test_printer_send_writes_exact_bytes(tcp_server):
    payload = b"\x1b@hello raw bytes\n\x1dV\x00"
    printer = PrinterClient("127.0.0.1", tcp_server.server_address[1], timeout=2)
    printer.send(payload)

    assert tcp_server.done.wait(3)
    assert tcp_server.received == payload


def test_printer_connection_failure_raises_clear_error():
    port = _closed_port()
    printer = PrinterClient("127.0.0.1", port, timeout=1)
    with pytest.raises(PrinterError) as excinfo:
        printer.send(b"x")
    message = str(excinfo.value)
    assert "printer 127.0.0.1:" in message
    assert "failed" in message


def test_payload_sha_mismatch_is_rejected_before_printing():
    payload = b"payload"
    job = make_job(payload, payload_sha256=hashlib.sha256(b"other").hexdigest())

    with pytest.raises(Exception) as excinfo:
        verify_payload(job)
    assert "payload_sha256_mismatch" in str(excinfo.value)

    api = FakeApi([job])
    printer = FakePrinter()
    assert run_once(make_config(), api=api, printer=printer) == 1
    assert printer.sent == []
    assert api.results == [("job-1", "lease-1", "failed", "payload_sha256_mismatch")]


def test_run_once_claims_prints_and_reports_done():
    payload = b"\x1b@ticket bytes\x1dV\x00"
    api = FakeApi([make_job(payload)])
    printer = FakePrinter()

    assert run_once(make_config(), api=api, printer=printer) == 0
    assert printer.sent == [payload]
    assert api.results == [("job-1", "lease-1", "done", None)]


def test_run_once_no_job_returns_cleanly():
    api = FakeApi([None])
    printer = FakePrinter()

    assert run_once(make_config(), api=api, printer=printer) == 0
    assert printer.sent == []
    assert api.results == []


def test_run_once_printer_failure_reports_failed():
    api = FakeApi([make_job(b"\x1b@payload")])
    printer = FakePrinter(fail=True)

    assert run_once(make_config(), api=api, printer=printer) == 1
    assert len(api.results) == 1
    job_id, lease_id, status, error = api.results[0]
    assert (job_id, lease_id, status) == ("job-1", "lease-1", "failed")
    assert "offline" in error


def test_run_once_claim_error_returns_one():
    class FailingApi(FakeApi):
        def claim(self, printer_id, lease_seconds):
            raise ApiError("server down")

    assert run_once(make_config(), api=FailingApi([]), printer=FakePrinter()) == 1


def test_config_rejects_missing_values():
    for field in (
        "server_url",
        "daemon_token",
        "printer_id",
        "printer_host",
        "printer_port",
        "poll_seconds",
    ):
        data = dict(BASE_CONFIG)
        del data[field]
        with pytest.raises(ConfigError):
            Config.from_dict(data)


def test_config_rejects_zero_and_bad_values():
    with pytest.raises(ConfigError):
        make_config(poll_seconds=0)
    with pytest.raises(ConfigError):
        make_config(heartbeat_seconds=-1)
    with pytest.raises(ConfigError):
        make_config(printer_timeout_seconds=0)
    with pytest.raises(ConfigError):
        make_config(printer_port=0)
    with pytest.raises(ConfigError):
        make_config(printer_port=70000)
    with pytest.raises(ConfigError):
        make_config(printer_port="9100")
    with pytest.raises(ConfigError):
        make_config(server_url="not-a-url")
    with pytest.raises(ConfigError):
        make_config(lease_seconds=1.5)


def test_config_loads_json_and_env_overrides(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(BASE_CONFIG), encoding="utf-8")
    monkeypatch.setenv("PRINT_DAEMON_TOKEN", "env-token")
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://127.0.0.1:9999/")

    config = Config.load(config_path)
    assert config.daemon_token == "env-token"
    assert config.server_url == "http://127.0.0.1:9999"
    assert "env-token" not in repr(config)


def test_config_load_rejects_bad_json(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(config_path)


def test_test_page_contains_init_and_cut():
    page = make_test_page()
    assert page.startswith(b"\x1b@")
    assert b"\x1dV\x00" in page
    page.decode("ascii")  # The test page must stay ASCII-only.
