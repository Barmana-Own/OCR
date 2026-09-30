"""Document reader selection and source-to-page ingestion orchestration."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from ocr_platform.config import Settings
from ocr_platform.domain import ProcessingStatus, ProcessingWarning, WarningSeverity
from ocr_platform.errors import InvalidDocumentError, UnsupportedDocumentError
from ocr_platform.storage import ArtifactLayout, ArtifactStore, LocalArtifactStore, sha256_file

from .image_reader import ImageReader
from .models import ArtifactReference, IngestionResult, PageInput, RenderedPage
from .office_reader import (
    DOCX_CONTENT_TYPE,
    PPTX_CONTENT_TYPE,
    XLS_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    OfficeReader,
)
from .pdf_reader import PdfReader
from .source import build_document_source, detect_content_type
from .text_reader import TEXT_CONTENT_TYPES, TextReader


class DocumentReaderService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pdf_reader = PdfReader(settings)
        self.image_reader = ImageReader(settings)
        self.office_reader = OfficeReader(settings)
        self.text_reader = TextReader(max_page_height=settings.max_page_height)

    def read(
        self, path: Path, *, document_id: str, content_type: str, source_uri: str
    ) -> tuple[PageInput, ...]:
        if content_type == "application/pdf":
            return self.pdf_reader.extract(path, document_id=document_id, source_uri=source_uri)
        if content_type.startswith("image/"):
            return self.image_reader.read(
                path,
                source_uri=source_uri,
                document_id=document_id,
            )
        if content_type in {
            DOCX_CONTENT_TYPE,
            XLSX_CONTENT_TYPE,
            PPTX_CONTENT_TYPE,
            XLS_CONTENT_TYPE,
        }:
            return self.office_reader.extract(
                path,
                content_type=content_type,
                source_uri=source_uri,
            )
        if content_type in TEXT_CONTENT_TYPES:
            return self.text_reader.read(
                path,
                content_type=content_type,
                source_uri=source_uri,
                document_id=document_id,
            )
        raise UnsupportedDocumentError("no reader is registered for this content type")

    def render_page(
        self,
        path: Path,
        *,
        content_type: str,
        page_number: int,
        dpi: int,
        source_uri: str,
    ) -> RenderedPage:
        if content_type == "application/pdf":
            return self.pdf_reader.render_page(path, page_number=page_number, dpi=dpi)
        if content_type.startswith("image/"):
            if page_number != 1:
                raise InvalidDocumentError("standalone image inputs contain one page")
            return self.image_reader.render(path, source_uri=source_uri)
        if content_type in {
            DOCX_CONTENT_TYPE,
            XLSX_CONTENT_TYPE,
            PPTX_CONTENT_TYPE,
            XLS_CONTENT_TYPE,
        }:
            return self.office_reader.render_page(
                path,
                content_type=content_type,
                page_number=page_number,
                dpi=dpi,
                source_uri=source_uri,
            )
        if content_type in TEXT_CONTENT_TYPES:
            raise UnsupportedDocumentError(
                "logical text formats do not have a visual page renderer"
            )
        raise UnsupportedDocumentError("no renderer is registered for this content type")


class DocumentIngestionService:
    """Inspect a source and persist only the bounded artifacts needed downstream."""

    def __init__(
        self,
        settings: Settings,
        *,
        artifact_store: ArtifactStore | None = None,
        reader_service: DocumentReaderService | None = None,
        layout: ArtifactLayout | None = None,
    ) -> None:
        self.settings = settings
        self.store = artifact_store or LocalArtifactStore(settings.storage_root)
        self.readers = reader_service or DocumentReaderService(settings)
        self.layout = layout or ArtifactLayout()

    def ingest(
        self,
        path: Path,
        *,
        filename: str,
        declared_content_type: str | None = None,
        document_id: str | None = None,
    ) -> IngestionResult:
        if not path.is_file():
            raise InvalidDocumentError("source file does not exist")
        try:
            source_size = path.stat().st_size
        except OSError as exc:
            raise InvalidDocumentError("source file could not be inspected") from exc
        if source_size <= 0:
            raise InvalidDocumentError("source is empty")
        if source_size > self.settings.max_upload_bytes:
            raise InvalidDocumentError("source exceeds configured size limit")

        content_type = detect_content_type(path, declared_content_type)
        source_checksum = sha256_file(path)
        resolved_document_id = document_id or f"doc-{source_checksum[:16]}"
        self._validate_document_id(resolved_document_id)
        source_artifact = self._store_source(resolved_document_id, path, source_checksum)
        source_uri = source_artifact.uri
        source = build_document_source(
            source_artifact.path,
            filename=filename,
            declared_content_type=content_type,
            source_uri=source_uri,
        )
        pages = self.readers.read(
            source_artifact.path,
            document_id=resolved_document_id,
            content_type=source.content_type,
            source_uri=source_uri,
        )
        if not pages:
            raise InvalidDocumentError("document contains no pages")
        if len(pages) > self.settings.max_pages:
            raise InvalidDocumentError("source exceeds configured page limit")

        warnings: list[ProcessingWarning] = []
        inspected_pages: list[PageInput] = []
        for page in pages:
            page_warnings = self._page_warnings(resolved_document_id, page)
            warnings.extend(page_warnings)
            if page.needs_ocr:
                dpi = (
                    self.settings.tiny_text_dpi
                    if self._is_tiny_text(page)
                    else self.settings.default_dpi
                )
                rendered = self.readers.render_page(
                    source_artifact.path,
                    content_type=source.content_type,
                    page_number=page.page_number,
                    dpi=dpi,
                    source_uri=page.source_uri,
                )
                artifact_name = self.layout.page_render_name(page.page_number, rendered.dpi)
                stored = self.store.put_bytes(
                    resolved_document_id,
                    artifact_name,
                    rendered.image_bytes,
                    overwrite=True,
                )
                page = replace(
                    page,
                    quality=rendered.quality or page.quality,
                    render_artifact=ArtifactReference(
                        uri=stored.uri,
                        checksum_sha256=stored.checksum_sha256,
                        byte_size=stored.byte_size,
                        media_type="image/png",
                        kind="page_render",
                        width=rendered.width,
                        height=rendered.height,
                        dpi=rendered.dpi,
                    ),
                )
            inspected_pages.append(page)

        return IngestionResult(
            document_id=resolved_document_id,
            source=source,
            source_artifact=ArtifactReference(
                uri=source_artifact.uri,
                checksum_sha256=source_artifact.checksum_sha256,
                byte_size=source_artifact.byte_size,
                media_type=source.content_type,
                kind="source",
            ),
            pages=tuple(inspected_pages),
            warnings=tuple(warnings),
            processing_status=(
                ProcessingStatus.COMPLETED_WITH_WARNINGS
                if warnings
                else ProcessingStatus.COMPLETED
            ),
        )

    @staticmethod
    def _validate_document_id(document_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", document_id):
            raise InvalidDocumentError("invalid document id")

    def _store_source(self, document_id: str, path: Path, checksum: str):
        artifact_name = self.layout.source_name
        if self.store.exists(document_id, artifact_name):
            existing = self.store.get(document_id, artifact_name)
            if existing.checksum_sha256 != checksum:
                raise InvalidDocumentError("document id already references a different source")
            return existing
        try:
            return self.store.put_bytes(
                document_id,
                artifact_name,
                path.read_bytes(),
            )
        except OSError as exc:
            raise InvalidDocumentError("source could not be copied to artifact storage") from exc

    def _page_warnings(
        self, document_id: str, page: PageInput
    ) -> tuple[ProcessingWarning, ...]:
        evidence = page.native_text_evidence
        if evidence is None or evidence.reliable or evidence.reason == "no_embedded_text":
            return ()
        return (
            ProcessingWarning(
                code="native_text_unreliable",
                severity=WarningSeverity.WARNING,
                phase="inspect_source",
                message=evidence.reason,
                document_id=document_id,
                page_number=page.page_number,
            ),
        )

    def _is_tiny_text(self, page: PageInput) -> bool:
        return any(
            (line.bbox[3] - line.bbox[1]) < self.settings.tiny_text_line_height_points
            for line in page.native_lines
            if line.bbox[3] > line.bbox[1]
        )



