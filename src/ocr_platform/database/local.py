"""Atomic local persistence adapters for development and single-node workers."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from threading import RLock

from pydantic import ValidationError

from ocr_platform.domain import Document, VerificationStatus
from ocr_platform.errors import ArtifactStorageError, StorageFailureError
from ocr_platform.workers.models import JobRecord

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _safe_id(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value) or value in {".", ".."}:
        raise ArtifactStorageError(f"unsafe {label}")
    return value


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=".write-",
            suffix=".json",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise StorageFailureError("unable to persist metadata") from exc


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageFailureError("persisted metadata is unreadable") from exc
    if not isinstance(value, dict):
        raise StorageFailureError("persisted metadata has an invalid shape")
    return value


class InMemoryJobRepository:
    """Thread-safe repository useful for tests and explicitly ephemeral deployments."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = RLock()

    def save(self, job: JobRecord) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def find_by_fingerprint(self, submission_fingerprint: str) -> JobRecord | None:
        with self._lock:
            return next(
                (
                    job
                    for job in self._jobs.values()
                    if job.submission_fingerprint == submission_fingerprint
                ),
                None,
            )

    def find_by_idempotency_key(self, idempotency_key: str | None) -> JobRecord | None:
        if idempotency_key is None:
            return None
        with self._lock:
            return next(
                (job for job in self._jobs.values() if job.idempotency_key == idempotency_key),
                None,
            )

    def find_by_document_id(self, document_id: str) -> tuple[JobRecord, ...]:
        with self._lock:
            return tuple(
                job for job in self._jobs.values() if job.document_id == document_id
            )

    def delete_by_document_id(self, document_id: str) -> int:
        with self._lock:
            job_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if job.document_id == document_id
            ]
            for job_id in job_ids:
                del self._jobs[job_id]
            return len(job_ids)


class InMemoryDocumentRepository:
    """Thread-safe document repository for isolated API and worker tests."""

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}
        self._lock = RLock()

    def save(self, document: Document) -> None:
        with self._lock:
            self._documents[document.id] = document

    def get(self, document_id: str) -> Document | None:
        with self._lock:
            return self._documents.get(document_id)

    def delete(self, document_id: str) -> bool:
        with self._lock:
            return self._documents.pop(document_id, None) is not None

    def update_status(self, document_id: str, status: VerificationStatus) -> None:
        with self._lock:
            document = self._documents.get(document_id)
            if document is not None:
                self._documents[document_id] = document.model_copy(update={"status": status})


class FileJobRepository:
    """Durable single-node job metadata stored as atomically replaced JSON files."""

    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root.resolve() / "metadata" / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, job_id: str) -> Path:
        return self.root / f"{_safe_id(job_id, 'job id')}.json"

    @staticmethod
    def _parse(payload: dict[str, object]) -> JobRecord:
        try:
            return JobRecord.model_validate(payload)
        except ValidationError as exc:
            raise StorageFailureError("persisted job metadata is invalid") from exc

    def save(self, job: JobRecord) -> None:
        with self._lock:
            _write_json(self._path(job.job_id), job.model_dump(mode="json", exclude_none=True))

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            payload = _read_json(self._path(job_id))
            return self._parse(payload) if payload is not None else None

    def _all(self) -> tuple[JobRecord, ...]:
        jobs: list[JobRecord] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
            payload = _read_json(path)
            if payload is not None:
                jobs.append(self._parse(payload))
        return tuple(jobs)

    def find_by_fingerprint(self, submission_fingerprint: str) -> JobRecord | None:
        with self._lock:
            return next(
                (
                    job
                    for job in self._all()
                    if job.submission_fingerprint == submission_fingerprint
                ),
                None,
            )

    def find_by_idempotency_key(self, idempotency_key: str | None) -> JobRecord | None:
        if idempotency_key is None:
            return None
        with self._lock:
            return next(
                (job for job in self._all() if job.idempotency_key == idempotency_key),
                None,
            )

    def find_by_document_id(self, document_id: str) -> tuple[JobRecord, ...]:
        with self._lock:
            return tuple(job for job in self._all() if job.document_id == document_id)

    def delete_by_document_id(self, document_id: str) -> int:
        with self._lock:
            deleted = 0
            for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise StorageFailureError("unable to inspect job metadata") from exc
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise StorageFailureError("job metadata contains an unsafe file")
                payload = _read_json(path)
                if payload is None:
                    continue
                job = self._parse(payload)
                if job.document_id != document_id:
                    continue
                try:
                    path.unlink()
                except OSError as exc:
                    raise StorageFailureError("unable to delete job metadata") from exc
                deleted += 1
            return deleted

class FileDocumentRepository:
    """Durable canonical-result index for the local deployment adapter."""

    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root.resolve() / "metadata" / "documents"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, document_id: str) -> Path:
        return self.root / f"{_safe_id(document_id, 'document id')}.json"

    def save(self, document: Document) -> None:
        with self._lock:
            _write_json(self._path(document.id), document.canonical_dict())

    def get(self, document_id: str) -> Document | None:
        with self._lock:
            payload = _read_json(self._path(document_id))
            if payload is None:
                return None
            try:
                return Document.model_validate(payload)
            except ValidationError as exc:
                raise StorageFailureError("persisted document metadata is invalid") from exc

    def delete(self, document_id: str) -> bool:
        with self._lock:
            path = self._path(document_id)
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise StorageFailureError("unable to inspect document metadata") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise StorageFailureError("document metadata contains an unsafe file")
            try:
                path.unlink()
            except OSError as exc:
                raise StorageFailureError("unable to delete document metadata") from exc
            return True

    def update_status(self, document_id: str, status: VerificationStatus) -> None:
        with self._lock:
            document = self.get(document_id)
            if document is not None:
                self.save(document.model_copy(update={"status": status}))
