import pytest
from pydantic import ValidationError

from ocr_platform.domain import (
    BoundingBox,
    CoordinateSpace,
    ExtractionMetadata,
    ExtractionMethod,
    LineResult,
    OCRCandidate,
    Provenance,
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
