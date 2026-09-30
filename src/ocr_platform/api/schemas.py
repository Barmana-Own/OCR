from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ocr_platform.workers.models import JobProgress, JobStatus, ProcessingMode


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    pipeline_version: str
    capabilities: list[dict[str, object]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    request_id: str
    retryable: bool = False
    job_id: str | None = None
    document_id: str | None = None


class JobSubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    document_id: str
    status: JobStatus
    mode: ProcessingMode
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    progress: JobProgress
    created_at: datetime
    idempotent_replay: bool = False


class ProcessMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_filename: str = Field(min_length=1, max_length=255)
    content_type_detected: str
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
