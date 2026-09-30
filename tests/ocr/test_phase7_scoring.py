from ocr_platform.domain import ExtractionMetadata, ExtractionMethod, VerificationReason
from ocr_platform.ocr.verification import make_candidate
from ocr_platform.ocr.verification.scoring import (
    CandidateScoringPolicy,
    are_confidence_scales_compatible,
    score_candidate,
)


def extraction(backend: str, scale: str = "score-0-1") -> ExtractionMetadata:
    return ExtractionMetadata(
        method=ExtractionMethod.OCR,
        backend=backend,
        model="test",
        model_version="1",
        dpi=300,
        preprocess_variant="source-render",
        confidence_scale=scale,
    )


def test_scoring_uses_backend_specific_thresholds_without_comparing_engines() -> None:
    policy = CandidateScoringPolicy(
        default_confidence_threshold=0.80,
        backend_confidence_thresholds={"engine-a": 0.60, "engine-b": 0.95},
    )
    a = make_candidate(
        "valid text",
        confidence=0.70,
        extraction=extraction("engine-a"),
        reason="first",
    )
    b = make_candidate(
        "valid text",
        confidence=0.70,
        extraction=extraction("engine-b"),
        reason="alternate",
    )

    assert VerificationReason.LOW_PRIMARY_CONFIDENCE not in score_candidate(a, policy).reason_codes
    assert VerificationReason.LOW_PRIMARY_CONFIDENCE in score_candidate(b, policy).reason_codes
    assert are_confidence_scales_compatible(a, b) is False
    assert are_confidence_scales_compatible(
        a,
        make_candidate(
            "valid text",
            confidence=0.99,
            extraction=extraction("engine-c", "opaque-score"),
            reason="alternate",
        ),
    ) is False


def test_scoring_flags_malformed_text_even_when_provider_confidence_is_high() -> None:
    candidate = make_candidate(
        "OK\x00\ufffd\ufffd",
        confidence=0.99,
        extraction=extraction("engine-a"),
        reason="first",
    )

    score = score_candidate(candidate, CandidateScoringPolicy(max_suspicious_char_rate=0.1))

    assert VerificationReason.SUSPICIOUS_CHARACTERS in score.reason_codes
    assert score.usable is False


def test_scoring_flags_language_script_and_explicit_format_mismatches() -> None:
    candidate = make_candidate(
        "contract value",
        confidence=0.95,
        extraction=extraction("engine-a"),
        reason="first",
        language="fa",
        script="Arabic",
    )

    score = score_candidate(
        candidate,
        CandidateScoringPolicy(expected_pattern=r"^\d{4}$"),
    )

    assert VerificationReason.LANGUAGE_SCRIPT_MISMATCH in score.reason_codes
    assert VerificationReason.EXPECTED_FORMAT_MISMATCH in score.reason_codes


def test_scoring_retains_tiny_text_and_missing_confidence_as_explicit_signals() -> None:
    candidate = make_candidate(
        "12",
        confidence=None,
        extraction=extraction("engine-a"),
        reason="tiny-pass",
        tiny_text=True,
        image_quality=0.1,
    )

    score = score_candidate(candidate, CandidateScoringPolicy(min_text_length=3))

    assert VerificationReason.TINY_TEXT in score.reason_codes
    assert VerificationReason.LOW_PRIMARY_CONFIDENCE in score.reason_codes
    assert VerificationReason.SHORT_TEXT in score.reason_codes
    assert VerificationReason.LOW_IMAGE_QUALITY in score.reason_codes
