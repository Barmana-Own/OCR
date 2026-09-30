from pathlib import Path

import fitz

from ocr_platform.config import Settings
from ocr_platform.domain import BlockType, ExtractionMethod, PageType, VerificationStatus
from ocr_platform.pipeline import DocumentPipeline


def test_reliable_native_pdf_text_skips_ocr(tmp_path: Path) -> None:
    path = tmp_path / "native.pdf"
    document_pdf = fitz.open()
    page = document_pdf.new_page(width=300, height=400)
    page.insert_text((40, 60), "Contract 12345")
    document_pdf.save(path)
    document_pdf.close()

    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    document = DocumentPipeline(settings, backends=()).process_path(
        path,
        filename="native.pdf",
        declared_content_type="application/pdf",
    )
    line = document.pages[0].blocks[0].lines[0]
    assert (settings.storage_root / document.id / "source" / "original.bin").is_file()
    assert document.pages[0].page_type == PageType.NATIVE_TEXT
    assert line.extraction.method == ExtractionMethod.NATIVE_PDF_TEXT
    assert line.verification_status == VerificationStatus.VERIFIED
    assert document.warnings == []


def test_image_only_pdf_requires_ocr_backend(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    document_pdf = fitz.open()
    document_pdf.new_page(width=300, height=400)
    document_pdf.save(path)
    document_pdf.close()

    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    document = DocumentPipeline(settings, backends=()).process_path(
        path,
        filename="scan.pdf",
        declared_content_type="application/pdf",
    )
    assert document.pages[0].page_type == PageType.SCANNED
    assert document.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert any("no OCR backend" in warning for warning in document.warnings)


def test_mixed_pdf_preserves_native_text_and_routes_image_region_to_ocr(tmp_path: Path) -> None:
    path = tmp_path / "mixed.pdf"
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 50), False)
    image.clear_with(0xFFFFFF)
    document_pdf = fitz.open()
    page = document_pdf.new_page(width=300, height=400)
    page.insert_text((40, 60), "Contract 12345")
    page.insert_image(fitz.Rect(40, 120, 140, 180), pixmap=image)
    document_pdf.save(path)
    document_pdf.close()

    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    from tests.integration.test_pipeline import DeterministicBackend

    document = DocumentPipeline(settings, backends=(DeterministicBackend(),)).process_path(
        path,
        filename="mixed.pdf",
        declared_content_type="application/pdf",
    )
    page_result = document.pages[0]
    assert page_result.page_type == PageType.MIXED
    assert page_result.blocks[0].block_type in {BlockType.TITLE, BlockType.HEADER}
    assert page_result.blocks[0].reading_order == 0
    assert any(
        line.extraction.method == ExtractionMethod.NATIVE_PDF_TEXT
        for block in page_result.blocks
        for line in block.lines
    )
    assert any(
        line.extraction.method == ExtractionMethod.OCR
        for block in page_result.blocks
        for line in block.lines
    )

