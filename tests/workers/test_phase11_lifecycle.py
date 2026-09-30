from datetime import UTC, datetime
from pathlib import Path

import pytest

from ocr_platform.database.local import InMemoryDocumentRepository, InMemoryJobRepository
from ocr_platform.domain import Document, DocumentSource, ProcessingStatus, VerificationStatus
from ocr_platform.errors import DocumentBusyError
from ocr_platform.governance.lifecycle import DocumentLifecycleService
from ocr_platform.storage import LocalArtifactStore
from ocr_platform.workers.models import JobRecord, JobStatus, ProcessingMode


def _document(document_id: str) -> Document:
    now = datetime.now(UTC)
    return Document(
        id=document_id,
        pipeline_version="0.1.0",
        source=DocumentSource(
            filename="source.png",
            content_type="image/png",
            byte_size=1,
            checksum_sha256="a" * 64,
            source_uri=f"artifact://{document_id}/uploads/source.bin",
        ),
        configuration_hash="b" * 64,
        processing_checksum="c" * 64,
        processing_started_at=now,
        processing_finished_at=now,
        processing_status=ProcessingStatus.COMPLETED,
        status=VerificationStatus.ACCEPTED,
    )


def _job(document_id: str, status: JobStatus) -> JobRecord:
    return JobRecord(
        job_id=f"job-{document_id}",
        document_id=document_id,
        status=status,
        mode=ProcessingMode.BALANCED,
        source_checksum="a" * 64,
        configuration_hash="b" * 64,
        submission_fingerprint="c" * 64,
        progress={"stage": status.value, "percent": 100 if status is JobStatus.COMPLETED else 1},
    )


def test_document_deletion_removes_private_artifacts_metadata_and_exports(
    tmp_path: Path,
) -> None:
    document_id = "doc-delete"
    store = LocalArtifactStore(tmp_path / "artifacts")
    document_repository = InMemoryDocumentRepository()
    job_repository = InMemoryJobRepository()
    document_repository.save(_document(document_id))
    job_repository.save(_job(document_id, JobStatus.COMPLETED))
    store.put_bytes(document_id, "uploads/source.bin", b"source")
    export_root = tmp_path / "artifacts" / "exports" / document_id
    export_root.mkdir(parents=True)
    (export_root / "manifest.json").write_text("{}\n", encoding="utf-8")

    result = DocumentLifecycleService(
        artifact_store=store,
        document_repository=document_repository,
        job_repository=job_repository,
        export_root=tmp_path / "artifacts" / "exports",
    ).delete_document(document_id)

    assert result.document_metadata_deleted is True
    assert result.job_records_deleted == 1
    assert result.artifact_files_deleted == 1
    assert result.export_files_deleted == 1
    assert document_repository.get(document_id) is None
    assert job_repository.get(f"job-{document_id}") is None
    assert not (tmp_path / "artifacts" / document_id).exists()
    assert not export_root.exists()


def test_document_deletion_rejects_active_jobs(tmp_path: Path) -> None:
    document_id = "doc-busy"
    store = LocalArtifactStore(tmp_path / "artifacts")
    document_repository = InMemoryDocumentRepository()
    job_repository = InMemoryJobRepository()
    document_repository.save(_document(document_id))
    job_repository.save(_job(document_id, JobStatus.RUNNING))

    with pytest.raises(DocumentBusyError):
        DocumentLifecycleService(
            artifact_store=store,
            document_repository=document_repository,
            job_repository=job_repository,
            export_root=tmp_path / "artifacts" / "exports",
        ).delete_document(document_id)

    assert document_repository.get(document_id) is not None
