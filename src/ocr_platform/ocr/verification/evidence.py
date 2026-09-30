"""Evidence identity helpers for backend-aware verification.

Preprocessing retries are useful attempts, but they are correlated observations
when they use the same configured backend identity.  This module keeps that
distinction explicit and deterministic for the verification engine and tests.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Protocol

from ocr_platform.domain import ExtractionMetadata

type EvidenceKey = tuple[str, str, str, str]


class CandidateEvidence(Protocol):
    """Minimum candidate shape required by the evidence helpers."""

    normalized_text: str
    extraction: ExtractionMetadata


def candidate_evidence_key(candidate: CandidateEvidence) -> EvidenceKey:
    """Return the stable identity of the model that produced a candidate.

    The key intentionally excludes preprocessing variant, DPI, region scale,
    render variant, retry number, and candidate id.  Those values describe an
    attempt and remain in the candidate's extraction metadata, but changing
    one must not create independent OCR evidence.

    The tuple contains both the declared backend family and backend name.  A
    missing/``unknown`` family falls back to the adapter name so legacy
    adapters still receive a deterministic identity.  Model and model
    version are part of the identity; configured releases are therefore
    treated as distinct evidence identities and are auditable in provenance.
    """

    extraction = candidate.extraction
    backend_family = _identity_component(extraction.backend_family, "unknown")
    backend_name = _identity_component(extraction.backend, "unknown")
    if backend_family == "unknown":
        backend_family = backend_name
    return (
        backend_family,
        backend_name,
        _identity_component(extraction.model, "unknown"),
        _identity_component(extraction.model_version, "unknown"),
    )


def text_stability_count(
    candidates: Iterable[CandidateEvidence],
    normalized_text: str | None = None,
) -> int:
    """Count attempts supporting one normalized text value.

    This is a stability measure only.  It must not be used as an independent
    backend count.
    """

    selected = _matching_candidates(candidates, normalized_text)
    return len(selected)


def independent_consensus_count(
    candidates: Iterable[CandidateEvidence],
    normalized_text: str | None = None,
) -> int:
    """Count distinct backend/model/version identities for one text value."""

    selected = _matching_candidates(candidates, normalized_text)
    return len({candidate_evidence_key(candidate) for candidate in selected})


def same_backend_stability_count(
    candidates: Iterable[CandidateEvidence],
    normalized_text: str | None = None,
) -> int:
    """Return the largest number of matching attempts from one evidence key."""

    selected = _matching_candidates(candidates, normalized_text)
    counts = Counter(candidate_evidence_key(candidate) for candidate in selected)
    return max(counts.values(), default=0)


def evidence_keys(
    candidates: Iterable[CandidateEvidence],
    normalized_text: str | None = None,
) -> tuple[EvidenceKey, ...]:
    """Return sorted, unique evidence keys for deterministic audit output."""

    selected = _matching_candidates(candidates, normalized_text)
    return tuple(sorted({candidate_evidence_key(candidate) for candidate in selected}))


def _matching_candidates(
    candidates: Iterable[CandidateEvidence], normalized_text: str | None
) -> tuple[CandidateEvidence, ...]:
    materialized = tuple(candidates)
    if normalized_text is None:
        return materialized
    return tuple(
        candidate for candidate in materialized if candidate.normalized_text == normalized_text
    )


def _identity_component(value: str, fallback: str) -> str:
    normalized = value.strip().casefold()
    return normalized or fallback


__all__ = [
    "CandidateEvidence",
    "EvidenceKey",
    "candidate_evidence_key",
    "evidence_keys",
    "independent_consensus_count",
    "same_backend_stability_count",
    "text_stability_count",
]
