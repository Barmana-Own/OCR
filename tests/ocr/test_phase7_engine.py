from ocr_platform.domain import (
    ExtractionMetadata,
    ExtractionMethod,
    ReviewFlag,
    VerificationReason,
    VerificationStatus,
)
from ocr_platform.ocr.verification import (
    VerificationEngine,
    VerificationPolicy,
    candidate_evidence_key,
    independent_consensus_count,
    make_candidate,
    same_backend_stability_count,
)


def extraction(
    backend: str,
    *,
    scale: str = "test-0-1",
    variant: str = "source-render",
    dpi: int = 300,
    model: str = "test",
    model_version: str = "1",
    backend_family: str = "unknown",
) -> ExtractionMetadata:
    return ExtractionMetadata(
        method=ExtractionMethod.OCR,
        backend=backend,
        model=model,
        model_version=model_version,
        dpi=dpi,
        preprocess_variant=variant,
        confidence_scale=scale,
        backend_family=backend_family,
    )


def candidate(
    text: str,
    *,
    backend: str = "engine-a",
    confidence: float | None = 0.97,
    variant: str = "source-render",
    tiny_text: bool = False,
    scale: str = "test-0-1",
    dpi: int = 300,
    model: str = "test",
    model_version: str = "1",
    backend_family: str = "unknown",
):
    return make_candidate(
        text,
        confidence=confidence,
        extraction=extraction(
            backend,
            scale=scale,
            variant=variant,
            dpi=dpi,
            model=model,
            model_version=model_version,
            backend_family=backend_family,
        ),
        reason=f"{backend}-{variant}",
        tiny_text=tiny_text,
    )


def test_agreement_across_two_engines_verifies_without_cross_engine_ranking() -> None:
    outcome = VerificationEngine(VerificationPolicy()).evaluate(
        [
            candidate("شماره ۱۲۳", backend="engine-a", confidence=0.96),
            candidate("شماره ۱۲۳", backend="engine-b", confidence=0.99),
        ]
    )

    assert outcome.status == VerificationStatus.VERIFIED
    assert outcome.selected is not None
    assert outcome.selected.extraction.backend == "engine-a"
    assert outcome.reason_codes == (
        VerificationReason.CONSENSUS_ACROSS_BACKENDS,
    )
    assert outcome.selected_candidate_id == "candidate-1"


def test_single_digit_disagreement_requires_review_and_is_explained() -> None:
    outcome = VerificationEngine(VerificationPolicy()).evaluate(
        [candidate("شماره ۱۲۳"), candidate("شماره ۱۲۴", backend="engine-b")]
    )

    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert ReviewFlag.DISAGREEMENT in outcome.flags
    assert VerificationReason.DIGIT_DISAGREEMENT in outcome.reason_codes


def test_low_confidence_same_backend_multipass_consensus_requires_review() -> None:
    outcome = VerificationEngine(
        VerificationPolicy(
            confidence_threshold=0.85,
            verified_threshold=0.92,
            max_attempts=3,
            allow_consensus_override_low_confidence=True,
        )
    ).evaluate(
        [
            candidate("ABC-123", confidence=0.40, variant="source-render"),
            candidate("ABC-123", confidence=0.45, variant="grayscale"),
        ]
    )

    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert VerificationReason.LOW_PRIMARY_CONFIDENCE in outcome.reason_codes
    assert VerificationReason.CONSENSUS_ACROSS_VARIANTS in outcome.reason_codes
    assert VerificationReason.INSUFFICIENT_INDEPENDENT_EVIDENCE in outcome.reason_codes
    assert ReviewFlag.INDEPENDENT_EVIDENCE_INSUFFICIENT in outcome.flags


def test_three_same_tesseract_variants_are_stability_not_independent_consensus() -> None:
    candidates = [
        candidate(
            "ABC-123",
            backend="tesseract",
            backend_family="tesseract",
            confidence=0.40,
            variant=variant,
        )
        for variant in ("source-render", "grayscale", "contrast")
    ]

    outcome = VerificationEngine(
        VerificationPolicy(max_attempts=3, min_consensus_candidates=2)
    ).evaluate(candidates)

    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert outcome.stability_count == 3
    assert outcome.independent_evidence_count == 1
    assert VerificationReason.STABLE_ACROSS_VARIANTS in outcome.reason_codes
    assert VerificationReason.CORRELATED_EVIDENCE_ONLY in outcome.reason_codes
    assert VerificationReason.INDEPENDENT_BACKEND_CONSENSUS not in outcome.reason_codes
    assert candidate_evidence_key(candidates[0]) == (
        "tesseract",
        "tesseract",
        "test",
        "1",
    )
    assert independent_consensus_count(candidates) == 1
    assert same_backend_stability_count(candidates) == 3


