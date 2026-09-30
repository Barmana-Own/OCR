"""Source-type detection, signature validation, and immutable source metadata."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from ocr_platform.domain import DocumentSource
from ocr_platform.errors import InvalidDocumentError, UnsupportedDocumentError
from ocr_platform.storage import sha256_file

SUPPORTED_CONTENT_TYPES = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/tiff", "image/webp"}
)
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def detect_content_type_from_bytes(data: bytes) -> str:
    """Detect a supported type from content bytes without trusting metadata."""

    if not data:
        raise InvalidDocumentError("source is empty")
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise UnsupportedDocumentError("unsupported or unrecognized document type")


def detect_content_type(path: Path, declared_content_type: str | None = None) -> str:
    try:
        with path.open("rb") as handle:
            header = handle.read(16)
    except OSError as exc:
        raise InvalidDocumentError("source could not be read") from exc

    for signature, content_type in _SIGNATURES:
        if header.startswith(signature):
            return content_type
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"

    guessed, _ = mimetypes.guess_type(path.name)
    candidate = (declared_content_type or guessed or "").split(";", 1)[0].strip().lower()
    if candidate in SUPPORTED_CONTENT_TYPES:
        return candidate
    raise UnsupportedDocumentError("unsupported or unrecognized document type")


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
