"""Bounded multipart upload validation independent of OCR execution."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import UploadFile

from ocr_platform.errors import InvalidDocumentError, UnsupportedDocumentError
from ocr_platform.ingestion.source import detect_content_type_from_bytes


def validate_filename(filename: str | None) -> str:
    if not filename:
        raise InvalidDocumentError("filename is required")
    if (
        len(filename) > 255
        or any(char in filename for char in "/\\:")
        or any(ord(char) < 32 for char in filename)
        or filename in {".", ".."}
    ):
        raise InvalidDocumentError("filename contains unsafe characters")
    return filename


async def read_upload_bytes(upload: UploadFile, *, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        raise InvalidDocumentError("upload size limit is invalid")
    buffer = bytearray()
    while chunk := await upload.read(1024 * 1024):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise InvalidDocumentError("upload exceeds configured size limit")
    if not buffer:
        raise InvalidDocumentError("source is empty")
    return bytes(buffer)


def validate_upload_content(
    data: bytes,
    *,
    declared_content_type: str | None,
    allowed_content_types: Iterable[str],
) -> str:
    detected = detect_content_type_from_bytes(data)
    allowed = frozenset(allowed_content_types)
    if detected not in allowed:
        raise UnsupportedDocumentError("detected document type is not allowed")
    declared = (declared_content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared != "application/octet-stream":
        if declared not in allowed:
            raise UnsupportedDocumentError("declared content type is not allowed")
        if declared != detected:
            raise InvalidDocumentError("declared content type does not match file signature")
    return detected
