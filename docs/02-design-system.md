# Design System: OCR Pipeline Operator Surfaces

## Purpose

The initial product is API-first and has no browser UI in scope. This document defines semantic foundations for future operator/reviewer surfaces and for API-facing status terminology so a later UI can remain consistent with the canonical data model.

## Semantic foundations

- **Typography:** system sans for operational labels; tabular numerals for IDs, coordinates, confidence, and metrics; monospace only for checksums and backend identifiers.
- **Spacing:** 4px base rhythm with 8/12/16/24/32/48px semantic steps.
- **Radii:** small controls 6px, cards/panels 10px, modal surfaces 14px.
- **Elevation:** use borders and restrained shadows; never rely on shadow alone for state.
- **Motion:** short, interruptible transitions; honor reduced-motion preferences; no motion is required to understand review state.
- **Icons:** use meaningful labels alongside icons; directional icons must be checked for RTL behavior.

## Status semantics

Status must be communicated by text, icon/shape, and color where a future UI exists. Key states are `accepted`, `verified`, `uncertain`, `human_review_required`, `failed`, `processing`, and `unavailable`.

## Accessibility and localization

- Keyboard focus must remain visible and move into dialogs/review panels predictably.
- Every upload, retry, export, and review action needs a label, disabled/loading state, and safe error association.
- Persian/Arabic text must be rendered in true RTL containers without reversing stored strings. Mixed LTR values such as URLs, emails, IDs, checksums, and coordinates need explicit direction isolation.
- Confidence and review status must not be communicated by color alone.

## Future operator surface families

1. Upload/process form with file constraints and progress/error states.
2. Document queue with processing status, backend/model, retries, review count, and filtering.
3. Document inspector with page image, line/block boxes, raw/normalized toggle, verification history, and reviewer action log.
4. Export job screen with deterministic manifest, version/config hashes, output formats, and failure/retry state.
5. Quality dashboard with backend-specific confidence caveat, CER/WER, review rate, disagreement, and tiny-text recovery.

## Handoff to Stage 03

No frontend source is created in this release because the requested product is an API/data pipeline. A future client must consume the typed API contract and canonical schema rather than reconstructing status or provenance from presentation strings.
