"""Bounded native readers for text, CSV, JSON, and HTML sources.

These formats are never rasterized for ordinary text extraction. The reader
creates logical pages with explicit native-text provenance; it does not claim
that a text file has a visual page image.
"""

from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from ocr_platform.domain import CoordinateSpace, PageType
from ocr_platform.errors import InvalidDocumentError

from .models import NativeTextEvidence, NativeTextLine, PageInput

TEXT_CONTENT_TYPES = frozenset(
    {
        "text/plain",
        "text/csv",
        "application/json",
        "text/html",
    }
)


class TextReader:
    """Read bounded UTF-8 text sources into native logical pages."""

    def __init__(self, *, max_page_height: int = 50_000) -> None:
        if max_page_height < 90:
            raise ValueError("maximum logical page height is too small")
        self.max_page_height = max_page_height

    def read(
        self,
        path: Path,
        *,
        content_type: str,
        source_uri: str,
        document_id: str,
    ) -> tuple[PageInput, ...]:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InvalidDocumentError("text source is not valid UTF-8") from exc
        except OSError as exc:
            raise InvalidDocumentError("text source could not be read") from exc
        if "\x00" in text:
            raise InvalidDocumentError("text source contains binary NUL bytes")
        lines = _logical_lines(text, content_type)
        lines_per_page = max(1, (self.max_page_height - 72) // 18)
        pages = tuple(
            _page(
                chunk,
                page_number=page_number,
                source_uri=source_uri,
                document_id=document_id,
            )
            for page_number, start in enumerate(range(0, len(lines), lines_per_page), start=1)
            for chunk in (lines[start : start + lines_per_page],)
        )
        return pages


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")


def _logical_lines(text: str, content_type: str) -> tuple[str, ...]:
    if content_type == "text/html":
        parser = _VisibleTextParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:
            raise InvalidDocumentError("HTML source could not be parsed") from exc
        text = "".join(parser.parts)
    elif content_type == "application/json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidDocumentError("JSON source is malformed") from exc
    elif content_type == "text/csv":
        try:
            list(csv.reader(io.StringIO(text, newline="")))
        except csv.Error as exc:
            raise InvalidDocumentError("CSV source is malformed") from exc
    lines = tuple(line.rstrip("\r") for line in text.splitlines())
    return lines or ("",)


def _page(
    lines: tuple[str, ...],
    *,
    page_number: int,
    source_uri: str,
    document_id: str,
) -> PageInput:
    width = 612.0
    height = max(792.0, 72.0 + len(lines) * 18.0)
    native_lines = tuple(
        NativeTextLine(
            text=line,
            bbox=(36.0, 36.0 + index * 18.0, width - 36.0, 50.0 + index * 18.0),
            block_index=0,
            line_index=index,
        )
        for index, line in enumerate(lines)
        if line.strip()
    )
    character_count = sum(len(line.strip()) for line in lines)
    evidence = NativeTextEvidence(
        character_count=character_count,
        line_count=len(native_lines),
        text_coverage=min(1.0, len(native_lines) * 14.0 * (width - 72.0) / (width * height)),
        plausibility_score=1.0 if character_count else 0.0,
        suspicious_ratio=0.0,
        has_text_objects=bool(native_lines),
        reliable=True,
        reason="native_text_file",
    )
    return PageInput(
        page_number=page_number,
        page_id=f"{document_id}-page-{page_number:04d}",
        width=width,
        height=height,
        coordinate_space=CoordinateSpace.PDF_POINT,
        page_type=PageType.NATIVE_TEXT,
        source_uri=f"{source_uri}#page={page_number}",
        native_text_reliable=True,
        native_text_reason="native_text_file",
        native_lines=native_lines,
        native_text_evidence=evidence,
    )


def is_html_payload(text: str) -> bool:
    return bool(
        re.search(
            r"<\s*(?:!doctype\s+html|html|body|head|title|meta|p|div|span|table|script|main|article)\b",
            text[:4096],
            re.I,
        )
    )


def is_csv_payload(text: str) -> bool:
    rows = text.splitlines()
    if len(rows) < 2:
        return False
    for delimiter in (",", ";", "\t", "|"):
        counts = [row.count(delimiter) for row in rows[:32] if row.strip()]
        if len(counts) >= 2 and counts[0] > 0 and len(set(counts)) == 1:
            return True
    return False


def detect_text_content_type(
    data: bytes,
    *,
    declared_content_type: str | None = None,
) -> str | None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if "\x00" in text:
        return None
    declared = declared_content_type.strip().lower() if declared_content_type else None
    if declared == "application/json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidDocumentError("declared JSON source is malformed") from exc
        return declared
    if declared == "text/html":
        if not is_html_payload(text):
            raise InvalidDocumentError("declared HTML source has no HTML signature")
        return declared
    if declared == "text/csv":
        try:
            rows = list(csv.reader(io.StringIO(text, newline="")))
        except csv.Error as exc:
            raise InvalidDocumentError("declared CSV source is malformed") from exc
        if not rows or not any(delimiter in text for delimiter in (",", ";", "\t", "|")):
            raise InvalidDocumentError("declared CSV source has no tabular signature")
        return declared
    if declared == "text/plain":
        return declared
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            return "application/json"
    if is_html_payload(text):
        return "text/html"
    if is_csv_payload(text):
        return "text/csv"
    # An unlabelled one-line payload has no reliable content signature.  Keep
    # that case fail-closed; callers with a trusted text MIME type or a
    # recognized text-file suffix can still opt into native reading.
    return "text/plain" if text.strip() and any(char in text for char in "\r\n") else None


__all__ = ["TEXT_CONTENT_TYPES", "TextReader", "detect_text_content_type"]
