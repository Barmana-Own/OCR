"""Backend-aware quality signals for OCR candidates.

The scorer evaluates one candidate at a time. It intentionally does not rank
confidence values from incompatible providers; consensus and selection policy
belong to the verification engine.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ocr_platform.domain import VerificationReason

if TYPE_CHECKING:
    from .engine import AttemptCandidate

_RTL_RE = re.compile(r"[\u0590-\u08ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_REPLACEMENT_CHAR = "\ufffd"


@dataclass(frozen=True, slots=True)
class CandidateScoringPolicy:
    """Configurable per-candidate quality thresholds.

    ``backend_confidence_thresholds`` is keyed by the adapter name. Values are
    meaningful only within the backend's declared confidence scale.
    """

    default_confidence_threshold: float = 0.85
    backend_confidence_thresholds: Mapping[str, float] = field(default_factory=dict)
    min_text_length: int = 1
    max_suspicious_char_rate: float = 0.10
    min_image_quality: float | None = 0.20
    expected_pattern: str | None = None

    def __post_init__(self) -> None:
        _validate_probability(
            self.default_confidence_threshold, "default_confidence_threshold"
        )
        for backend, threshold in self.backend_confidence_thresholds.items():
            if not backend.strip():
                raise ValueError("backend confidence threshold keys must not be empty")
            _validate_probability(threshold, f"confidence threshold for {backend}")
        if self.min_text_length < 1:
            raise ValueError("min_text_length must be positive")
        _validate_probability(self.max_suspicious_char_rate, "max_suspicious_char_rate")
        if self.min_image_quality is not None:
            _validate_probability(self.min_image_quality, "min_image_quality")
        if self.expected_pattern is not None:
            try:
                re.compile(self.expected_pattern)
            except re.error as exc:
                raise ValueError("expected_pattern must be a valid regular expression") from exc

    def confidence_threshold_for(self, backend: str) -> float:
        return self.backend_confidence_thresholds.get(backend, self.default_confidence_threshold)


@dataclass(frozen=True, slots=True)
class CandidateScore:
    candidate_id: str | None
    confidence_scale: str
    confidence_threshold: float
    suspicious_char_rate: float
    quality_score: float
    reason_codes: tuple[VerificationReason, ...]
    usable: bool


def are_confidence_scales_compatible(
    left: AttemptCandidate, right: AttemptCandidate
) -> bool:
    """Return whether numeric confidence values may be compared directly."""

    left_scale = left.extraction.confidence_scale
    right_scale = right.extraction.confidence_scale
    if left_scale != right_scale:
        return False
    return left.extraction.backend == right.extraction.backend


def score_candidate(
    candidate: AttemptCandidate, policy: CandidateScoringPolicy
) -> CandidateScore:
    text = candidate.raw_text
    non_whitespace = [char for char in text if not char.isspace()]
    suspicious_count = sum(_is_suspicious(char) for char in non_whitespace)
    suspicious_rate = suspicious_count / max(len(non_whitespace), 1)
    reasons: list[VerificationReason] = []

    if candidate.confidence is None or candidate.confidence < policy.confidence_threshold_for(
        candidate.extraction.backend
    ):
        reasons.append(VerificationReason.LOW_PRIMARY_CONFIDENCE)
    if not non_whitespace:
        reasons.append(VerificationReason.EMPTY_TEXT)
    elif len(non_whitespace) < policy.min_text_length:
        reasons.append(VerificationReason.SHORT_TEXT)
    if suspicious_rate > policy.max_suspicious_char_rate:
        reasons.append(VerificationReason.SUSPICIOUS_CHARACTERS)
    if not _language_script_is_consistent(candidate):
        reasons.append(VerificationReason.LANGUAGE_SCRIPT_MISMATCH)
    expected_pattern = candidate.expected_format or policy.expected_pattern
    if expected_pattern is not None and re.fullmatch(expected_pattern, text) is None:
        reasons.append(VerificationReason.EXPECTED_FORMAT_MISMATCH)
    if (
        policy.min_image_quality is not None
        and candidate.image_quality is not None
        and candidate.image_quality < policy.min_image_quality
    ):
        reasons.append(VerificationReason.LOW_IMAGE_QUALITY)
    if candidate.tiny_text:
        reasons.append(VerificationReason.TINY_TEXT)

    fatal_reasons = {
        VerificationReason.EMPTY_TEXT,
        VerificationReason.SHORT_TEXT,
        VerificationReason.SUSPICIOUS_CHARACTERS,
        VerificationReason.LANGUAGE_SCRIPT_MISMATCH,
        VerificationReason.EXPECTED_FORMAT_MISMATCH,
    }
    confidence_value = candidate.confidence or 0.0
    quality_score = max(0.0, min(1.0, confidence_value))
    if suspicious_rate > 0:
        quality_score *= max(0.0, 1.0 - suspicious_rate)
    if candidate.image_quality is not None:
        quality_score = (quality_score + max(0.0, min(1.0, candidate.image_quality))) / 2
    return CandidateScore(
        candidate_id=candidate.candidate_id,
        confidence_scale=candidate.extraction.confidence_scale,
        confidence_threshold=policy.confidence_threshold_for(candidate.extraction.backend),
        suspicious_char_rate=suspicious_rate,
        quality_score=quality_score,
        reason_codes=tuple(dict.fromkeys(reasons)),
        usable=not bool(fatal_reasons.intersection(reasons)),
    )


def _is_suspicious(char: str) -> bool:
    if char == _REPLACEMENT_CHAR or unicodedata.category(char) in {"Co", "Cn"}:
        return True
    return unicodedata.category(char).startswith("C") and char not in {"\t", "\n", "\r"}


def _language_script_is_consistent(candidate: AttemptCandidate) -> bool:
    text = candidate.raw_text
    has_rtl = bool(_RTL_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    language = candidate.language.lower()
    script = candidate.script.lower()
    if language in {"fa", "fas", "ar", "ara", "ur", "he"} and not has_rtl:
        return False
    if language in {"en", "eng", "fr", "de", "es", "latin"} and not has_latin:
        return False
    if script in {"arabic", "hebrew"} and not has_rtl:
        return False
    return script not in {"latin", "latn"} or has_latin


__all__ = [
    "CandidateScore",
    "CandidateScoringPolicy",
    "are_confidence_scales_compatible",
    "score_candidate",
]


def _validate_probability(value: float, name: str) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
