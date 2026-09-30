from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ocr_platform.domain.models import (
    BlockResult,
    BlockType,
    BoundingBox,
    CoordinateSpace,
    Document,
    DocumentResult,
    ExtractionMetadata,
    ExtractionMethod,
    LineResult,
    OCRCandidate,
    PageResult,
    PageType,
    PolygonPoint,
    ProcessingManifest,
    ProcessingStatus,
    ProcessingWarning,
    Provenance,
    SourceMetadata,
    TextType,
    VerificationRecord,
    VerificationStatus,
    WordResult,
)

SOURCE_TEXT = "شماره قرارداد ١٢٣٤٥ / Ref ABC-123, https://example.com?q=١"
NORMALIZED_TEXT = "شماره قرارداد ۱۲۳۴۵ / Ref ABC-123, https://example.com?q=١"


def _extraction() -> ExtractionMetadata:
    return ExtractionMetadata(
        method=ExtractionMethod.OCR,
        backend="test-backend",
        model="test-model",
        model_version="1.0",
        dpi=450,
        region_scale=2,
        preprocess_variant="deskew",
    )


def _line() -> LineResult:
    return LineResult(
        id="line-1",
        raw_text=SOURCE_TEXT,
        normalized_text=NORMALIZED_TEXT,
        bbox=BoundingBox(x0=10, y0=20, x1=880, y1=60),
        polygon=[
            PolygonPoint(x=10, y=20),
            PolygonPoint(x=880, y=20),
            PolygonPoint(x=880, y=60),
            PolygonPoint(x=10, y=60),
        ],
        confidence=0.97,
        language="fa",
        script="Arabic",
        text_type=TextType.PRINTED,
        reading_order=1,
        source=Provenance(
            document_id="doc-1",
            page_number=1,
            coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        ),
        extraction=_extraction(),
    )


def _page() -> PageResult:
    line = _line()
    block = BlockResult(
        id="block-1",
        block_type=BlockType.PRINTED_TEXT,
        bbox=BoundingBox(x0=10, y0=20, x1=880, y1=60),
        reading_order=1,
        confidence=0.97,
        source=line.source,
        lines=[line],
    )
    return PageResult(
        page_number=1,
        width=900,
        height=100,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        page_type=PageType.SCANNED,
        source_uri="sha256://page-1",
        rendered_width=900,
        rendered_height=100,
        blocks=[block],
    )


def test_canonical_names_preserve_legacy_aliases_and_raw_text() -> None:
    assert DocumentResult is Document
    assert PageResult.__name__ == "PageResult"
    assert WordResult.__name__ == "WordResult"

    line = _line()
    assert line.raw_text == SOURCE_TEXT
    assert line.normalized_text == NORMALIZED_TEXT
    assert line.raw_text != line.normalized_text

    serialized = line.model_dump(mode="json")
    assert serialized["raw_text"] == SOURCE_TEXT
    assert serialized["normalized_text"] == NORMALIZED_TEXT


def test_document_result_serializes_status_warning_and_provenance() -> None:
    now = datetime.now(UTC)
    source = SourceMetadata(
        filename="mixed-fa-en.pdf",
        content_type="application/pdf",
        byte_size=1234,
        checksum_sha256="a" * 64,
        source_uri="sha256://a",
    )
    warning = ProcessingWarning(
        code="ocr_disagreement",
        phase="verification",
        message="Candidates disagree.",
        page_number=1,
        created_at=now,
    )
    result = DocumentResult(
        id="doc-1",
        pipeline_version="0.2.0",
        source=source,
        configuration_hash="b" * 64,
        processing_checksum="c" * 64,
        processing_started_at=now,
        processing_finished_at=now,
        pages=[_page()],
        status=VerificationStatus.HUMAN_REVIEW_REQUIRED,
        processing_status=ProcessingStatus.COMPLETED_WITH_WARNINGS,
        processing_warnings=[warning],
    )

    payload = result.model_dump(mode="json")
    assert payload["processing_status"] == "completed_with_warnings"
    assert payload["processing_warnings"][0]["code"] == "ocr_disagreement"
    assert payload["pages"][0]["blocks"][0]["lines"][0]["raw_text"] == SOURCE_TEXT
    assert payload["pages"][0]["blocks"][0]["lines"][0]["source"]["page_number"] == 1


def test_geometry_rejects_inversion_and_known_page_bounds() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x0=20, y0=10, x1=19, y1=30)

    with pytest.raises(ValidationError):
        PageResult(
            page_number=1,
            width=100,
            height=100,
            coordinate_space=CoordinateSpace.RENDERED_PIXEL,
            page_type=PageType.IMAGE,
            source_uri="sha256://page-1",
            rendered_width=100,
            rendered_height=100,
            blocks=[
                BlockResult(
                    id="block-outside",
                    block_type=BlockType.PRINTED_TEXT,
                    bbox=BoundingBox(x0=0, y0=0, x1=101, y1=20),
                    reading_order=1,
                    source=Provenance(
                        document_id="doc-1",
                        page_number=1,
                        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
                    ),
                )
            ],
        )


def test_candidates_verification_records_and_manifest_are_typed() -> None:
    candidate = OCRCandidate(
        id="candidate-1",
        raw_text=SOURCE_TEXT,
        normalized_text=NORMALIZED_TEXT,
        confidence=0.91,
        extraction=_extraction(),
        source=Provenance(
            document_id="doc-1",
            page_number=1,
            coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        ),
    )
    record = VerificationRecord(
        id="attempt-1",
        status=VerificationStatus.VERIFIED,
        raw_text=SOURCE_TEXT,
        normalized_text=NORMALIZED_TEXT,
        confidence=0.98,
        extraction=_extraction(),
        difference_from_previous=0.01,
        reason="Consensus reached.",
    )
    manifest = ProcessingManifest(
        document_id="doc-1",
        pipeline_version="0.2.0",
        schema_version="1.0.0",
        source_checksum="a" * 64,
        processing_checksum="b" * 64,
        configuration_hash="c" * 64,
        formats=["canonical_json", "plain_text"],
    )

    assert candidate.raw_text == SOURCE_TEXT
    assert record.status is VerificationStatus.VERIFIED
    assert manifest.model_dump(mode="json")["formats"] == ["canonical_json", "plain_text"]




