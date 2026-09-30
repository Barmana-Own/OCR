"""Bounded asynchronous document job orchestration."""

from __future__ import annotations

import inspect
import tempfile
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore, RLock

from ocr_platform.config import Settings
from ocr_platform.database.ports import DocumentRepository, JobRepository
from ocr_platform.dataset import DatasetExport, DatasetExporter, DatasetExportPolicy
from ocr_platform.domain import Document, ProcessingStatus
from ocr_platform.errors import (
    ConfigurationError,
    DocumentNotFoundError,
    IdempotencyConflictError,
    InvalidDocumentError,
    JobNotFoundError,
    OcrPlatformError,
    QueueCapacityError,
)
from ocr_platform.governance.lifecycle import (
    DocumentDeletionResult,
    DocumentLifecycleService,
)
from ocr_platform.ingestion.source import detect_content_type_from_bytes
from ocr_platform.observability.logging import get_logger
from ocr_platform.observability.metrics import MetricsRegistry
from ocr_platform.observability.tracing import trace_span
from ocr_platform.storage import ArtifactStore, LocalArtifactStore, sha256_bytes
from ocr_platform.utils import stable_hash

from .models import JobError, JobProgress, JobRecord, JobStatus, ProcessingMode
from .policy import ProcessingModePolicy
from .ports import DocumentProcessor, JobQueue, PipelineFactory

logger = get_logger(__name__)


@dataclass(frozen=True)
class JobSubmission:
    job: JobRecord
    idempotent_replay: bool = False


