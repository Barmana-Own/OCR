from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ocr_platform.domain import (
    BlockResult,
    BlockType,
    BoundingBox,
    CoordinateSpace,
    DocumentResult,
    ExtractionMetadata,
    ExtractionMethod,
    LineResult,
    OCRCandidate,
    PageResult,
    PageType,
    Provenance,
    SourceMetadata,
    TableCellResult,
    TextType,
    VerificationReason,
    VerificationRecord,
    VerificationStatus,
)


def extraction() -> ExtractionMetadata:
    return ExtractionMetadata(
        method=ExtractionMethod.OCR,
        backend="test",
        model="model",
        model_version="1",
        preprocess_variant="source-render",
        confidence_scale="test-0-1",
    )


def provenance() -> Provenance:
    return Provenance(
        document_id="doc-1",
        page_number=1,
        source_uri="artifact://doc-1/page.png",
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
    )


def test_reason_codes_selected_candidate_and_review_artifact_serialize() -> None:
    candidate = OCRCandidate(
        id="candidate-1",
        raw_text="شماره ١٢٣",
        normalized_text="شماره ۱۲۳",
        confidence=0.8,
        extraction=extraction(),
        reason_codes=[VerificationReason.LOW_PRIMARY_CONFIDENCE],
    )
    record = VerificationRecord(
        id="attempt-1",
        candidate_id=candidate.id,
        status=VerificationStatus.UNCERTAIN,
        raw_text=candidate.raw_text,
        normalized_text=candidate.normalized_text,
        confidence=candidate.confidence,
        extraction=extraction(),
        reason="low primary confidence",
        reason_codes=[VerificationReason.LOW_PRIMARY_CONFIDENCE],
    )
    line = LineResult(
        id="line-1",
        raw_text=candidate.raw_text,
        normalized_text=candidate.normalized_text,
        bbox=BoundingBox(x0=1, y0=2, x1=10, y1=20),
        reading_order=0,
        source=provenance(),
        extraction=extraction(),
        verification_status=VerificationStatus.UNCERTAIN,
        selected_candidate_id=candidate.id,
        reason_codes=[VerificationReason.LOW_PRIMARY_CONFIDENCE],
        review_artifact_uri="artifact://doc-1/reviews/line-1.json",
        verification_history=[record],
        candidates=[candidate],
    )

    payload = line.model_dump(mode="json")

    assert payload["raw_text"] == "شماره ١٢٣"
    assert payload["normalized_text"] == "شماره ۱۲۳"
    assert payload["selected_candidate_id"] == "candidate-1"
    assert payload["reason_codes"] == ["low_primary_confidence"]
    assert payload["verification_history"][0]["candidate_id"] == "candidate-1"
    assert line.needs_review is True


def test_confidence_fields_reject_values_outside_backend_normalized_range() -> None:
    with pytest.raises(ValidationError):
        OCRCandidate(
            id="candidate-1",
            raw_text="text",
            normalized_text="text",
            confidence=1.01,
            extraction=extraction(),
        )


def test_tiny_text_promotes_review_flag_before_state_synchronization() -> None:
    line = LineResult(
        id="line-1",
        raw_text="12",
        normalized_text="۱۲",
        bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10),
        reading_order=0,
        tiny_text=True,
        source=provenance(),
        extraction=extraction(),
    )

    assert line.needs_review is True
    assert line.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED


def test_review_required_cannot_remain_verified_for_line_or_table_cell() -> None:
    line = LineResult(
        id="line-verified-review",
        raw_text="ABC",
        normalized_text="ABC",
        bbox=BoundingBox(x0=0, y0=0, x1=20, y1=10),
        reading_order=0,
        needs_review=True,
        verification_status=VerificationStatus.VERIFIED,
        source=provenance(),
        extraction=extraction(),
    )
    cell = TableCellResult(
        id="cell-verified-review",
        row=0,
        column=0,
        raw_text="ABC",
        normalized_text="ABC",
        bbox=BoundingBox(x0=0, y0=0, x1=20, y1=10),
        reading_order=0,
        needs_review=True,
        verification_status=VerificationStatus.VERIFIED,
        text_type=TextType.PRINTED,
        source=provenance(),
        extraction=extraction(),
    )

    assert line.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert cell.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert line.needs_review is True
    assert cell.needs_review is True


def test_parent_block_and_document_status_cannot_hide_review_child() -> None:
    line = LineResult(
        id="line-review-child",
        raw_text="ABC",
        normalized_text="ABC",
        bbox=BoundingBox(x0=0, y0=0, x1=20, y1=10),
        reading_order=0,
        needs_review=True,
        source=provenance(),
        extraction=extraction(),
    )
    block = BlockResult(
        id="block-review-child",
        block_type=BlockType.PRINTED_TEXT,
        bbox=BoundingBox(x0=0, y0=0, x1=20, y1=10),
        reading_order=0,
        verification_status=VerificationStatus.VERIFIED,
        source=provenance(),
        lines=[line],
    )
    page = PageResult(
        page_number=1,
        width=20,
        height=10,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        page_type=PageType.IMAGE,
        source_uri="artifact://doc-1/page.png",
        rendered_width=20,
        rendered_height=10,
        verification_status=VerificationStatus.VERIFIED,
        blocks=[block],
    )
    document = DocumentResult(
        id="doc-1",
        pipeline_version="0.1.0",
        source=SourceMetadata(
            filename="source.png",
            content_type="image/png",
            byte_size=1,
            checksum_sha256="a" * 64,
            source_uri="artifact://doc-1/source.png",
        ),
        configuration_hash="b" * 64,
        processing_checksum="c" * 64,
        processing_started_at=datetime.now(UTC),
        pages=[page],
        status=VerificationStatus.VERIFIED,
    )

    assert block.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert page.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert document.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert document.needs_review is True
