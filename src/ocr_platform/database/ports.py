"""Persistence ports. Concrete production adapters are deployment-specific."""

from __future__ import annotations

from typing import Protocol

from ocr_platform.domain import Document, VerificationStatus
from ocr_platform.workers.models import JobRecord


class DocumentRepository(Protocol):
    def save(self, document: Document) -> None: ...

    def get(self, document_id: str) -> Document | None: ...

    def delete(self, document_id: str) -> bool: ...

    def update_status(self, document_id: str, status: VerificationStatus) -> None: ...


class JobRepository(Protocol):
    def save(self, job: JobRecord) -> None: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def find_by_fingerprint(self, submission_fingerprint: str) -> JobRecord | None: ...

    def find_by_idempotency_key(self, idempotency_key: str | None) -> JobRecord | None: ...

    def find_by_document_id(self, document_id: str) -> tuple[JobRecord, ...]: ...

    def delete_by_document_id(self, document_id: str) -> int: ...

class ReviewRepository(Protocol):
    def append_decision(
        self, document_id: str, line_id: str, decision: str, actor_id: str
    ) -> None: ...
