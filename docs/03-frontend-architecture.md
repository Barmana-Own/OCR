# Frontend Architecture: API-First Release

## Applicability decision

**Status: PASS / NOT_APPLICABLE for browser implementation in release 0.1.0.** The requested product is a document-processing service and dataset pipeline. No browser UI was requested, and implementing a separate frontend would add a second product surface without improving the core OCR/data-integrity objective.

## Future client boundary

Future operator and reviewer clients must consume the FastAPI/OpenAPI contract and canonical `Document` response. They must not infer verification state from color, replace raw text with normalized text, or reconstruct reading order by reversing RTL strings.

## Required client behavior when added

- Typed API client with explicit loading, empty, validation, dependency-failure, forbidden, uncertain, and retry states.
- Upload limits and server-side validation mirrored for user feedback but never treated as a security boundary.
- Raw/normalized text shown as separate fields; page image/crop coordinates rendered in the declared coordinate space.
- Review actions append audit decisions and never mutate raw OCR evidence.
- Keyboard/focus semantics, accessible errors, reduced motion, and bidirectional mixed-content handling follow Stage 02.

## No hidden mocks

There is no production frontend path and no client-side fixture path. Test doubles remain confined to tests and explicit development adapters.

## Handoff to Stage 04

The backend must expose stable typed schemas and error codes so future clients can be generated or implemented without coupling to internal persistence or model adapters.