def test_two_independent_backend_families_can_verify_agreement() -> None:
    candidates = [
        candidate("ABC-123", backend="tesseract", backend_family="tesseract", confidence=0.96),
        candidate("ABC-123", backend="paddle", backend_family="paddleocr", confidence=0.97),
    ]

    outcome = VerificationEngine(VerificationPolicy()).evaluate(candidates)

    assert outcome.status == VerificationStatus.VERIFIED
    assert outcome.independent_evidence_count == 2
    assert VerificationReason.CONSENSUS_ACROSS_BACKENDS in outcome.reason_codes
    assert VerificationReason.CORRELATED_EVIDENCE_ONLY not in outcome.reason_codes


def test_model_versions_are_distinct_evidence_identities_by_policy() -> None:
    candidates = [
        candidate(
            "ABC-123",
            backend="tesseract",
            backend_family="tesseract",
            model_version=version,
            confidence=0.40,
            variant=f"model-{version}",
        )
        for version in ("1", "2")
    ]

    outcome = VerificationEngine(VerificationPolicy()).evaluate(candidates)

    assert outcome.status == VerificationStatus.VERIFIED
    assert outcome.independent_evidence_count == 2
    assert VerificationReason.INDEPENDENT_BACKEND_CONSENSUS in outcome.reason_codes


def test_high_confidence_same_backend_retry_remains_accepted_not_verified() -> None:
    outcome = VerificationEngine(VerificationPolicy()).evaluate(
        [
            candidate("ABC-123", backend="tesseract", confidence=0.96, variant="source-render"),
            candidate("ABC-123", backend="tesseract", confidence=0.97, variant="grayscale"),
        ]
    )

    assert outcome.status == VerificationStatus.ACCEPTED
    assert outcome.independent_evidence_count == 1
    assert ReviewFlag.INDEPENDENT_EVIDENCE_INSUFFICIENT not in outcome.flags


def test_verified_threshold_can_be_used_without_consensus_when_policy_allows_it() -> None:
    outcome = VerificationEngine(
        VerificationPolicy(require_consensus_for_verified=False, max_attempts=2)
    ).evaluate([candidate("ABC-123", confidence=0.98)])

    assert outcome.status == VerificationStatus.VERIFIED
    assert VerificationReason.INSUFFICIENT_EVIDENCE not in outcome.reason_codes


def test_high_confidence_malformed_candidate_is_not_accepted() -> None:
    outcome = VerificationEngine(VerificationPolicy()).evaluate(
        [candidate("OK\x00\ufffd", confidence=0.99)]
    )

    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert VerificationReason.SUSPICIOUS_CHARACTERS in outcome.reason_codes


def test_tiny_text_high_dpi_agreement_without_independent_backend_requires_review() -> None:
    outcome = VerificationEngine(VerificationPolicy()).evaluate(
        [
            candidate("۱۲۳۴۵", confidence=0.41, tiny_text=True, variant="source-render"),
            candidate("۱۲۳۴۵", confidence=0.96, tiny_text=True, variant="high-dpi", dpi=600),
        ]
    )

    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert VerificationReason.TINY_TEXT in outcome.reason_codes
    assert VerificationReason.CONSENSUS_ACROSS_VARIANTS in outcome.reason_codes
    assert VerificationReason.INSUFFICIENT_INDEPENDENT_EVIDENCE in outcome.reason_codes


def test_unresolved_disagreement_retains_all_attempts_and_is_uncertain() -> None:
    outcome = VerificationEngine(VerificationPolicy(max_attempts=3)).evaluate(
        [
            candidate("A", confidence=0.96, variant="source-render"),
            candidate("B", confidence=0.95, variant="grayscale"),
            candidate("C", confidence=0.94, variant="contrast"),
        ]
    )

    assert outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert len(outcome.attempts) == 3
    assert all(attempt.raw_text for attempt in outcome.attempts)
    assert all(attempt.reason_codes for attempt in outcome.attempts)
