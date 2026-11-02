"""Persistent scheduler run records with per-period leases.

Every scheduled task runs at most once per period across all API workers.
A claim is an atomic upsert that succeeds only when the period is new, the
previous attempt failed, or the current lease expired.  A crashed worker
therefore leaves a row that another worker can reclaim after the lease.

The table lives in ``league.db`` next to the game state so a single SQLite
transaction is the only coordination primitive the scheduler needs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from .. import calendar as cal

JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"


class JobRunMixin:
    """Claim, finish, and inspect scheduler run records."""

    def claim_job_run(
        self,
        name: str,
        period_key: str,
        *,
        now: datetime | str | None = None,
        lease_seconds: float = 300.0,
    ) -> str | None:
        """Atomically claim one ``(name, period_key)`` period.

        Returns a fresh ``run_id`` when this caller owns the period, or ``None``
        when another live worker owns it or the period already succeeded.
        """

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        started_at = cal.iso_ts(local_now)
        lease_until = cal.iso_ts(local_now + timedelta(seconds=lease_seconds))
        run_id = uuid.uuid4().hex
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO job_runs "
                "(name, period_key, status, attempts, run_id, started_at, "
                "finished_at, lease_until, error) "
                "VALUES (?, ?, 'running', 1, ?, ?, NULL, ?, NULL) "
                "ON CONFLICT(name, period_key) DO UPDATE SET "
                "status = 'running', "
                "attempts = job_runs.attempts + 1, "
                "run_id = excluded.run_id, "
                "started_at = excluded.started_at, "
                "finished_at = NULL, "
                "lease_until = excluded.lease_until, "
                "error = NULL "
                "WHERE job_runs.status != 'succeeded' AND ("
                "job_runs.status != 'running' "
                "OR job_runs.lease_until IS NULL "
                "OR job_runs.lease_until < excluded.started_at)",
                (name, period_key, run_id, started_at, lease_until),
            )
            if cursor.rowcount == 0:
                return None
        return run_id

    def finish_job_run(
        self,
        name: str,
        period_key: str,
        run_id: str,
        *,
        now: datetime | str | None = None,
    ) -> bool:
        """Mark a claimed run as successful; stale claims are ignored."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE job_runs SET status = 'succeeded', finished_at = ?, "
                "lease_until = NULL, error = NULL "
                "WHERE name = ? AND period_key = ? AND run_id = ? "
                "AND status = 'running'",
                (cal.iso_ts(local_now), name, period_key, run_id),
            )
            return cursor.rowcount > 0

    def renew_job_run(
        self,
        name: str,
        period_key: str,
        run_id: str,
        *,
        now: datetime | str | None = None,
        lease_seconds: float = 60.0,
    ) -> bool:
        """Extend a live lease so a slow job is not stolen by another worker."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        lease_until = cal.iso_ts(local_now + timedelta(seconds=lease_seconds))
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE job_runs SET lease_until = ? "
                "WHERE name = ? AND period_key = ? AND run_id = ? "
                "AND status = 'running'",
                (lease_until, name, period_key, run_id),
            )
            return cursor.rowcount > 0

    def fail_job_run(
        self,
        name: str,
        period_key: str,
        run_id: str,
        *,
        error: str,
        now: datetime | str | None = None,
    ) -> bool:
        """Record a failed attempt so the next scheduler tick may retry it."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE job_runs SET status = 'failed', finished_at = ?, "
                "lease_until = NULL, error = ? "
                "WHERE name = ? AND period_key = ? AND run_id = ? "
                "AND status = 'running'",
                (
                    cal.iso_ts(local_now),
                    error[:2000],
                    name,
                    period_key,
                    run_id,
                ),
            )
            return cursor.rowcount > 0

    def get_job_run(self, name: str, period_key: str) -> dict[str, Any] | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM job_runs WHERE name = ? AND period_key = ?",
                (name, period_key),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_job_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM job_runs ORDER BY started_at DESC, name, "
                "period_key LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]


__all__ = [
    "JOB_STATUS_FAILED",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCEEDED",
    "JobRunMixin",
]
