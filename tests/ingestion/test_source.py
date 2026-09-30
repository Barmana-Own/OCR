from pathlib import Path

import pytest

from ocr_platform.errors import InvalidDocumentError, UnsupportedDocumentError
from ocr_platform.ingestion.source import build_document_source, detect_content_type


def test_detects_pdf_signature(tmp_path: Path) -> None:
    path = tmp_path / "document.bin"
    path.write_bytes(b"%PDF-1.7\nnot-a-complete-pdf")
    assert detect_content_type(path) == "application/pdf"


def test_rejects_unknown_signature(tmp_path: Path) -> None:
    path = tmp_path / "document.bin"
    path.write_bytes(b"not a document")
    with pytest.raises(UnsupportedDocumentError):
        detect_content_type(path)


def test_build_source_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.touch()
    with pytest.raises(InvalidDocumentError, match="empty"):
        build_document_source(
            path,
            filename="empty.pdf",
            declared_content_type="application/pdf",
            source_uri="artifact://doc-1/empty.pdf",
        )
