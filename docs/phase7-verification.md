# Phase 7 — Verification, Confidence Policy, Retry Logic, and Uncertainty

## Scope

Phase 7 adds the quality-control boundary that prevents a first OCR result
from becoming training truth without evidence. It preserves raw backend text,
keeps normalized text separate, applies provider-aware policy, retains all
bounded attempts, and creates review material for unresolved lines.

## Executable modules

| Module | Responsibility |
|---|---|
| `ocr/verification/comparison.py` | NFC-aware and configurable normalized comparison, edit/CER-like distance, and digit/punctuation/whitespace classification |
| `ocr/verification/scoring.py` | Per-candidate quality signals and backend-specific confidence thresholds |
| `ocr/verification/retry.py` | Finite ordered retry-plan records for preprocessing, DPI, scale, and alternate backends |
| `ocr/verification/engine.py` | Candidate selection, consensus, certainty status, flags, reason codes, and attempt history |
| `domain/models.py` | Canonical candidate, line, table-cell, block, and verification evidence fields |
| `pipeline.py` | Candidate-budget enforcement, PDF high-DPI escalation, geometry mapping, review evidence, and quality aggregation |
| `storage/layout.py` | Deterministic page-scoped review artifact names |
| `dataset/exporter.py` | Audit-complete line-crop labels |
| `config/settings.py` | Environment-backed thresholds and retry/resource limits |

## Decision policy

The engine evaluates candidates in a deterministic order and caps them at
`verification_max_candidates`. A candidate can receive signals for:

- backend-specific confidence below threshold;
- empty or suspicious text;
- short text;
- language/script mismatch;
- an explicitly supplied expected format mismatch;
- low available line-image quality;
- tiny-text routing;
- confidence-scale mismatch;
- disagreement with another candidate;
- digit, punctuation, or whitespace-only differences.

Confidence values are not globally calibrated. Numeric selection is only
performed for candidates from the same backend and declared scale. Different
providers can still establish consensus when their normalized text agrees;
the higher numeric score is not treated as the winner.

The final state rules are:

| Condition | State |
|---|---|
| no candidate | `failed` |
| clean candidate, no material ambiguity, below verification evidence requirement | `accepted` |
| clean high-confidence candidate with required consensus | `verified` |
| disagreement, malformed/empty text, unresolved low confidence, or incompatible weak scales | `human_review_required` |
| non-selected disagreement attempts | `uncertain` in attempt history |

Low-confidence exact consensus can be promoted to `verified` only when
`verification_allow_consensus_override_low_confidence` is enabled and all
consensus candidates remain otherwise usable. Tiny text requires the configured
consensus threshold by default. Every decision stores both a status and reason
codes; status is never inferred from a single provider confidence field.

## Retry and DPI behavior

`RetryPlan` describes this bounded order:

1. first pass;
2. alternate preprocessing;
3. higher-resolution page/crop;
4. first configured alternate region scale;
5. alternate backend;
6. additional region scales if budget remains.

The synchronous document pipeline preserves its established variant behavior
and applies the configured candidate budget. For PDF pages rendered below the
configured high-quality DPI, a weak final result may trigger one high-quality
rerender. High-resolution result geometry is mapped back to the base rendered
page before canonical assembly. Tiny pages already rendered at tiny-text DPI
are not blindly rendered again.

All source pages and original renders remain separate artifacts. Derived crops,
preprocessing variants, and review overlays are stored independently.

## Human-review evidence

For every review-needed line, the pipeline attempts to store:

- a page-scoped highlighted PNG overlay;
- a JSON package containing source page URI, rendered page URI, line crop URI,
  bbox/polygon, coordinate space and dimensions;
- selected candidate identity, all candidate raw/normalized text, confidence,
  backend/model/version, DPI, region scale, and preprocessing variant;
- verification status, flags, reason codes, and ordered history.

The store is immutable by default. Reprocessing reuses identical bytes and
reports a scoped warning for incompatible content rather than overwriting
evidence. A storage failure leaves the line in a review-required state.

## Configuration

Phase 7 settings are included in the configuration hash and can be overridden
through `.env.example` entries including:

- `OCR_VERIFICATION_MAX_CANDIDATES`;
- `OCR_VERIFICATION_MIN_CONSENSUS_CANDIDATES`;
- `OCR_VERIFICATION_REQUIRE_CONSENSUS`;
- `OCR_VERIFICATION_ALLOW_CONSENSUS_OVERRIDE`;
- `OCR_VERIFICATION_MIN_TEXT_LENGTH`;
- `OCR_VERIFICATION_MAX_SUSPICIOUS_CHAR_RATE`;
- `OCR_VERIFICATION_MIN_IMAGE_QUALITY`;
- `OCR_VERIFICATION_ENABLE_HIGH_QUALITY_RETRY`;
- `OCR_BACKEND_CONFIDENCE_THRESHOLDS` using safe `backend:threshold` pairs.

## Tests and validation evidence

Targeted Phase 7 tests cover comparison, mixed Persian/English and RTL/LTR
strings, digit variants, backend-specific thresholds, malformed high-confidence
text, explicit formats, tiny text, engine consensus, disagreement, bounded
retry ordering, model serialization, configuration bounds, pipeline retries,
and review artifacts. The final validation record is maintained in
`project-state.json` and `release-manifest.json`.

Heavy OCR/HTR/table model quality remains deployment-dependent. No test or
verification path fabricates provider output, and no LLM correction is used to
replace raw OCR.
