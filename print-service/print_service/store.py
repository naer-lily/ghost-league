"""SQLite storage for print jobs, leases, printers, and reprints."""

from __future__ import annotations

import base64
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS print_jobs (
    id TEXT PRIMARY KEY,
    printer_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_ref TEXT,
    dedupe_key TEXT,
    payload BLOB NOT NULL,
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_id TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    claimed_at TEXT,
    printed_at TEXT,
    last_error TEXT,
    reprint_of TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_print_jobs_dedupe
    ON print_jobs (printer_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_print_jobs_claim
    ON print_jobs (printer_id, status, created_at);

CREATE TABLE IF NOT EXISTS print_printers (
    printer_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    detail TEXT,
    last_seen_at TEXT,
    updated_at TEXT NOT NULL
);
"""

JOB_METADATA_COLUMNS = (
    "id",
    "printer_id",
    "kind",
    "source_ref",
    "dedupe_key",
    "payload_sha256",
    "status",
    "attempts",
    "max_attempts",
    "lease_id",
    "lease_expires_at",
    "created_at",
    "updated_at",
    "claimed_at",
    "printed_at",
    "last_error",
    "reprint_of",
)


class LeaseConflict(Exception):
    """Raised when a result does not match the job's active lease."""


class PrintStore:
    """One SQLite file shared by every request of a service process.

    Connections are opened per operation. Combined with WAL and
    ``BEGIN IMMEDIATE`` around writes this keeps concurrent TestClient
    requests and multiple uvicorn workers consistent.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        now_fn: Callable[[], datetime] | None = None,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.db_path = str(db_path)
        self._now_fn = now_fn
        self._busy_timeout_ms = busy_timeout_ms
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._init_schema()

    # -- connection helpers -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=self._busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_ms)}")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- time ---------------------------------------------------------------

    def _now_datetime(self) -> datetime:
        value = self._now_fn() if self._now_fn is not None else datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")

    def now_iso(self) -> str:
        return self._iso(self._now_datetime())

    # -- serialization ------------------------------------------------------

    @staticmethod
    def _metadata(row: sqlite3.Row) -> dict:
        return {column: row[column] for column in JOB_METADATA_COLUMNS}

    def _job_row(self, conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM print_jobs WHERE id = ?", (job_id,)
        ).fetchone()

    # -- jobs ---------------------------------------------------------------

    def create_job(
        self,
        *,
        printer_id: str,
        kind: str,
        payload: bytes,
        payload_sha256: str,
        source_ref: str | None = None,
        dedupe_key: str | None = None,
        max_attempts: int = 3,
    ) -> tuple[dict, bool]:
        """Insert a job, returning ``(metadata, duplicate)``.

        Dedupe is scoped to ``(printer_id, dedupe_key)`` and checked inside
        the same write transaction as the insert.
        """
        now = self.now_iso()
        job_id = str(uuid.uuid4())
        with self._transaction() as conn:
            if dedupe_key is not None:
                existing = conn.execute(
                    "SELECT * FROM print_jobs WHERE printer_id = ? AND dedupe_key = ?",
                    (printer_id, dedupe_key),
                ).fetchone()
                if existing is not None:
                    return self._metadata(existing), True
            conn.execute(
                """
                INSERT INTO print_jobs (
                    id, printer_id, kind, source_ref, dedupe_key, payload,
                    payload_sha256, status, attempts, max_attempts,
                    lease_id, lease_expires_at, created_at, updated_at,
                    claimed_at, printed_at, last_error, reprint_of
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, NULL, NULL,
                          ?, ?, NULL, NULL, NULL, NULL)
                """,
                (
                    job_id,
                    printer_id,
                    kind,
                    source_ref,
                    dedupe_key,
                    sqlite3.Binary(payload),
                    payload_sha256,
                    max_attempts,
                    now,
                    now,
                ),
            )
            row = self._job_row(conn, job_id)
            assert row is not None
            return self._metadata(row), False

    def get_job(self, job_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = self._job_row(conn, job_id)
            if row is None:
                return None
            metadata = self._metadata(row)
            metadata["payload"] = bytes(row["payload"])
            return metadata
        finally:
            conn.close()

    def get_job_metadata(self, job_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = self._job_row(conn, job_id)
            return None if row is None else self._metadata(row)
        finally:
            conn.close()

    def _reap_expired(
        self, conn: sqlite3.Connection, now: str, printer_id: str | None = None
    ) -> None:
        query = (
            "UPDATE print_jobs SET "
            "status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END, "
            "last_error = CASE WHEN attempts >= max_attempts THEN 'lease_expired' "
            "ELSE last_error END, "
            "lease_id = NULL, lease_expires_at = NULL, updated_at = ? "
            "WHERE status = 'claimed' AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at <= ?"
        )
        params: list[object] = [now, now]
        if printer_id is not None:
            query += " AND printer_id = ?"
            params.append(printer_id)
        conn.execute(query, params)

    def reap_expired(self, printer_id: str | None = None) -> None:
        now = self.now_iso()
        with self._transaction() as conn:
            self._reap_expired(conn, now, printer_id)

    def claim_job(self, printer_id: str, lease_seconds: int) -> dict | None:
        """Reap expired leases, then claim the oldest pending job."""
        now_dt = self._now_datetime()
        now = self._iso(now_dt)
        expires = self._iso(now_dt + timedelta(seconds=lease_seconds))
        with self._transaction() as conn:
            self._reap_expired(conn, now, printer_id)
            row = conn.execute(
                """
                SELECT * FROM print_jobs
                WHERE printer_id = ? AND status = 'pending'
                ORDER BY created_at ASC, rowid ASC
                LIMIT 1
                """,
                (printer_id,),
            ).fetchone()
            if row is None:
                return None
            attempts = int(row["attempts"]) + 1
            lease_id = str(uuid.uuid4())
            conn.execute(
                """
                UPDATE print_jobs
                SET status = 'claimed', attempts = ?, lease_id = ?,
                    lease_expires_at = ?, claimed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (attempts, lease_id, expires, now, now, row["id"]),
            )
            row = self._job_row(conn, row["id"])
            assert row is not None
            job = self._metadata(row)
            job["payload_b64"] = _b64encode(bytes(row["payload"]))
            return job

    def record_result(
        self,
        *,
        job_id: str,
        lease_id: str,
        status: str,
        error: str | None = None,
    ) -> dict:
        """Apply a daemon result to a claimed job.

        Raises :class:`LeaseConflict` when the job is missing, not claimed,
        or the lease does not match.
        """
        now = self.now_iso()
        with self._transaction() as conn:
            row = self._job_row(conn, job_id)
            if (
                row is None
                or row["status"] != "claimed"
                or not row["lease_id"]
                or row["lease_id"] != lease_id
            ):
                raise LeaseConflict(job_id)

            if status == "done":
                conn.execute(
                    """
                    UPDATE print_jobs
                    SET status = 'done', printed_at = ?, updated_at = ?,
                        lease_id = NULL, lease_expires_at = NULL, last_error = NULL
                    WHERE id = ?
                    """,
                    (now, now, job_id),
                )
            elif status == "failed":
                retry = int(row["attempts"]) < int(row["max_attempts"])
                next_status = "pending" if retry else "failed"
                conn.execute(
                    """
                    UPDATE print_jobs
                    SET status = ?, updated_at = ?, last_error = ?,
                        lease_id = NULL, lease_expires_at = NULL
                    WHERE id = ?
                    """,
                    (next_status, now, error, job_id),
                )
            elif status == "unknown":
                conn.execute(
                    """
                    UPDATE print_jobs
                    SET status = 'needs_attention', updated_at = ?, last_error = ?,
                        lease_id = NULL, lease_expires_at = NULL
                    WHERE id = ?
                    """,
                    (now, error, job_id),
                )
            else:  # pragma: no cover - Pydantic rejects other values first
                raise ValueError(f"unsupported result status: {status}")

            updated = self._job_row(conn, job_id)
            assert updated is not None
            return self._metadata(updated)

    def reprint_job(self, job_id: str) -> dict | None:
        """Create a fresh pending job copying the original payload."""
        now = self.now_iso()
        new_id = str(uuid.uuid4())
        with self._transaction() as conn:
            source = self._job_row(conn, job_id)
            if source is None:
                return None
            conn.execute(
                """
                INSERT INTO print_jobs (
                    id, printer_id, kind, source_ref, dedupe_key, payload,
                    payload_sha256, status, attempts, max_attempts,
                    lease_id, lease_expires_at, created_at, updated_at,
                    claimed_at, printed_at, last_error, reprint_of
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, 'pending', 0, ?, NULL, NULL,
                          ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    new_id,
                    source["printer_id"],
                    source["kind"],
                    source["source_ref"],
                    sqlite3.Binary(bytes(source["payload"])),
                    source["payload_sha256"],
                    source["max_attempts"],
                    now,
                    now,
                    source["id"],
                ),
            )
            row = self._job_row(conn, new_id)
            assert row is not None
            return self._metadata(row)

    # -- printers -----------------------------------------------------------

    def heartbeat(
        self, *, printer_id: str, state: str, detail: str | None = None
    ) -> dict:
        now = self.now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO print_printers (
                    printer_id, state, detail, last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(printer_id) DO UPDATE SET
                    state = excluded.state,
                    detail = excluded.detail,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (printer_id, state, detail, now, now),
            )
            row = conn.execute(
                "SELECT * FROM print_printers WHERE printer_id = ?",
                (printer_id,),
            ).fetchone()
            assert row is not None
            return dict(row)

    def get_printer(self, printer_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM print_printers WHERE printer_id = ?",
                (printer_id,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            conn.close()


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
