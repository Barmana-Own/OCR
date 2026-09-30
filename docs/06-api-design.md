# API Design

> Cross-cutting canonical baseline: [architecture.md](architecture.md), [data-model.md](data-model.md), and [processing-flow.md](processing-flow.md). Phase 9 execution details are in [phase9-api-orchestration.md](phase9-api-orchestration.md).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | public | Process health |
| GET | `/readyz` | public | Artifact and metadata storage readiness |
| POST | `/v1/documents` | API key when `OCR_REQUIRE_AUTH=true` | Bounded asynchronous upload and job submission |
| GET | `/v1/jobs/{job_id}` | API key when `OCR_REQUIRE_AUTH=true` | Job status and page/stage progress |
| GET | `/v1/documents/{document_id}` | API key when `OCR_REQUIRE_AUTH=true` | Canonical document result |
| GET | `/v1/documents/{document_id}/manifest` | API key when `OCR_REQUIRE_AUTH=true` | Dataset/export manifest |
| GET | `/v1/documents/{document_id}/pages/{page}/image` | API key when `OCR_REQUIRE_AUTH=true` | Rendered page artifact |
| GET | `/v1/documents/{document_id}/exports/{format}` | API key when `OCR_REQUIRE_AUTH=true` | Policy-aware JSON/text/Markdown/page/crop export |
| POST | `/v1/documents/process` | API key when `OCR_REQUIRE_AUTH=true` | Synchronous compatibility endpoint |

## Asynchronous submission

`POST /v1/documents` accepts multipart field `file`, form field `mode` (`fast`, `balanced`, or `accurate`), and optional `Idempotency-Key`. It returns `202` with `job_id`, `document_id`, source/configuration checksums, selected mode, initial progress, and `idempotent_replay`.

Clients poll `GET /v1/jobs/{job_id}`. A terminal job does not imply that every line is correct: `completed_with_warnings` and the document's separate `VerificationStatus`/line review state remain authoritative for OCR certainty.

## Upload contract

- Accepted signatures: PDF, PNG, JPEG, TIFF, WebP.
- Actual content signatures are checked; extension and client MIME type are not authoritative.
- The client MIME type must be allowed and match the signature unless it is the generic `application/octet-stream`.
- Empty and oversized streams are rejected before enqueueing.
- Filename metadata cannot contain path separators, control characters, colon/alternate-stream separators, traversal names, or more than 255 characters.
- Source bytes are stored under a server-generated content-addressed document namespace.

## Response and retrieval contract

The canonical document preserves the complete `Document -> Page -> Block -> Line -> Word` hierarchy and all raw/normalized text, geometry, extraction provenance, verification history, and warnings. The API never filters canonical JSON for an export policy.

`GET /v1/documents/{document_id}/exports/{format}` supports `json`, `txt`, `md`, `manifest`, `pages`, and `crops`. The optional `policy` query parameter is `strict_verified_only`, `accepted_verified` (default), or `all_with_status`. Strict policy is the safe choice for training labels; uncertain and human-review-required records are not silently mixed into derived text/crop outputs.

## Errors

Errors use a stable JSON envelope:

- `code`
- `message`
- `request_id`
- `retryable`
- optional `job_id` and `document_id` correlation fields

Internal stack traces, absolute paths, API keys, and document contents are not returned.

## Versioning, idempotency, and storage

The API is versioned under `/v1`. The submission fingerprint includes source SHA-256, effective mode configuration hash, mode, and optional idempotency key. Identical work returns the existing job; key reuse for a different request returns a conflict.

The default single-node adapter uses bounded in-process workers, atomic JSON metadata under the configured artifact root, and immutable local artifacts. `JobRepository`, `DocumentRepository`, and `ArtifactStore` remain replaceable ports. A shared database, object store, distributed queue, signed artifact URLs, and restart recovery are deployment concerns for a multi-instance production profile.
