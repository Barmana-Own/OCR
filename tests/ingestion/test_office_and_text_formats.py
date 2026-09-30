from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from ocr_platform.config import Settings
from ocr_platform.domain import PageType
from ocr_platform.errors import InvalidDocumentError, UnsupportedDocumentError
from ocr_platform.ingestion import OfficeReader, TextReader
from ocr_platform.ingestion.source import (
    detect_content_type,
    detect_content_type_from_bytes,
)


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _docx() -> bytes:
    return _zip_bytes(
        {
            "word/document.xml": (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>سلام OCR</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
        }
    )


def _xlsx() -> bytes:
    return _zip_bytes(
        {
            "xl/workbook.xml": (
                '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Data" r:id="rId1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>نام</t></is></c>'
                '<c r="B1" t="inlineStr"><is><t>Alice</t></is></c></row></sheetData>'
                "</worksheet>"
            ),
        }
    )


def _pptx() -> bytes:
    return _zip_bytes(
        {
            "ppt/presentation.xml": (
                '<p:presentation '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldSz cx="9144000" cy="6858000"/>'
                '<p:sldIdLst><p:sldId id="1" r:id="rId1"/></p:sldIdLst></p:presentation>'
            ),
            "ppt/_rels/presentation.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="slides/slide1.xml"/>'
                "</Relationships>"
            ),
            "ppt/slides/slide1.xml": (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<p:sp><p:txBody><a:p><a:r><a:t>عنوان اسلاید</a:t></a:r></a:p></p:txBody>'
                '<p:spPr><a:xfrm><a:off x="12700" y="12700"/><a:ext cx="1000000" cy="300000"/>'
                "</a:xfrm></p:spPr></p:sp>"
                '<p:pic><p:spPr><a:xfrm><a:off x="2000000" y="2000000"/>'
                '<a:ext cx="1000000" cy="1000000"/></a:xfrm></p:spPr></p:pic>'
                "</p:sld>"
            ),
        }
    )


def test_ooxml_detection_uses_container_members_and_native_readers(tmp_path: Path) -> None:
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    reader = OfficeReader(settings)
    cases = (
        (
            _docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "سلام OCR",
        ),
        (
            _xlsx(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "نام",
        ),
        (
            _pptx(),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "عنوان اسلاید",
        ),
    )
    for index, (data, content_type, expected_text) in enumerate(cases):
        path = tmp_path / f"office-{index}.bin"
        path.write_bytes(data)
        assert detect_content_type_from_bytes(data) == content_type
        assert detect_content_type(path, "application/octet-stream") == content_type
        pages = reader.extract(path, content_type=content_type, source_uri=f"artifact://doc-{index}/source")
        assert pages[0].native_text_reliable is True
        assert any(expected_text in line.text for line in pages[0].native_lines)


def test_pptx_embedded_image_is_marked_for_visual_ocr(tmp_path: Path) -> None:
    path = tmp_path / "slides.pptx"
    path.write_bytes(_pptx())
    pages = OfficeReader(Settings(environment="test", storage_root=tmp_path / "artifacts")).extract(
        path,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source_uri="artifact://doc/source",
    )
    assert pages[0].page_type is PageType.MIXED
    assert pages[0].needs_ocr is True
    assert pages[0].image_regions


def test_text_formats_are_native_and_never_require_visual_rendering(tmp_path: Path) -> None:
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    reader = TextReader(max_page_height=120)
    path = tmp_path / "source.txt"
    path.write_text("شماره قرارداد ۱۲۳\nsecond line", encoding="utf-8")
    pages = reader.read(
        path,
        content_type="text/plain",
        source_uri="artifact://doc/source.txt",
        document_id="doc-text",
    )
    assert pages[0].native_text_reliable is True
    assert pages[0].native_lines[0].text == "شماره قرارداد ۱۲۳"
    assert detect_content_type(path, "text/plain") == "text/plain"
    with pytest.raises(UnsupportedDocumentError, match="not have a visual"):
        from ocr_platform.ingestion import DocumentReaderService

        DocumentReaderService(settings).render_page(
            path,
            content_type="text/plain",
            page_number=1,
            dpi=300,
            source_uri="artifact://doc/source.txt",
        )


def test_text_signature_detection_rejects_malformed_declared_json() -> None:
    with pytest.raises(InvalidDocumentError, match="JSON"):
        detect_content_type_from_bytes(b"{not-json}", "application/json")


def test_malformed_office_zip_is_typed_as_invalid() -> None:
    with pytest.raises(InvalidDocumentError, match="ZIP"):
        detect_content_type_from_bytes(b"PK\x03\x04not-a-zip")
