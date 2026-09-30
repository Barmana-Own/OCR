from ocr_platform.domain import (
    CoordinateSpace,
    ExtractionMetadata,
    ExtractionMethod,
    ReviewFlag,
    TextType,
    VerificationStatus,
)
from ocr_platform.ingestion.models import NativeTextLine, PageInput
from ocr_platform.ocr.models import BackendTextLine
from ocr_platform.ocr.routing import PageRouter, sort_reading_order
from ocr_platform.ocr.verification import VerificationEngine, VerificationPolicy, make_candidate


def extraction(backend: str, scale: str = "backend-specific") -> ExtractionMetadata:
    return ExtractionMetadata(
        method=ExtractionMethod.OCR,
        backend=backend,
        model="test",
        model_version="1",
        dpi=300,
        preprocess_variant="test",
        confidence_scale=scale,
    )


def test_router_preserves_native_first_decision() -> None:
    page = PageInput(
        page_number=1,
        width=600,
        height=800,
        coordinate_space=CoordinateSpace.PDF_POINT,
        page_type="native_text",
        source_uri="artifact://doc/page-1",
        native_text_reliable=True,
        native_text_reason="embedded_text_reliable",
        native_lines=(NativeTextLine("text", (1, 1, 50, 10), 0, 0),),
    )
    decision = PageRouter().route(page)
    assert decision.requires_ocr is False
    assert decision.reason == "reliable_native_text"


def test_reading_order_is_spatial_and_rtl_aware_without_reversing_text() -> None:
    lines = [
        BackendTextLine("B", (100, 0, 120, 10), 0.9, "fa", "Arabic", TextType.PRINTED),
        BackendTextLine("A", (10, 0, 30, 10), 0.9, "fa", "Arabic", TextType.PRINTED),
    ]
    ordered = sort_reading_order(lines, direction="rtl")
    assert [line.raw_text for line in ordered] == ["B", "A"]


def test_confidence_scales_are_not_compared_across_backends() -> None:
    engine = VerificationEngine(VerificationPolicy(confidence_threshold=0.8))
    outcome = engine.evaluate(
        [
            make_candidate(
                "same",
                confidence=0.2,
                extraction=extraction("a", "scale-a"),
                reason="first",
            ),
            make_candidate(
                "same",
                confidence=0.99,
                extraction=extraction("b", "scale-b"),
                reason="alternate",
            ),
        ]
    )
    assert outcome.selected is not None
    assert outcome.selected.extraction.backend == "a"
    assert ReviewFlag.CONFIDENCE_SCALE_MISMATCH in outcome.flags
    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED


def test_disagreement_requires_human_review() -> None:
    engine = VerificationEngine(
        VerificationPolicy(confidence_threshold=0.8, verified_threshold=0.9)
    )
    outcome = engine.evaluate(
        [
            make_candidate("شماره ۱۲", confidence=0.95, extraction=extraction("a"), reason="first"),
            make_candidate(
                "شماره ۱۳", confidence=0.94, extraction=extraction("b"), reason="alternate"
            ),
        ]
    )
    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert outcome.flags
