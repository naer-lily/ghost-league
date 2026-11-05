"""Request models for the print queue API.

Every model forbids unknown fields so producer/daemon typos fail loudly with 422.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["done", "failed", "unknown"]
PrinterState = Literal["online", "offline", "unknown"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobCreateRequest(StrictModel):
    printer_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    payload_b64: str
    source_ref: str | None = Field(default=None, max_length=256)
    dedupe_key: str | None = Field(default=None, max_length=256)
    max_attempts: int = Field(default=3, ge=1, le=10)


class ClaimRequest(StrictModel):
    printer_id: str = Field(min_length=1, max_length=128)
    lease_seconds: int = Field(default=60, ge=10, le=300)


class ResultRequest(StrictModel):
    lease_id: str = Field(min_length=1, max_length=128)
    status: JobStatus
    error: str | None = Field(default=None, max_length=2000)


class HeartbeatRequest(StrictModel):
    printer_id: str = Field(min_length=1, max_length=128)
    state: PrinterState
    detail: str | None = Field(default=None, max_length=2000)
