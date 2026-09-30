from .comparison import (
    TextComparison,
    cer_like_distance,
    compare_text,
    edit_distance,
    exact_agreement,
    normalized_agreement,
    unicode_normalize,
)
from .engine import (
    AttemptCandidate,
    VerificationEngine,
    VerificationOutcome,
    VerificationPolicy,
    make_candidate,
)
from .evidence import (
    EvidenceKey,
    candidate_evidence_key,
    evidence_keys,
    independent_consensus_count,
    same_backend_stability_count,
    text_stability_count,
)
from .retry import RetryAttempt, RetryPlan, RetryStage
from .scoring import (
    CandidateScore,
    CandidateScoringPolicy,
    are_confidence_scales_compatible,
    score_candidate,
)

__all__ = [
    "AttemptCandidate",
    "CandidateScore",
    "CandidateScoringPolicy",
    "RetryAttempt",
    "RetryPlan",
    "RetryStage",
    "TextComparison",
    "VerificationEngine",
    "VerificationOutcome",
    "VerificationPolicy",
    "EvidenceKey",
    "candidate_evidence_key",
    "evidence_keys",
    "independent_consensus_count",
    "same_backend_stability_count",
    "text_stability_count",
    "cer_like_distance",
    "compare_text",
    "edit_distance",
    "exact_agreement",
    "make_candidate",
    "are_confidence_scales_compatible",
    "score_candidate",
    "normalized_agreement",
    "unicode_normalize",
]
