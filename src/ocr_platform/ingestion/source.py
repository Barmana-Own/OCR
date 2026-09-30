"""Source-type detection, signature validation, and immutable source metadata."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

from ocr_platform.domain import DocumentSource
from ocr_platform.errors import InvalidDocumentError, UnsupportedDocumentError
from ocr_platform.storage import sha256_file

from .text_reader import TEXT_CONTENT_TYPES, detect_text_content_type

SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        *TEXT_CONTENT_TYPES,
    }
)
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def detect_content_type_from_bytes(
    data: bytes,
    declared_content_type: str | None = None,
) -> str:
    """Detect a supported type from content bytes without trusting metadata."""

    if not data:
        raise InvalidDocumentError("source is empty")
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"PK\x03\x04"):
        try:
            return _detect_ooxml_content_type(BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise InvalidDocumentError("Office ZIP container is malformed") from exc
    if data.startswith(_OLE_SIGNATURE):
        return _detect_ole_content_type(BytesIO(data))
    text_type = detect_text_content_type(
        data,
        declared_content_type=declared_content_type,
    )
    if text_type is not None:
        return text_type
    raise UnsupportedDocumentError("unsupported or unrecognized document type")


def _detect_text_type_from_suffix(
    path: Path,
    declared_content_type: str | None,
) -> str | None:
    if declared_content_type in TEXT_CONTENT_TYPES:
        return declared_content_type
    suffix = path.suffix.lower()
    return {
        ".txt": "text/plain",
        ".log": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".html": "text/html",
        ".htm": "text/html",
    }.get(suffix)


def detect_content_type(path: Path, declared_content_type: str | None = None) -> str:
    try:
        with path.open("rb") as handle:
            data = handle.read(4 * 1024 * 1024)
    except OSError as exc:
        raise InvalidDocumentError("source could not be read") from exc

    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"PK\x03\x04"):
        try:
            return _detect_ooxml_content_type(path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise InvalidDocumentError("Office ZIP container is malformed") from exc
    if data.startswith(_OLE_SIGNATURE):
        return _detect_ole_content_type(path)
    text_type = detect_text_content_type(
        data,
        declared_content_type=declared_content_type,
    )
    if text_type is not None:
        return text_type
    text_type = _detect_text_type_from_suffix(path, declared_content_type)
    if text_type is not None:
        return text_type
    raise UnsupportedDocumentError("unsupported or unrecognized document type")


def _detect_ooxml_content_type(stream) -> str:
    with zipfile.ZipFile(stream) as archive:
        names = {name.replace("\\", "/").lower() for name in archive.namelist()}
    if "word/document.xml" in names:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if "xl/workbook.xml" in names:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if "ppt/presentation.xml" in names:
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    raise UnsupportedDocumentError("unsupported or unrecognized Office container")


def _detect_ole_content_type(stream) -> str:
    try:
        import olefile
    except ImportError as exc:
        raise UnsupportedDocumentError(
            "legacy OLE Office detection requires the optional 'office' extra"
        ) from exc
    try:
        with olefile.OleFileIO(stream) as ole:
            streams = {"/".join(str(part).lower() for part in entry) for entry in ole.listdir()}
    except Exception as exc:
        raise InvalidDocumentError("legacy Office container is malformed") from exc
    if any(entry.endswith("workbook") for entry in streams):
        return "application/vnd.ms-excel"
    raise UnsupportedDocumentError(
        "legacy Office format is not supported by the configured readers"
    )


def build_document_source(
    path: Path,
    *,
    filename: str,
    declared_content_type: str | None,
    source_uri: str,
) -> DocumentSource:
    if not filename or len(filename) > 255 or any(ord(char) < 32 for char in filename):
        raise InvalidDocumentError("invalid source filename")
    try:
        byte_size = path.stat().st_size
    except OSError as exc:
        raise InvalidDocumentError("source could not be inspected") from exc
    if byte_size == 0:
        raise InvalidDocumentError("source is empty")
    content_type = detect_content_type(path, declared_content_type)
    return DocumentSource(
        filename=filename,
        content_type=content_type,
        byte_size=byte_size,
        checksum_sha256=sha256_file(path),
        source_uri=source_uri,
    )
