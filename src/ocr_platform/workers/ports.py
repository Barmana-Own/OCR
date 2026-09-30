"""Application-facing worker ports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ocr_platform.domain import Document
from ocr_platform.workers.models import ProcessingMode


class DocumentProcessor(Protocol):
    """The only pipeline capability required by the job runner."""

    def process_path(
        self,
        path: Path,
        *,
        filename: str,
        declared_content_type: str | None = None,
        document_id: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> Document: ...


PipelineFactory = Callable[[ProcessingMode], DocumentProcessor]


class JobQueue(Protocol):
    """Durable queue boundary used when workers run in separate processes."""

    def enqueue(self, job_id: str) -> None: ...

    def dequeue(self, *, timeout_seconds: int = 5) -> str | None: ...

    def ack(self, job_id: str) -> None: ...
