"""Explicit metadata repository construction for local and PostgreSQL deployments."""

from __future__ import annotations

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError

from .local import FileDocumentRepository, FileJobRepository
from .ports import DocumentRepository, JobRepository
from .postgres import PostgresDocumentRepository, PostgresJobRepository


def build_metadata_repositories(
    settings: Settings,
) -> tuple[DocumentRepository, JobRepository]:
    if settings.metadata_backend == "file":
        return (
            FileDocumentRepository(settings.storage_root),
            FileJobRepository(settings.storage_root),
        )
    if settings.metadata_backend == "postgres" and settings.postgres_dsn:
        documents = PostgresDocumentRepository(
            settings.postgres_dsn,
            schema_name=settings.postgres_schema,
        )
        jobs = PostgresJobRepository(
            settings.postgres_dsn,
            schema_name=settings.postgres_schema,
        )
        documents.ensure_schema()
        jobs.ensure_schema()
        return documents, jobs
    raise ConfigurationError("unsupported metadata backend")


__all__ = ["build_metadata_repositories"]
