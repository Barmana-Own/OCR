from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ocr_platform.domain import (
    Block,
    BlockType,
    BoundingBox,
    CoordinateSpace,
    Document,
    DocumentSource,
    ExtractionMetadata,
    ExtractionMethod,
    Line,
    Page,
    PageType,
    Provenance,
    ReviewFlag,
    TextType,
    VerificationStatus,
)


def make_line(*, needs_review: bool = False) -> Line:
    return Line(
        id="line-1",
        raw_text="شماره قرارداد ١٢٣٤٥",
        normalized_text="شماره قرارداد ۱۲۳۴۵",
        bbox=BoundingBox(x0=10, y0=20, x1=200, y1=40),
        confidence=0.91,
        language="fa",
        script="Arabic",
        text_type=TextType.PRINTED,
        reading_order=0,
        needs_review=needs_review,
        source=Provenance(
            document_id="doc-1",
            page_number=1,
            coordinate_space=CoordinateSpace.PDF_POINT,
        ),
        extraction=ExtractionMetadata(
            method=ExtractionMethod.NATIVE_PDF_TEXT,
            backend="pymupdf-native",
            model="embedded-text",
            model_version="1",
            preprocess_variant="none",
        ),
        uncertainty_flags=[ReviewFlag.LOW_CONFIDENCE] if needs_review else [],
    )


def test_line_preserves_raw_and_normalized_text_and_marks_review() -> None:
    line = make_line(needs_review=True)
    assert line.raw_text == "شماره قرارداد ١٢٣٤٥"
    assert line.normalized_text == "شماره قرارداد ۱۲۳۴۵"
    assert line.needs_review is True
    assert line.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED


def test_document_requires_contiguous_page_numbers() -> None:
    block = Block(
        id="block-1",
        block_type=BlockType.PRINTED_TEXT,
        bbox=BoundingBox(x0=0, y0=0, x1=400, y1=100),
        reading_order=0,
        source=Provenance(
            document_id="doc-1",
            page_number=1,
            coordinate_space=CoordinateSpace.PDF_POINT,
        ),
        lines=[make_line()],
    )
    pages = [
        Page(
            page_number=1,
            width=400,
            height=600,
            coordinate_space=CoordinateSpace.PDF_POINT,
            page_type=PageType.NATIVE_TEXT,
            source_uri="artifact://doc-1/page-1",
            blocks=[block],
            native_text_reliable=True,
        ),
        Page(
            page_number=3,
            width=400,
            height=600,
            coordinate_space=CoordinateSpace.PDF_POINT,
            page_type=PageType.NATIVE_TEXT,
            source_uri="artifact://doc-1/page-3",
        ),
    ]
    with pytest.raises(ValidationError, match="contiguous"):
        Document(
            id="doc-1",
            pipeline_version="0.1.0",
            source=DocumentSource(
                filename="source.pdf",
                content_type="application/pdf",
                byte_size=10,
                checksum_sha256="a" * 64,
                source_uri="artifact://doc-1/source.pdf",
            ),
            configuration_hash="b" * 64,
            processing_checksum="c" * 64,
            processing_started_at=datetime.now(UTC),
            pages=pages,
        )


def test_bounding_box_rejects_inverted_coordinates() -> None:
    with pytest.raises(ValidationError, match="ordered"):
        BoundingBox(x0=10, y0=0, x1=5, y1=20)
