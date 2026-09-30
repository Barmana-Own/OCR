"""Dedicated Redis-backed document worker entry point."""

from __future__ import annotations

from ocr_platform.config import get_settings
from ocr_platform.database import build_metadata_repositories
from ocr_platform.observability.logging import configure_logging
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.storage import build_artifact_store
from ocr_platform.workers import ProcessingMode, ProcessingModePolicy, build_job_queue
from ocr_platform.workers.orchestrator import DocumentJobService


def main() -> int:
    settings = get_settings()
    configure_logging(allow_sensitive_debug_logging=settings.allow_sensitive_debug_logging)
    queue = build_job_queue(settings)
    if queue is None:
        raise RuntimeError("OCR_QUEUE_BACKEND=redis is required for the worker entry point")
    store = build_artifact_store(settings)
    documents, jobs = build_metadata_repositories(settings)

    def pipeline_factory(mode: ProcessingMode) -> DocumentPipeline:
        mode_settings = ProcessingModePolicy.for_mode(settings, mode).settings
        return DocumentPipeline(mode_settings, artifact_store=store)

    service = DocumentJobService(
        settings,
        pipeline_factory=pipeline_factory,
        artifact_store=store,
        document_repository=documents,
        job_repository=jobs,
        job_queue=queue,
    )
    try:
        while True:
            job_id = queue.dequeue(timeout_seconds=5)
            if job_id is not None:
                service.run_job(job_id)
    finally:
        service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
