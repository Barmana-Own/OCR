"""Secure document deletion and private-artifact lifecycle operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from ocr_platform.database.ports import DocumentRepository, JobRepository
from ocr_platform.errors import DocumentBusyError, DocumentNotFoundError
from ocr_platform.storage import ArtifactStore, safe_delete_private_tree
from ocr_platform.workers.models import JobStatus


@dataclass(frozen=True)
class DocumentDeletionResult:
    document_id: str
    artifact_files_deleted: int
    export_files_deleted: int
    job_records_deleted: int
    document_metadata_deleted: bool

    def to_payload(self) -> dict[str, object]:
        return asdict(self) | {"deleted": True}


class DocumentLifecycleService:
    """Coordinate deletion while preserving active-job and path-safety invariants."""

    _ACTIVE_JOB_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        document_repository: DocumentRepository,
        job_repository: JobRepository,
        export_root: Path,
    ) -> None:
        self.artifact_store = artifact_store
        self.document_repository = document_repository
        self.job_repository = job_repository
        self.export_root = export_root

    def delete_document(self, document_id: str) -> DocumentDeletionResult:
        if self.document_repository.get(document_id) is None:
            raise DocumentNotFoundError()
        jobs = self.job_repository.find_by_document_id(document_id)
        if any(job.status in self._ACTIVE_JOB_STATUSES for job in jobs):
            raise DocumentBusyError()

        artifact_files_deleted = self.artifact_store.delete_document(document_id)
        export_files_deleted = safe_delete_private_tree(
            self.export_root,
            document_id,
            label="document export",
        )
        document_metadata_deleted = self.document_repository.delete(document_id)
        job_records_deleted = self.job_repository.delete_by_document_id(document_id)
        return DocumentDeletionResult(
            document_id=document_id,
            artifact_files_deleted=artifact_files_deleted,
            export_files_deleted=export_files_deleted,
            job_records_deleted=job_records_deleted,
            document_metadata_deleted=document_metadata_deleted,
        )
