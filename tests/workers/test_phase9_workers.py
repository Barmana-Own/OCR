from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.database.local import InMemoryDocumentRepository, InMemoryJobRepository
from ocr_platform.domain import Document, DocumentSource, ProcessingStatus, VerificationStatus
from ocr_platform.errors import InvalidDocumentError, OcrBackendFailure
from ocr_platform.storage import LocalArtifactStore
from ocr_platform.workers.models import JobStatus, ProcessingMode
from ocr_platform.workers.orchestrator import DocumentJobService
from ocr_platform.workers.policy import ProcessingModePolicy


def _png_bytes() -> bytes:
    from io import BytesIO

    stream = BytesIO()
    Image.new("RGB", (12, 12), "white").save(stream, format="PNG")
    return stream.getvalue()


def _document(document_id: str, *, warnings: list[str] | None = None) -> Document:
    now = datetime.now(UTC)
    warnings = warnings or []
    return Document(
        id=document_id,
        pipeline_version="0.1.0",
        source=DocumentSource(
            filename="source.png",
            content_type="image/png",
            byte_size=1,
            checksum_sha256="a" * 64,
            source_uri=f"artifact://{document_id}/source/original.bin",
        ),
        configuration_hash="b" * 64,
        processing_checksum="c" * 64,
        processing_started_at=now,
        processing_finished_at=now,
        processing_status=(
            ProcessingStatus.COMPLETED_WITH_WARNINGS
            if warnings
            else ProcessingStatus.COMPLETED
        ),
        status=(
            VerificationStatus.HUMAN_REVIEW_REQUIRED
            if warnings
            else VerificationStatus.ACCEPTED
        ),
        warnings=warnings,
    )


class RecordingPipeline:
    def __init__(self, *, failure: bool = False, warnings: list[str] | None = None) -> None:
        self.failure = failure
        self.warnings = warnings or []
        self.calls = 0

    def process_path(
        self,
        path: Path,
        *,
        filename: str,
        declared_content_type: str | None = None,
        document_id: str | None = None,
        progress_callback=None,
    ) -> Document:
        self.calls += 1
        if progress_callback is not None:
            progress_callback(1, 1, "ocr")
        if self.failure:
            raise OcrBackendFailure("test backend failed")
        assert document_id is not None
        return _document(document_id, warnings=self.warnings)


def _service(tmp_path: Path, pipeline: RecordingPipeline) -> DocumentJobService:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        temporary_workspace=tmp_path / "tmp",
        worker_count=1,
        max_queued_jobs=4,
    )
    return DocumentJobService(
        settings,
        pipeline=pipeline,
        artifact_store=LocalArtifactStore(settings.storage_root),
        job_repository=InMemoryJobRepository(),
        document_repository=InMemoryDocumentRepository(),
    )


def test_processing_modes_are_configured_and_distinct() -> None:
    settings = Settings(environment="test", max_retries=2)

    fast = ProcessingModePolicy.for_mode(settings, ProcessingMode.FAST)
    balanced = ProcessingModePolicy.for_mode(settings, ProcessingMode.BALANCED)
    accurate = ProcessingModePolicy.for_mode(settings, ProcessingMode.ACCURATE)

    assert fast.settings.max_retries == settings.mode_max_retries[0][1]
    assert fast.settings.verification_enable_high_quality_retry is False
    assert balanced.settings.max_retries == settings.max_retries
    assert accurate.settings.max_retries == settings.mode_max_retries[2][1]
    assert accurate.settings.verification_enable_high_quality_retry is True


def test_job_service_is_idempotent_and_persists_lifecycle(tmp_path: Path) -> None:
    pipeline = RecordingPipeline()
    service = _service(tmp_path, pipeline)
    try:
        first = service.submit_bytes(
            _png_bytes(),
            filename="source.png",
            content_type="image/png",
            mode=ProcessingMode.BALANCED,
            idempotency_key="request-1",
        )
        completed = service.wait_for(first.job.job_id, timeout=5)
        second = service.submit_bytes(
            _png_bytes(),
            filename="source.png",
            content_type="image/png",
            mode=ProcessingMode.BALANCED,
            idempotency_key="request-1",
        )
    finally:
        service.shutdown()

    assert completed.status is JobStatus.COMPLETED
    assert completed.progress.completed_pages == (1,)
    assert second.job.job_id == first.job.job_id
    assert second.idempotent_replay is True
    assert pipeline.calls == 1


def test_programmatic_submission_rejects_traversal_filenames(tmp_path: Path) -> None:
    service = _service(tmp_path, RecordingPipeline())
    try:
        with pytest.raises(InvalidDocumentError):
            service.submit_bytes(
                _png_bytes(),
                filename="..",
                content_type="image/png",
            )
    finally:
        service.shutdown()


@pytest.mark.parametrize(
    ("failure", "warnings", "status"),
    [
        (True, [], JobStatus.FAILED),
        (False, ["verification warning"], JobStatus.COMPLETED_WITH_WARNINGS),
    ],
)
def test_job_service_exposes_failure_and_warning_states(
    tmp_path: Path,
    failure: bool,
    warnings: list[str],
    status: JobStatus,
) -> None:
    service = _service(tmp_path, RecordingPipeline(failure=failure, warnings=warnings))
    try:
        submission = service.submit_bytes(
            _png_bytes(),
            filename="source.png",
            content_type="image/png",
            mode="fast",
        )
        job = service.wait_for(submission.job.job_id, timeout=5)
    finally:
        service.shutdown()

    assert job.status is status
    if failure:
        assert job.error is not None
        assert job.error.code == "ocr_backend_failure"
