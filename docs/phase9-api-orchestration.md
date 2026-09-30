# Phase 9 — FastAPI, Job Orchestration, Storage, and Workers

## Scope

Phase 9 adds a production-oriented asynchronous API boundary around the existing synchronous `DocumentPipeline`. The API remains a modular monolith: FastAPI parses requests, `DocumentJobService` owns submission and lifecycle state, the worker invokes the provider-neutral pipeline, and storage/repository ports isolate local persistence from future PostgreSQL, S3-compatible, Redis, RQ, or Celery adapters.

The existing `POST /v1/documents/process` endpoint remains available for compatibility. New clients should submit to `POST /v1/documents` and poll a job.

## API contract

All processing routes use the configured `X-OCR-API-Key` dependency when `OCR_REQUIRE_AUTH=true`. Health and readiness remain public.

| Method | Path | Result |
|---|---|---|
| POST | `/v1/documents` | `202` with a deterministic job/document submission record |
| GET | `/v1/jobs/{job_id}` | Current job state, progress, warnings, and safe failure details |
| GET | `/v1/documents/{document_id}` | Complete canonical JSON document after processing |
| GET | `/v1/documents/{document_id}/manifest` | Policy-aware export manifest |
| GET | `/v1/documents/{document_id}/pages/{page}/image` | Protected rendered page bytes |
| GET | `/v1/documents/{document_id}/exports/{format}` | JSON, text, Markdown, manifest, page, or crop export |
| POST | `/v1/documents/process` | Existing synchronous compatibility endpoint |

`POST /v1/documents` accepts multipart field `file`, optional form field `mode` (`fast`, `balanced`, or `accurate`), and either `Idempotency-Key` or `X-Idempotency-Key`.

## Upload safety

The API streams multipart data in bounded chunks and rejects empty or oversized bodies before enqueueing. It validates the actual file signature for PDF, PNG, JPEG, TIFF, and WebP. Declared MIME type is advisory only when it is `application/octet-stream`; otherwise it must be allowed and agree with the detected signature. Filename metadata rejects path separators, drive/alternate-stream separators, control characters, traversal names, and overlong values. The worker service repeats size, filename, and signature checks so programmatic callers cannot bypass the API boundary.

Uploaded bytes are kept as an immutable artifact under the content-addressed document namespace. The worker writes a private temporary copy only for the synchronous pipeline call and removes it in a `finally` block. Raw document contents, API keys, and upload filenames are not logged by default.

## Modes and configuration

Processing modes are not OCR certainty states. They select a validated settings variant:

| Mode | Default policy |
|---|---|
| `fast` | zero retries and no high-quality retry |
| `balanced` | configured base retry/high-quality policy |
| `accurate` | configured higher retry budget and high-quality retry enabled |

The policy is controlled by `OCR_MODE_MAX_RETRIES` and `OCR_MODE_HIGH_QUALITY_RETRY`; the effective settings variant contributes to the configuration hash recorded in the job and canonical document. Base DPI, tiny-text DPI, backend thresholds, page limits, and processing timeout remain in `Settings`.

## Job lifecycle

`JobStatus` is separate from `VerificationStatus`:

```text
queued -> running -> completed
                  -> completed_with_warnings
                  -> failed
                  -> cancelled (reserved for a future cancellation command)
```

The default worker uses a bounded `ThreadPoolExecutor` with `OCR_WORKER_COUNT` workers and `OCR_MAX_QUEUED_JOBS` queued slots. Submission returns without waiting for OCR. Page/stage callbacks persist `current_page`, `total_pages`, `stage`, and a bounded percentage. The local adapter persists job JSON atomically under `<storage_root>/metadata/jobs/`; canonical documents are persisted under `<storage_root>/metadata/documents/`.

No external queue is installed or silently required in this phase. The executor is intentionally a single-process adapter. Multi-process recovery, distributed scheduling, cancellation, and queue visibility require a deployment-specific repository/queue adapter and are documented as follow-on work.

## Idempotency

The service computes a submission fingerprint from source SHA-256, effective configuration hash, mode, and idempotency key. Repeated identical submissions return the existing job and set `idempotent_replay=true`. Reusing an idempotency key with a different source, mode, or configuration returns `409 idempotency_conflict`. Submissions without an explicit key still deduplicate identical source/configuration/mode work.

## Retrieval and exports

Canonical document retrieval is complete and unfiltered. Export routes use `DatasetExportPolicy` explicitly:

- `strict_verified_only` excludes accepted-but-unverified and review-required records;
- `accepted_verified` is the default derived-text/crop policy;
- `all_with_status` includes every record with its status labels.

Rendered images are read through validated `artifact://` URIs; request paths never become filesystem paths. `json`, `txt`, and `md` are returned as files. `manifest` returns the export manifest file. `pages` and `crops` return a JSON list of generated relative artifact paths so callers can fetch page images through the protected page route or process the export through a storage adapter.

## Error contract

Errors use a stable envelope containing `code`, `message`, `request_id`, and `retryable`. When a route has identified a job or document, the envelope also includes `job_id` and/or `document_id`. Request-validation errors, missing resources, unsafe upload inputs, queue capacity, idempotency conflicts, backend failures, and storage failures map to safe status codes without stack traces or absolute paths.

## Persistence and deployment boundary

`FileJobRepository` and `FileDocumentRepository` are the current local durable adapters. They use atomic JSON replacement and traversal-safe identifiers. The repository ports are intentionally small so a deployment can replace them with PostgreSQL without changing FastAPI or OCR code. Large source/page/export artifacts remain files through `ArtifactStore`; they are not stored in metadata JSON or database blobs.

The local metadata adapter is appropriate for development and a single-node deployment with a private artifact volume. Before public multi-instance production, add a shared metadata database, object storage, queue/worker runtime, authenticated artifact URLs, rate limiting, secret rotation, and restart/recovery testing.

## Validation

Phase 9 tests cover valid and invalid signature uploads, empty and oversized uploads, unsafe filenames, job lifecycle, backend failure, completed-with-warnings, repository persistence, canonical JSON/manifest/text retrieval, page-image access, strict export selection, and idempotent replay. The API tests use injected test pipelines; they do not fabricate OCR output in production code.