class DocumentJobService:
    """Submit and monitor work without coupling transport to OCR providers."""

    _UPLOAD_ARTIFACT_TEMPLATE = "uploads/source-{checksum}.bin"

    def __init__(
        self,
        settings: Settings,
        *,
        pipeline: DocumentProcessor | None = None,
        pipeline_factory: PipelineFactory | None = None,
        artifact_store: ArtifactStore | None = None,
        job_repository: JobRepository | None = None,
        document_repository: DocumentRepository | None = None,
        executor: Executor | None = None,
        job_queue: JobQueue | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        if pipeline is None and pipeline_factory is None:
            raise ConfigurationError("a document pipeline or pipeline factory is required")
        self.settings = settings
        self._pipeline = pipeline
        self._pipeline_factory = pipeline_factory
        self.artifact_store = artifact_store or getattr(
            pipeline, "store", None
        ) or LocalArtifactStore(settings.storage_root)
        if job_repository is None or document_repository is None:
            raise ConfigurationError("job and document repositories are required")
        self.job_repository = job_repository
        self.document_repository = document_repository
        self.metrics = metrics or MetricsRegistry()
        self._lifecycle = DocumentLifecycleService(
            artifact_store=self.artifact_store,
            document_repository=self.document_repository,
            job_repository=self.job_repository,
            export_root=settings.storage_root / "exports",
        )
        self._job_queue = job_queue
        self._executor = executor or (
            ThreadPoolExecutor(
                max_workers=settings.worker_count,
                thread_name_prefix="ocr-worker",
            )
            if job_queue is None
            else None
        )
        self._owns_executor = executor is None and job_queue is None
        self._capacity = BoundedSemaphore(settings.worker_count + settings.max_queued_jobs)
        self._page_capacity = BoundedSemaphore(settings.max_pages_in_flight)
        self._submission_lock = RLock()
        self._closed = False

    def submit_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str,
        mode: ProcessingMode | str = ProcessingMode.BALANCED,
        idempotency_key: str | None = None,
    ) -> JobSubmission:
        if not data:
            raise InvalidDocumentError("source is empty")
        if len(data) > self.settings.max_upload_bytes:
            raise InvalidDocumentError("upload exceeds configured size limit")
        if (
            not filename
            or len(filename) > 255
            or any(char in filename for char in "/\\:")
            or any(ord(char) < 32 for char in filename)
            or filename in {".", ".."}
        ):
            raise InvalidDocumentError("filename contains unsafe characters")
        detected_content_type = detect_content_type_from_bytes(
            data,
            declared_content_type=content_type,
        )
        if (
            not content_type
            or content_type not in self.settings.allowed_content_types
            or content_type != detected_content_type
        ):
            raise InvalidDocumentError("unsupported detected content type")
        try:
            selected_mode = ProcessingMode(mode)
        except ValueError as exc:
            raise InvalidDocumentError("processing mode is invalid") from exc
        normalized_key = self._validate_idempotency_key(idempotency_key)
        source_checksum = sha256_bytes(data)
        mode_policy = ProcessingModePolicy.for_mode(self.settings, selected_mode)
        configuration_hash = mode_policy.settings.configuration_hash
        fingerprint = stable_hash(
            {
                "source_checksum": source_checksum,
                "configuration_hash": configuration_hash,
                "mode": selected_mode.value,
                "idempotency_key": normalized_key,
            }
        )
        with self._submission_lock:
            keyed = self.job_repository.find_by_idempotency_key(normalized_key)
            if keyed is not None:
                if keyed.submission_fingerprint != fingerprint:
                    raise IdempotencyConflictError()
                return JobSubmission(keyed, idempotent_replay=True)
            existing = self.job_repository.find_by_fingerprint(fingerprint)
            if existing is not None:
                return JobSubmission(existing, idempotent_replay=True)
            capacity_acquired = False
            if self._job_queue is None:
                if not self._capacity.acquire(blocking=False):
                    raise QueueCapacityError()
                capacity_acquired = True
            job = JobRecord(
                job_id=f"job-{fingerprint[:24]}",
                document_id=f"doc-{source_checksum[:16]}",
                status=JobStatus.QUEUED,
                mode=selected_mode,
                source_checksum=source_checksum,
                filename=filename,
                content_type=detected_content_type,
                configuration_hash=configuration_hash,
                submission_fingerprint=fingerprint,
                idempotency_key=normalized_key,
                progress=JobProgress(stage="queued"),
            )
            try:
                self._store_upload(job, data)
                self.job_repository.save(job)
                self.metrics.increment("documents_submitted_total")
                if self._job_queue is not None:
                    self._job_queue.enqueue(job.job_id)
                else:
                    assert self._executor is not None
                    self._executor.submit(self._run_job, job.job_id)
            except Exception:
                if capacity_acquired:
                    self._capacity.release()
                raise
            return JobSubmission(job)

    def get_job(self, job_id: str) -> JobRecord:
        job = self.job_repository.get(job_id)
        if job is None:
            raise JobNotFoundError()
        return job

    def get_document(self, document_id: str) -> Document:
        document = self.document_repository.get(document_id)
        if document is None:
            raise DocumentNotFoundError()
        return document

    def delete_document(self, document_id: str) -> DocumentDeletionResult:
        with self._submission_lock:
            return self._lifecycle.delete_document(document_id)

    def wait_for(self, job_id: str, *, timeout: float = 30.0) -> JobRecord:
        deadline = time.monotonic() + timeout
        terminal = {
            JobStatus.COMPLETED,
            JobStatus.COMPLETED_WITH_WARNINGS,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
        while True:
            job = self.get_job(job_id)
            if job.status in terminal:
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job did not finish within {timeout} seconds")
            time.sleep(0.01)

    def export_document(
        self,
        document_id: str,
        *,
        formats: tuple[str, ...],
        policy: DatasetExportPolicy | str = DatasetExportPolicy.ACCEPTED_VERIFIED,
    ) -> DatasetExport:
        document = self.get_document(document_id)
        exporter = DatasetExporter(
            self.artifact_store,
            temporary_workspace=self.settings.export_staging_workspace.resolve(),
        )
        destination = self.settings.storage_root / "exports"
        with trace_span("dataset_export", metrics=self.metrics):
            return exporter.export(document, destination, formats=formats, policy=policy)

    def shutdown(self, *, wait: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_executor and isinstance(self._executor, ThreadPoolExecutor):
            self._executor.shutdown(wait=wait, cancel_futures=False)

    def run_job(self, job_id: str) -> None:
        """Execute one queued job; intended for a dedicated worker process."""

        if self._job_queue is None:
            raise ConfigurationError("run_job requires a durable queue-backed service")
        try:
            self._run_job(job_id, release_capacity=False)
        finally:
            self._job_queue.ack(job_id)

    def _store_upload(self, job: JobRecord, data: bytes) -> None:
        artifact_name = self._upload_artifact_name(job.source_checksum)
        if self.artifact_store.exists(job.document_id, artifact_name):
            existing = self.artifact_store.get(job.document_id, artifact_name)
            if existing.checksum_sha256 != job.source_checksum:
                raise InvalidDocumentError("document id already references a different source")
            return
        self.artifact_store.put_bytes(job.document_id, artifact_name, data)

    @classmethod
    def _upload_artifact_name(cls, checksum: str) -> str:
        return cls._UPLOAD_ARTIFACT_TEMPLATE.format(checksum=checksum)

    @staticmethod
    def _validate_idempotency_key(value: str | None) -> str | None:
        if value is None:
            return None
        if not 1 <= len(value) <= 255 or any(
            ord(char) < 33 or ord(char) > 126 for char in value
        ):
            raise InvalidDocumentError("idempotency key is invalid")
        return value

    def _processor_for(self, mode: ProcessingMode) -> DocumentProcessor:
        if self._pipeline_factory is not None:
            return self._pipeline_factory(mode)
        assert self._pipeline is not None
        return self._pipeline

    def _run_job(self, job_id: str, *, release_capacity: bool = True) -> None:
        started_performance = time.perf_counter()
        deadline = started_performance + self.settings.processing_timeout_seconds
        try:
            with self._submission_lock:
                job = self.get_job(job_id)
                started = datetime.now(UTC)
                job = job.model_copy(
                    update={
                        "status": JobStatus.RUNNING,
                        "started_at": started,
                        "progress": JobProgress(stage="ingestion", percent=1.0),
                    }
                )
                self._save_job(job)
            self.settings.temporary_workspace.mkdir(parents=True, exist_ok=True)
            self._raise_if_deadline_exceeded(deadline)
            source_bytes = self.artifact_store.read_bytes(
                job.document_id, self._upload_artifact_name(job.source_checksum)
            )
            with tempfile.NamedTemporaryFile(
                dir=self.settings.temporary_workspace,
                prefix=f"{job.job_id}-",
                suffix=".upload",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(source_bytes)
            try:
                processor = self._processor_for(job.mode)
                with trace_span("document_processing", metrics=self.metrics):
                    document = self._process_with_progress(
                        processor,
                        temporary_path,
                        job,
                        deadline=deadline,
                    )
            finally:
                temporary_path.unlink(missing_ok=True)
            self._raise_if_deadline_exceeded(deadline)
            status = (
                JobStatus.COMPLETED_WITH_WARNINGS
                if document.processing_status is ProcessingStatus.COMPLETED_WITH_WARNINGS
                or bool(document.warnings)
                else JobStatus.COMPLETED
            )
            finished = datetime.now(UTC)
            with self._submission_lock:
                self.document_repository.save(document)
                current_job = self.get_job(job_id)
                checkpoint_pages = tuple(page.page_number for page in document.pages)
                completed_pages = checkpoint_pages or current_job.progress.completed_pages
                total_pages = max(len(document.pages), current_job.progress.total_pages)
                self._save_job(
                    current_job.model_copy(
                        update={
                            "status": status,
                            "finished_at": finished,
                            "warnings": list(document.warnings),
                            "progress": JobProgress(
                                current_page=max(
                                    len(document.pages), current_job.progress.current_page
                                ),
                                total_pages=total_pages,
                                completed_pages=completed_pages,
                                stage="completed",
                                percent=100.0,
                            ),
                        }
                    )
                )
            self.metrics.increment("documents_processed_total")
            self.metrics.increment("pages_processed_total", len(document.pages))
            review_count = sum(
                line.needs_review
                for page in document.pages
                for block in page.blocks
                for line in block.lines
            )
            if review_count:
                self.metrics.increment("human_review_lines_total", review_count)
            retry_count = sum(
                max(0, len(line.verification_history) - 1)
                for page in document.pages
                for block in page.blocks
                for line in block.lines
            )
            if retry_count:
                self.metrics.increment("ocr_retries_total", retry_count)
            self.metrics.observe(
                "document_processing_latency_seconds",
                time.perf_counter() - started_performance,
                labels={"mode": job.mode.value},
            )
        except OcrPlatformError as exc:
            self._fail_job(job_id, exc.details.code, exc.details.message, exc.details.retryable)
        except Exception:
            logger.exception("unhandled document job failure", extra={"job_id": job_id})
            self._fail_job(job_id, "processing_error", "document processing failed", True)
        finally:
            if release_capacity:
                self._capacity.release()

    def _process_with_progress(
        self,
        processor: DocumentProcessor,
        path: Path,
        job: JobRecord,
        *,
        deadline: float | None = None,
    ) -> Document:
        def progress(current_page: int, total_pages: int, stage: str) -> None:
            if deadline is not None:
                self._raise_if_deadline_exceeded(deadline)
            denominator = max(total_pages, 1)
            percent = min(99.0, max(1.0, 5.0 + (current_page / denominator) * 90.0))
            with self._submission_lock:
                current = self.get_job(job.job_id)
                self.metrics.increment("stage_events_total", labels={"stage": stage})
                completed_pages = set(current.progress.completed_pages)
                if stage not in {"queued", "ingestion", "verification"} and current_page > 0:
                    completed_pages.add(current_page)
                self._save_job(
                    current.model_copy(
                        update={
                            "progress": JobProgress(
                                current_page=max(current_page, 0),
                                total_pages=max(total_pages, 0),
                                completed_pages=tuple(sorted(completed_pages)),
                                stage=stage,
                                percent=percent,
                            )
                        }
                    )
                )

        kwargs: dict[str, object] = {
            "filename": job.filename,
            "declared_content_type": job.content_type,
            "document_id": job.document_id,
        }
        if "progress_callback" in inspect.signature(processor.process_path).parameters:
            kwargs["progress_callback"] = progress
        with self._page_capacity:
            if deadline is not None:
                self._raise_if_deadline_exceeded(deadline)
            result = processor.process_path(path, **kwargs)
            if deadline is not None:
                self._raise_if_deadline_exceeded(deadline)
            return result

    @staticmethod
    def _raise_if_deadline_exceeded(deadline: float) -> None:
        from ocr_platform.errors import ProcessingTimeoutError

        if time.perf_counter() > deadline:
            raise ProcessingTimeoutError()

    def _save_job(self, job: JobRecord) -> None:
        self.job_repository.save(job)

    def _fail_job(self, job_id: str, code: str, message: str, retryable: bool) -> None:
        self.metrics.increment("document_failures_total", labels={"reason": code})
        with self._submission_lock:
            try:
                current = self.get_job(job_id)
            except JobNotFoundError:
                return
            self._save_job(
                current.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "finished_at": datetime.now(UTC),
                        "error": JobError(code=code, message=message, retryable=retryable),
                        "progress": current.progress.model_copy(
                            update={"stage": "failed"}
                        ),
                    }
                )
            )
