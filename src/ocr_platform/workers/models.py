"""Provider-neutral job and processing-mode contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ocr_platform.domain.models import Sha256


class ProcessingMode(StrEnum):
    """User-visible processing policy; separate from OCR certainty."""

    FAST = "fast"
    BALANCED = "balanced"
    ACCURATE = "accurate"


class JobStatus(StrEnum):
    """Lifecycle state for asynchronous processing submissions."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    current_page: int = Field(default=0, ge=0)
    total_pages: int = Field(default=0, ge=0)
    completed_pages: tuple[int, ...] = Field(default_factory=tuple)
    stage: str = Field(default="queued", min_length=1, max_length=128)
    percent: float = Field(default=0.0, ge=0.0, le=100.0)


class JobError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2048)
    retryable: bool = False


class JobRecord(BaseModel):
    """Persisted job state returned by the API and worker repository."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    status: JobStatus = JobStatus.QUEUED
    mode: ProcessingMode = ProcessingMode.BALANCED
    source_checksum: Sha256
    filename: str = Field(default="uploaded-source", min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", min_length=1, max_length=127)
    configuration_hash: Sha256
    submission_fingerprint: Sha256
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    progress: JobProgress = Field(default_factory=JobProgress)
    error: JobError | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
