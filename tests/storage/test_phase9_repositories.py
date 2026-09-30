from datetime import UTC, datetime
from pathlib import Path

from ocr_platform.config import Settings
from ocr_platform.database.local import FileDocumentRepository, FileJobRepository
from ocr_platform.domain import Document, DocumentSource, ProcessingStatus, VerificationStatus
from ocr_platform.workers.models import JobProgress, JobRecord, JobStatus, ProcessingMode


def _document(document_id: str = "doc-repository") -> Document:
    now = datetime.now(UTC)
    return Document(
        id=document_id,
        pipeline_version="0.1.0",
        source=DocumentSource(
            filename="source.png",
            content_type="image/png",
            byte_size=4,
            checksum_sha256="a" * 64,
            source_uri=f"artifact://{document_id}/source/original.bin",
        ),
        configuration_hash="b" * 64,
        processing_checksum="c" * 64,
        processing_started_at=now,
        processing_finished_at=now,
        processing_status=ProcessingStatus.COMPLETED,
        status=VerificationStatus.ACCEPTED,
    )


def _job(job_id: str = "job-repository") -> JobRecord:
    now = datetime.now(UTC)
    return JobRecord(
        job_id=job_id,
        document_id="doc-repository",
        status=JobStatus.QUEUED,
        mode=ProcessingMode.BALANCED,
        source_checksum="a" * 64,
        configuration_hash="b" * 64,
        submission_fingerprint="c" * 64,
        progress=JobProgress(stage="queued"),
        created_at=now,
    )


def test_file_repositories_round_trip_jobs_and_documents(tmp_path: Path) -> None:
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    jobs = FileJobRepository(settings.storage_root)
    documents = FileDocumentRepository(settings.storage_root)

    job = _job()
    document = _document()
    jobs.save(job)
    documents.save(document)

    assert jobs.get(job.job_id) == job
    assert documents.get("doc-repository") == document
    assert jobs.find_by_fingerprint(job.submission_fingerprint) == job
    assert jobs.find_by_idempotency_key(None) is None
