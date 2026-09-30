"""Optional PostgreSQL metadata repositories.

The adapters store validated canonical/job payloads as JSONB while keeping
the repository boundary independent from the database driver. They are lazy
about importing psycopg so the base installation remains usable locally.
"""

from __future__ import annotations

import json
import re

from ocr_platform.domain import Document, VerificationStatus
from ocr_platform.errors import BackendUnavailableError, StorageFailureError
from ocr_platform.workers.models import JobRecord

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _PostgresRepository:
    def __init__(self, dsn: str, *, schema_name: str = "public") -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty")
        if not _SAFE_IDENTIFIER.fullmatch(schema_name):
            raise ValueError("PostgreSQL schema name is unsafe")
        self.dsn = dsn
        self.schema_name = schema_name

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise BackendUnavailableError(
                "PostgreSQL persistence requires the optional 'distributed' extra"
            ) from exc
        try:
            return psycopg.connect(self.dsn)
        except Exception as exc:
            raise StorageFailureError("PostgreSQL connection failed") from exc


class PostgresDocumentRepository(_PostgresRepository):
    def ensure_schema(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}")
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {self.schema_name}.ocr_documents ("
                "document_id TEXT PRIMARY KEY, payload JSONB NOT NULL)"
            )

    def save(self, document: Document) -> None:
        payload = document.canonical_dict()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {self.schema_name}.ocr_documents(document_id, payload) "
                "VALUES (%s, %s::jsonb) ON CONFLICT (document_id) "
                "DO UPDATE SET payload = EXCLUDED.payload",
                (document.id, json.dumps(payload, ensure_ascii=False)),
            )

    def get(self, document_id: str) -> Document | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT payload FROM {self.schema_name}.ocr_documents WHERE document_id = %s",
                (document_id,),
            )
            row = cursor.fetchone()
        return Document.model_validate(row[0]) if row else None

    def delete(self, document_id: str) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {self.schema_name}.ocr_documents WHERE document_id = %s",
                (document_id,),
            )
            return cursor.rowcount > 0

    def update_status(self, document_id: str, status: VerificationStatus) -> None:
        document = self.get(document_id)
        if document is not None:
            self.save(document.model_copy(update={"status": status}))


class PostgresJobRepository(_PostgresRepository):
    def ensure_schema(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}")
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {self.schema_name}.ocr_jobs ("
                "job_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, "
                "submission_fingerprint TEXT NOT NULL, idempotency_key TEXT, "
                "payload JSONB NOT NULL, UNIQUE(submission_fingerprint))"
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS ocr_jobs_idempotency_idx ON "
                f"{self.schema_name}.ocr_jobs(idempotency_key)"
            )

    def save(self, job: JobRecord) -> None:
        payload = job.model_dump(mode="json", exclude_none=True)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {self.schema_name}.ocr_jobs "
                "(job_id, document_id, submission_fingerprint, idempotency_key, payload) "
                "VALUES (%s, %s, %s, %s, %s::jsonb) "
                "ON CONFLICT (job_id) DO UPDATE SET payload = EXCLUDED.payload, "
                "document_id = EXCLUDED.document_id, "
                "submission_fingerprint = EXCLUDED.submission_fingerprint, "
                "idempotency_key = EXCLUDED.idempotency_key",
                (
                    job.job_id,
                    job.document_id,
                    job.submission_fingerprint,
                    job.idempotency_key,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def get(self, job_id: str) -> JobRecord | None:
        return self._get_where("job_id", job_id)

    def find_by_fingerprint(self, submission_fingerprint: str) -> JobRecord | None:
        return self._get_where("submission_fingerprint", submission_fingerprint)

    def find_by_idempotency_key(self, idempotency_key: str | None) -> JobRecord | None:
        if idempotency_key is None:
            return None
        return self._get_where("idempotency_key", idempotency_key)

    def find_by_document_id(self, document_id: str) -> tuple[JobRecord, ...]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT payload FROM {self.schema_name}.ocr_jobs "
                "WHERE document_id = %s ORDER BY job_id",
                (document_id,),
            )
            rows = cursor.fetchall()
        return tuple(JobRecord.model_validate(row[0]) for row in rows)

    def delete_by_document_id(self, document_id: str) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {self.schema_name}.ocr_jobs WHERE document_id = %s",
                (document_id,),
            )
            return cursor.rowcount

    def _get_where(self, column: str, value: str) -> JobRecord | None:
        if column not in {"job_id", "submission_fingerprint", "idempotency_key"}:
            raise ValueError("unsupported PostgreSQL job lookup column")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT payload FROM {self.schema_name}.ocr_jobs WHERE {column} = %s LIMIT 1",
                (value,),
            )
            row = cursor.fetchone()
        return JobRecord.model_validate(row[0]) if row else None


__all__ = ["PostgresDocumentRepository", "PostgresJobRepository"]
