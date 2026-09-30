"""Backend-aware OCR candidate verification and bounded consensus policy."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from ocr_platform.domain import (
    ExtractionMetadata,
    ReviewFlag,
    VerificationAttempt,
    VerificationReason,
    VerificationStatus,
)
from ocr_platform.normalization import NormalizationConfig, normalize_text

from .comparison import TextComparison, compare_text
from .scoring import (
    CandidateScore,
    CandidateScoringPolicy,
    are_confidence_scales_compatible,
    score_candidate,
)


@dataclass(frozen=True)
class VerificationPolicy:
    confidence_threshold: float = 0.85
    verified_threshold: float = 0.92
    require_consensus_for_tiny_text: bool = True
    max_attempts: int = 3
    min_consensus_candidates: int = 2
    require_consensus_for_verified: bool = True
    allow_consensus_override_low_confidence: bool = True
    min_text_length: int = 1
    max_suspicious_char_rate: float = 0.10
    min_image_quality: float = 0.20
    backend_confidence_thresholds: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        _validate_probability(self.confidence_threshold, "confidence_threshold", strict=True)
        _validate_probability(self.verified_threshold, "verified_threshold", strict=True)
        if self.verified_threshold < self.confidence_threshold:
            raise ValueError("verified_threshold cannot be below confidence threshold")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.min_consensus_candidates < 1:
            raise ValueError("min_consensus_candidates must be positive")
        if self.min_consensus_candidates > self.max_attempts:
            raise ValueError("min_consensus_candidates cannot exceed max_attempts")
        if self.min_text_length < 1:
            raise ValueError("min_text_length must be positive")
        _validate_probability(
            self.max_suspicious_char_rate, "max_suspicious_char_rate", strict=False
        )
        _validate_probability(self.min_image_quality, "min_image_quality", strict=False)

    def scoring_policy(self) -> CandidateScoringPolicy:
        return CandidateScoringPolicy(
            default_confidence_threshold=self.confidence_threshold,
            backend_confidence_thresholds=dict(self.backend_confidence_thresholds),
            min_text_length=self.min_text_length,
            max_suspicious_char_rate=self.max_suspicious_char_rate,
            min_image_quality=self.min_image_quality,
        )


@dataclass(frozen=True)
class AttemptCandidate:
    raw_text: str
    normalized_text: str
    confidence: float | None
    extraction: ExtractionMetadata
    reason: str
    tiny_text: bool = False
    candidate_id: str | None = None
    language: str = "und"
    script: str = "Unknown"
    image_quality: float | None = None
    expected_format: str | None = None


@dataclass(frozen=True)
class VerificationOutcome:
    selected: AttemptCandidate | None
    status: VerificationStatus
    flags: tuple[ReviewFlag, ...]
    attempts: tuple[VerificationAttempt, ...]
    reason: str
    reason_codes: tuple[VerificationReason, ...] = ()
    selected_candidate_id: str | None = None
    comparisons: tuple[TextComparison, ...] = ()


class VerificationEngine:
    def __init__(self, policy: VerificationPolicy) -> None:
        self.policy = policy

    def evaluate(self, candidates: Sequence[AttemptCandidate]) -> VerificationOutcome:
        if not candidates:
            return VerificationOutcome(
                selected=None,
                status=VerificationStatus.FAILED,
                flags=(ReviewFlag.MISSING_BACKEND,),
                attempts=(),
                reason="no OCR candidates were produced",
                reason_codes=(VerificationReason.BACKEND_FAILURE,),
            )

        limited = tuple(
            replace(candidate, candidate_id=candidate.candidate_id or f"candidate-{index + 1}")
            for index, candidate in enumerate(candidates[: self.policy.max_attempts])
        )
        scoring = self.policy.scoring_policy()
        scores = tuple(score_candidate(candidate, scoring) for candidate in limited)
        scales_compatible = all(
            are_confidence_scales_compatible(limited[0], candidate)
            for candidate in limited[1:]
        )
        comparisons = tuple(
            compare_text(limited[0].raw_text, candidate.raw_text) for candidate in limited[1:]
        )
        normalized_groups = _group_by_normalized_text(limited)
        winning_text, winning_indexes = _winning_group(normalized_groups)
        consensus = len(winning_indexes) >= self.policy.min_consensus_candidates
        pool_indexes = winning_indexes if consensus else tuple(range(len(limited)))
        selected_index = self._select_index(limited, scores, pool_indexes, scales_compatible)
        selected = limited[selected_index]
        selected_score = scores[selected_index]

        reason_codes: list[VerificationReason] = list(selected_score.reason_codes)
        flags: list[ReviewFlag] = []
        all_candidates_individually_usable = all(
            score.usable
            and VerificationReason.LOW_PRIMARY_CONFIDENCE not in score.reason_codes
            for score in scores
        )
        scale_mismatch_requires_review = not scales_compatible and not (
            consensus and all_candidates_individually_usable
        )
        if scale_mismatch_requires_review:
            reason_codes.append(VerificationReason.CONFIDENCE_SCALE_MISMATCH)
            flags.append(ReviewFlag.CONFIDENCE_SCALE_MISMATCH)
        if len(normalized_groups) > 1:
            reason_codes.extend(
                (
                    VerificationReason.BACKEND_DISAGREEMENT,
                    VerificationReason.NORMALIZED_DISAGREEMENT,
                )
            )
            flags.append(ReviewFlag.DISAGREEMENT)
            reason_codes.extend(_difference_reason_codes(comparisons))
        if selected.tiny_text:
            flags.append(ReviewFlag.TINY_TEXT)
        _append_score_flags(flags, selected_score.reason_codes)

        if consensus:
            consensus_candidates = [limited[index] for index in winning_indexes]
            backends = {candidate.extraction.backend for candidate in consensus_candidates}
            variants = {
                candidate.extraction.preprocess_variant for candidate in consensus_candidates
            }
            if len(backends) > 1:
                reason_codes.append(VerificationReason.CONSENSUS_ACROSS_BACKENDS)
            if len(variants) > 1:
                reason_codes.append(VerificationReason.CONSENSUS_ACROSS_VARIANTS)
        elif self.policy.require_consensus_for_verified:
            reason_codes.append(VerificationReason.INSUFFICIENT_EVIDENCE)

        reason_codes = list(dict.fromkeys(reason_codes))
        blocking_reasons = {
            VerificationReason.EMPTY_TEXT,
            VerificationReason.SHORT_TEXT,
            VerificationReason.SUSPICIOUS_CHARACTERS,
            VerificationReason.LANGUAGE_SCRIPT_MISMATCH,
            VerificationReason.EXPECTED_FORMAT_MISMATCH,
        }
        selected_is_malformed = bool(blocking_reasons.intersection(selected_score.reason_codes))
        low_confidence = VerificationReason.LOW_PRIMARY_CONFIDENCE in reason_codes
        low_confidence_overridden = (
            low_confidence
            and consensus
            and self.policy.allow_consensus_override_low_confidence
            and not selected_is_malformed
        )
        tiny_consensus_required = selected.tiny_text and self.policy.require_consensus_for_tiny_text
        unresolved = (
            scale_mismatch_requires_review
            or len(normalized_groups) > 1
            or selected_is_malformed
            or (low_confidence and not low_confidence_overridden)
            or (tiny_consensus_required and not consensus)
        )
        if unresolved:
            status = VerificationStatus.HUMAN_REVIEW_REQUIRED
            if len(limited) >= self.policy.max_attempts and len(normalized_groups) > 1:
                reason_codes.append(VerificationReason.RETRY_EXHAUSTED)
        elif (
            selected_score.usable
            and (consensus or not self.policy.require_consensus_for_verified)
            and (
                selected.confidence is not None
                and selected.confidence >= self.policy.verified_threshold
                or low_confidence_overridden
            )
            and (not self.policy.require_consensus_for_verified or consensus)
        ):
            status = VerificationStatus.VERIFIED
        elif selected_score.usable:
            status = VerificationStatus.ACCEPTED
        else:
            status = VerificationStatus.HUMAN_REVIEW_REQUIRED

        reason_codes = list(dict.fromkeys(reason_codes))
        attempts = self._attempts(limited, scores, status, tuple(reason_codes), selected_index)
        reason = ";".join(code.value for code in reason_codes) or status.value
        return VerificationOutcome(
            selected=selected,
            status=status,
            flags=tuple(dict.fromkeys(flags)),
            attempts=attempts,
            reason=reason,
            reason_codes=tuple(reason_codes),
            selected_candidate_id=selected.candidate_id,
            comparisons=comparisons,
        )

    def _select_index(
        self,
        candidates: tuple[AttemptCandidate, ...],
        scores: tuple[CandidateScore, ...],
        pool_indexes: tuple[int, ...],
        scales_compatible: bool,
    ) -> int:
        usable_indexes = tuple(index for index in pool_indexes if scores[index].usable)
        selection_pool = usable_indexes or pool_indexes
        if not scales_compatible:
            return selection_pool[0]
        return max(
            selection_pool,
            key=lambda index: (
                candidates[index].confidence is not None,
                candidates[index].confidence or 0.0,
                scores[index].quality_score,
                -index,
            ),
        )

    @staticmethod
    def _attempts(
        candidates: tuple[AttemptCandidate, ...],
        scores: tuple[CandidateScore, ...],
        final_status: VerificationStatus,
        reason_codes: tuple[VerificationReason, ...],
        selected_index: int,
    ) -> tuple[VerificationAttempt, ...]:
        attempts: list[VerificationAttempt] = []
        previous: AttemptCandidate | None = None
        for index, candidate in enumerate(candidates):
            difference = None
            if previous is not None:
                from .comparison import cer_like_distance

                difference = cer_like_distance(previous.normalized_text, candidate.normalized_text)
            candidate_reasons = tuple(dict.fromkeys((*scores[index].reason_codes, *reason_codes)))
            attempt_status = (
                final_status
                if index == selected_index
                else VerificationStatus.UNCERTAIN
                if candidate.normalized_text != candidates[selected_index].normalized_text
                else VerificationStatus.ACCEPTED
            )
            attempts.append(
                VerificationAttempt(
                    id=f"attempt-{index + 1}",
                    candidate_id=candidate.candidate_id,
                    status=attempt_status,
                    raw_text=candidate.raw_text,
                    normalized_text=candidate.normalized_text,
                    confidence=candidate.confidence,
                    extraction=candidate.extraction,
                    difference_from_previous=difference,
                    reason=candidate.reason,
                    reason_codes=list(candidate_reasons),
                )
            )
            previous = candidate
        return tuple(attempts)


def make_candidate(
    raw_text: str,
    *,
    confidence: float | None,
    extraction: ExtractionMetadata,
    reason: str,
    tiny_text: bool = False,
    candidate_id: str | None = None,
    language: str = "und",
    script: str = "Unknown",
    image_quality: float | None = None,
    expected_format: str | None = None,
    normalization_config: NormalizationConfig | None = None,
) -> AttemptCandidate:
    return AttemptCandidate(
        raw_text=raw_text,
        normalized_text=normalize_text(raw_text, normalization_config),
        confidence=confidence,
        extraction=extraction,
        reason=reason,
        tiny_text=tiny_text,
        candidate_id=candidate_id,
        language=language,
        script=script,
        image_quality=image_quality,
        expected_format=expected_format,
    )


def _group_by_normalized_text(
    candidates: tuple[AttemptCandidate, ...],
) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        grouped.setdefault(candidate.normalized_text, []).append(index)
    return {text: tuple(indexes) for text, indexes in grouped.items()}


def _winning_group(groups: dict[str, tuple[int, ...]]) -> tuple[str, tuple[int, ...]]:
    return max(groups.items(), key=lambda item: (len(item[1]), -item[1][0]))


def _difference_reason_codes(
    comparisons: tuple[TextComparison, ...],
) -> tuple[VerificationReason, ...]:
    reasons: list[VerificationReason] = []
    for comparison in comparisons:
        if comparison.digit_only_disagreement:
            reasons.append(VerificationReason.DIGIT_DISAGREEMENT)
        if comparison.punctuation_only_disagreement:
            reasons.append(VerificationReason.PUNCTUATION_DIFFERENCE)
        if comparison.whitespace_only_disagreement:
            reasons.append(VerificationReason.WHITESPACE_DIFFERENCE)
    return tuple(dict.fromkeys(reasons))


def _append_score_flags(
    flags: list[ReviewFlag], reasons: Sequence[VerificationReason]
) -> None:
    if VerificationReason.LOW_PRIMARY_CONFIDENCE in reasons:
        flags.append(ReviewFlag.LOW_CONFIDENCE)
    if VerificationReason.LANGUAGE_SCRIPT_MISMATCH in reasons:
        flags.append(ReviewFlag.LANGUAGE_UNCERTAIN)
    if any(
        reason
        in {
            VerificationReason.EMPTY_TEXT,
            VerificationReason.SHORT_TEXT,
            VerificationReason.SUSPICIOUS_CHARACTERS,
            VerificationReason.EXPECTED_FORMAT_MISMATCH,
            VerificationReason.LOW_IMAGE_QUALITY,
        }
        for reason in reasons
    ):
        flags.append(ReviewFlag.MANUAL_REVIEW)


def _validate_probability(value: float, name: str, *, strict: bool) -> None:
    lower_valid = value > 0 if strict else value >= 0
    if not lower_valid or value > 1:
        raise ValueError(f"{name} must be between 0 and 1")
