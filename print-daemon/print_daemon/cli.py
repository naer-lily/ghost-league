"""Command line entry point and print loop for the PC daemon."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import logging
import signal
import threading
import time
from typing import Any

from . import __version__
from .api import ApiClient, ApiError
from .config import Config, ConfigError
from .printer import PrinterClient, PrinterError, test_page

LOG = logging.getLogger("print_daemon")

MAX_BACKOFF_SECONDS = 30.0
MAX_ERROR_CHARS = 2000


class PayloadError(Exception):
    """The claimed payload is missing, malformed, or fails its checksum."""


def verify_payload(job: dict[str, Any]) -> bytes:
    encoded = job.get("payload_b64")
    if not isinstance(encoded, str):
        raise PayloadError("payload_b64_missing")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise PayloadError("payload_b64_invalid") from None
    if not payload:
        raise PayloadError("payload_empty")

    expected = job.get("payload_sha256")
    actual = hashlib.sha256(payload).hexdigest()
    if not isinstance(expected, str) or not hmac.compare_digest(
        actual, expected.strip().lower()
    ):
        raise PayloadError("payload_sha256_mismatch")
    return payload


def _short_error(error: object) -> str:
    text = str(error).strip() or "unknown error"
    return text[:MAX_ERROR_CHARS]


def _report(
    api: Any, job_id: str, lease_id: str, status: str, error: str | None = None
) -> bool:
    try:
        api.report_result(job_id, lease_id, status, error)
    except ApiError as exc:
        LOG.error("job %s result %s not reported: %s", job_id, status, exc)
        return False
    return True


def process_job(job: dict[str, Any], api: Any, printer: Any) -> bool:
    """Verify, print, and report one claimed job.

    Returns True only when the payload was printed and ``done`` was accepted
    by the service.
    """
    job_id = str(job.get("id") or "")
    lease_id = job.get("lease_id")
    if not job_id or not isinstance(lease_id, str) or not lease_id:
        LOG.error("claimed job is missing id or lease_id")
        return False

    try:
        payload = verify_payload(job)
    except PayloadError as exc:
        LOG.warning("job %s rejected before printing: %s", job_id, exc)
        _report(api, job_id, lease_id, "failed", str(exc))
        return False

    try:
        printer.send(payload)
    except PrinterError as exc:
        message = _short_error(exc)
        LOG.warning("job %s printer failure: %s", job_id, message)
        _report(api, job_id, lease_id, "failed", message)
        return False

    if not _report(api, job_id, lease_id, "done"):
        LOG.error("job %s printed but could not be marked done", job_id)
        return False
    LOG.info("job %s printed", job_id)
    return True


def run_once(config: Config, api: Any | None = None, printer: Any | None = None) -> int:
    """Claim at most one job. Returns 0 for done/no job, 1 for any failure."""
    api = api if api is not None else _make_api(config)
    printer = printer if printer is not None else _make_printer(config)
    try:
        job = api.claim(config.printer_id, config.lease_seconds)
    except ApiError as exc:
        LOG.error("claim failed: %s", exc)
        return 1
    except Exception:  # noqa: BLE001 - --once must report a clean exit code
        LOG.exception("unexpected error while claiming a job")
        return 1
    if job is None:
        LOG.info("no print job available")
        return 0
    try:
        return 0 if process_job(job, api, printer) else 1
    except Exception:  # noqa: BLE001 - --once must report a clean exit code
        LOG.exception("unexpected error while processing a job")
        return 1


def run_forever(
    config: Config,
    api: Any | None = None,
    printer: Any | None = None,
    stop_event: threading.Event | None = None,
) -> int:
    api = api if api is not None else _make_api(config)
    printer = printer if printer is not None else _make_printer(config)
    stop = stop_event if stop_event is not None else threading.Event()
    _install_signal_handlers(stop)
    LOG.info(
        "print daemon started for printer %s (%s:%s)",
        config.printer_id,
        config.printer_host,
        config.printer_port,
    )

    next_heartbeat = 0.0
    backoff = min(config.poll_seconds, MAX_BACKOFF_SECONDS)
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_heartbeat:
            try:
                _send_heartbeat(config, api, printer)
            except Exception:  # noqa: BLE001 - heartbeat must not stop the loop
                LOG.exception("unexpected error while sending heartbeat")
            next_heartbeat = time.monotonic() + config.heartbeat_seconds

        try:
            job = api.claim(config.printer_id, config.lease_seconds)
        except ApiError as exc:
            LOG.warning("claim failed: %s; retrying in %.1fs", exc, backoff)
            if stop.wait(backoff):
                break
            backoff = min(max(backoff * 2.0, 1.0), MAX_BACKOFF_SECONDS)
            continue
        except Exception:  # noqa: BLE001 - keep polling after unexpected errors
            LOG.exception("unexpected claim error; retrying in %.1fs", backoff)
            if stop.wait(backoff):
                break
            backoff = min(max(backoff * 2.0, 1.0), MAX_BACKOFF_SECONDS)
            continue

        backoff = min(config.poll_seconds, MAX_BACKOFF_SECONDS)
        if job is None:
            if stop.wait(config.poll_seconds):
                break
            continue

        try:
            process_job(job, api, printer)
        except Exception:  # noqa: BLE001 - one bad job must not stop the daemon
            LOG.exception("unexpected error while processing a job")

    LOG.info("print daemon stopped")
    return 0


def _send_heartbeat(config: Config, api: Any, printer: Any) -> None:
    try:
        printer.probe()
    except PrinterError as exc:
        state = "offline"
        detail = _short_error(exc)
        LOG.warning("printer probe failed: %s", detail)
    else:
        state = "online"
        detail = None
    try:
        api.heartbeat(config.printer_id, state, detail)
    except ApiError as exc:
        LOG.warning("heartbeat failed: %s", exc)


def _install_signal_handlers(stop: threading.Event) -> None:
    def handler(signum, _frame) -> None:
        LOG.info("signal %s received, stopping", signum)
        stop.set()

    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            # Signals can only be installed from the main thread on some
            # platforms; the loop still works when called from a thread.
            pass


def _make_api(config: Config) -> ApiClient:
    return ApiClient(
        config.server_url, config.daemon_token, timeout=config.http_timeout_seconds
    )


def _make_printer(config: Config) -> PrinterClient:
    return PrinterClient(
        config.printer_host,
        config.printer_port,
        timeout=config.printer_timeout_seconds,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="print_daemon",
        description="Poll the print queue service and print raw ESC/POS jobs.",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="path to config.json (default: %(default)s)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="logging level (default: %(default)s)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="claim and process at most one job, then exit",
    )
    mode.add_argument(
        "--print-test",
        action="store_true",
        help="send an ASCII ESC/POS test page directly to the printer",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = Config.load(args.config)
    except ConfigError as exc:
        LOG.error("configuration error: %s", exc)
        return 2

    if args.print_test:
        printer = _make_printer(config)
        try:
            printer.send(test_page())
        except PrinterError as exc:
            LOG.error("print test failed: %s", exc)
            return 1
        LOG.info("test page sent to %s:%s", config.printer_host, config.printer_port)
        return 0

    if args.once:
        return run_once(config)
    return run_forever(config)
