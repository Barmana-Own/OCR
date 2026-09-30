# QA Report

## Release scope

QA covered the implemented API-first 0.1.0 pipeline: source validation, native-first PDF handling, image processing, OCR verification, provenance, export, authentication, error envelopes, and bounded resource behavior. No browser operator UI is in scope for this release.

## QA checklist and evidence

| Area | Result | Evidence |
|---|---|---|
| Clean Python import and compile | PASS | `python -m compileall -q src tests scripts` |
| Native PDF path | PASS | reliable embedded text bypasses OCR; image-only PDF requires backend; mixed PDFs preserve native blocks and OCR image regions |
| Raster image path | PASS | deterministic image fixture pipeline tests |
| Low-confidence retry | PASS | alternate preprocessing and exact-attempt geometry regression test |
| Missing backend behavior | PASS | no fabricated text; review flag and warning are emitted |
| Upload/auth boundary | PASS | TestClient API and security suites |
| Source/artifact integrity | PASS | checksum, traversal, size, and immutable-source tests |
| Page failure recovery/checkpoints | PASS | failed pages are preserved with review flags and completed page progress is persisted |
| Metrics/readiness/tracing | PASS | bounded content-free metrics, authenticated retrieval, capability readiness, and stage spans |
| Container configuration | PASS | non-root Docker defaults and `docker compose config` validation |
| Dataset export | PASS | deterministic manifest and line-crop/label tests |
| Responsive/browser UI | NOT_APPLICABLE | no browser frontend in 0.1.0 |
| Real OCR model quality | NOT_RUN | no external OCR executable/model weights installed |
| Container runtime smoke | NOT_RUN | Docker availability was not required for local validation |

## Defect log

No P0 or P1 defects remain. The following implementation defects were discovered and fixed during QA:

| ID | Severity | Root cause | Fix and regression coverage |
|---|---|---|---|
| QA-001 | P1 | rendered OCR regions retained source coordinate metadata after rendering | map region geometry into rendered pixels and map selected backend geometry back to page space; preprocessing and retry tests cover it |
| QA-002 | P1 | selected line geometry was taken from the first backend attempt even when a later retry won verification | select the exact backend/model/preprocess/scale attempt; retry regression test covers it |
| QA-003 | P2 | missing OCR adapter could be mistaken for an empty successful result | typed unavailable error, warning, and review-required canonical state; integration test covers it |

## Accessibility and operator UX

The release is API-first, so browser interaction, visual focus, touch targets, and responsive layout are not executable release checks. The future operator UI contract is documented in `docs/02-design-system.md` and `docs/02-ui-architecture.md`; it requires explicit loading, empty, error, review, keyboard, and RTL states.

## Release blockers

No open P0/P1 blocker is known for the implemented 0.1.0 scope. Real OCR/model evaluation, production object storage/database adapters, distributed queue restart recovery, gateway rate limiting, secret-manager integration, and container execution smoke tests remain deployment prerequisites rather than silently claimed deliverables.

