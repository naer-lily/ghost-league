"""FastAPI app factory for the thermal-printer queue service."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from datetime import datetime
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Response

from .auth import require_token
from .models import (
    ClaimRequest,
    HeartbeatRequest,
    JobCreateRequest,
    ResultRequest,
)
from .store import LeaseConflict, PrintStore

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
DEFAULT_DB = "print-service/data/print.db"

PAYLOAD_B64_INVALID = "payload_b64_invalid"
PAYLOAD_EMPTY = "payload_empty"
PAYLOAD_TOO_LARGE = "payload_too_large"
JOB_NOT_FOUND = "job_not_found"
LEASE_CONFLICT = "lease_conflict"

CLAIM_JOB_FIELDS = (
    "id",
    "printer_id",
    "kind",
    "source_ref",
    "payload_b64",
    "payload_sha256",
    "attempts",
    "max_attempts",
    "lease_id",
    "lease_expires_at",
)


def _decode_payload(value: str) -> bytes:
    try:
        payload = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail=PAYLOAD_B64_INVALID) from None
    if not payload:
        raise HTTPException(status_code=422, detail=PAYLOAD_EMPTY)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=422, detail=PAYLOAD_TOO_LARGE)
    return payload


def _clean_token(value: str | None) -> str | None:
    return value if value else None


def create_app(
    *,
    db_path: str | None = None,
    producer_token: str | None = None,
    daemon_token: str | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Create the print queue application.

    Explicit arguments win over environment fallbacks. Missing tokens are
    tolerated at startup so ``/healthz`` and local development keep working,
    but every authenticated route then fails closed with 503.
    """
    resolved_db = db_path or os.environ.get("PRINT_SERVICE_DB") or DEFAULT_DB
    resolved_producer = _clean_token(
        producer_token
        if producer_token is not None
        else os.environ.get("PRINT_PRODUCER_TOKEN")
    )
    resolved_daemon = _clean_token(
        daemon_token
        if daemon_token is not None
        else os.environ.get("PRINT_DAEMON_TOKEN")
    )

    store = PrintStore(resolved_db, now_fn=now_fn)
    app = FastAPI(title="print-service", version="0.1.0")
    app.state.store = store
    app.state.producer_token = resolved_producer
    app.state.daemon_token = resolved_daemon

    producer_auth = Depends(require_token(resolved_producer))
    daemon_auth = Depends(require_token(resolved_daemon))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "time": store.now_iso()}

    @app.post("/v1/print/jobs", dependencies=[producer_auth])
    def create_job(body: JobCreateRequest) -> dict:
        payload = _decode_payload(body.payload_b64)
        digest = hashlib.sha256(payload).hexdigest()
        job, duplicate = store.create_job(
            printer_id=body.printer_id,
            kind=body.kind,
            source_ref=body.source_ref,
            dedupe_key=body.dedupe_key,
            payload=payload,
            payload_sha256=digest,
            max_attempts=body.max_attempts,
        )
        return {"job": job, "duplicate": duplicate}

    @app.post("/v1/print/claim", dependencies=[daemon_auth])
    def claim(body: ClaimRequest):
        job = store.claim_job(body.printer_id, body.lease_seconds)
        if job is None:
            return Response(status_code=204)
        return {"job": {key: job[key] for key in CLAIM_JOB_FIELDS}}

    @app.post("/v1/print/jobs/{job_id}/result", dependencies=[daemon_auth])
    def job_result(job_id: str, body: ResultRequest) -> dict:
        try:
            job = store.record_result(
                job_id=job_id,
                lease_id=body.lease_id,
                status=body.status,
                error=body.error,
            )
        except LeaseConflict:
            raise HTTPException(status_code=409, detail=LEASE_CONFLICT) from None
        return {"job": job}

    @app.get("/v1/print/jobs/{job_id}", dependencies=[producer_auth])
    def get_job(job_id: str) -> dict:
        job = store.get_job_metadata(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=JOB_NOT_FOUND)
        return {"job": job}

    @app.post("/v1/print/jobs/{job_id}/reprint", dependencies=[producer_auth])
    def reprint(job_id: str) -> dict:
        job = store.reprint_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=JOB_NOT_FOUND)
        return {"job": job}

    @app.post("/v1/print/heartbeat", dependencies=[daemon_auth])
    def heartbeat(body: HeartbeatRequest) -> dict:
        store.heartbeat(
            printer_id=body.printer_id,
            state=body.state,
            detail=body.detail,
        )
        return {"status": "ok", "time": store.now_iso()}

    return app
