# UI/API Architecture: OCR Pipeline Operator Workflows

## Role-based navigation map

The API is the initial control plane. Future navigation is role-scoped:

| Role | Surfaces |
|---|---|
| Dataset engineer | Documents, processing profiles, retries, exports, quality metrics |
| Operator | Upload, processing queue, document inspector, export status |
| Reviewer | Assigned review queue, page/line evidence, review decisions |
| ML engineer | Versioned exports, manifests, evaluation metrics |
| Administrator | Health/readiness, configuration diagnostics, audit events |

Unauthorized surfaces must not appear as normal navigation choices and must still be protected server-side.

## Journey-to-surface map

| Journey | Required surface/state |
|---|---|
| Upload | File selection, validation, duplicate checksum notice, upload failure, accepted/processing |
| Native-first processing | Page-level method badge, native text result, OCR fallback reason, dependency-unavailable error |
| OCR retry | Attempt timeline, preprocessing/DPI/backend metadata, disagreement warning, retry limit |
| Review | Source page/crop, boxes, raw vs normalized text, confidence caveat, approve/flag action, immutable audit |
| Export | Format/version/config/source hashes, deterministic completion, partial failure, retry |
| Quality | Metric availability/NOT_RUN, backend grouping, review rate, disagreement and tiny-text paths |

## State matrix

| State | Required behavior |
|---|---|
| Loading/processing | Show current stage and correlation/job ID; prevent duplicate submit; allow safe refresh. |
| Empty | Explain no documents/exports/reviews and provide the next allowed action. |
| Validation error | Associate message with the exact file/field; do not discard the source silently. |
| Server/dependency error | Show safe error code, retryability, and preserve source/job evidence. |
| Permission denied | Explain lack of access without revealing existence of protected resources. |
| Uncertain | Show uncertainty flags, raw attempts, and review requirement; never hide the text. |
| Offline/degraded | Keep unsent input local only if explicitly designed later; current API client should surface failure. |

## Responsive behavior for future UI

- Mobile: stack upload and filters; use page image plus line detail drawer; allow deliberate horizontal scrolling for dense metadata tables.
- Tablet: two-pane document inspector where page image and line list remain usable.
- Desktop: three-pane inspector for source, structured layout, and verification history; keep raw/normalized columns readable.
- Large desktop: cap content width and preserve line/crop legibility rather than stretching boxes.

## Traceability

The future surfaces map directly to FR-001 through FR-020 and NFR-001 through NFR-015. The canonical API response is authoritative for data and status; UI state is a projection, not a source of truth.
