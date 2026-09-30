# Security Review

## Scope and authorization

The review covers the active repository and its local API/storage/pipeline trust boundaries. No external systems were probed and no destructive exploitation was performed.

## Threat model summary

Assets include uploaded source files, raw OCR text, derived page images/crops, configuration, API keys, and canonical exports. Entry points are multipart uploads, CLI paths, environment variables, OCR backend subprocesses, and future artifact URIs. Privileged access is the service API key for processing endpoints.

## Findings

| ID | Severity | Component | Evidence | Remediation | Status |
|---|---|---|---|---|---|
| SEC-001 | High | Source storage | Reprocessing could overwrite a source artifact if a caller reused a document ID for different bytes. | Compare existing artifact checksum and reject mismatched source reuse; keep atomic immutable source writes. | Fixed and tested |
| SEC-002 | Medium | Pipeline | CLI callers could bypass the HTTP upload limit. | Enforce max source bytes inside the pipeline before hashing/reading. | Fixed and tested |
| SEC-003 | Medium | API errors | Authentication failures used a different error shape and could lose generated correlation IDs. | Use typed platform errors and persist middleware request ID in request state. | Fixed and tested |
| SEC-004 | Medium | Source metadata | Long filenames were silently truncated, weakening provenance. | Reject filenames over 255 characters. | Fixed and tested |
| SEC-005 | Medium | External OCR | A missing OCR engine could otherwise tempt fallback fabrication. | Missing adapters raise BackendUnavailableError; output remains review-required with warning. | Fixed and tested |
| SEC-006 | High | Document lifecycle | A deletion boundary must not remove another document or race an active job. | Validate opaque IDs and resolved private roots, reject symlink/reparse/non-regular entries, serialize deletion with submission/terminal persistence, and reject queued/running documents. | Fixed and tested |
| SEC-007 | Medium | Operational telemetry | Metrics and capability endpoints could leak document content or sensitive high-cardinality labels. | Metrics are bounded/content-free, label keys and values are restricted, `/metrics` is authenticated, and capability payloads contain backend metadata only. | Fixed and tested |
| SEC-008 | Medium | Container/runtime | Packaging model weights or running as a privileged user would increase deployment risk. | Run as UID 10001, mount model/cache volumes separately, exclude weight patterns from the build context, and document licensed runtime installation. | Fixed and Compose-validated |

## Input and injection review

- Filenames reject path separators/control characters.
- Storage components use a strict allow-list and resolved-root check.
- Upload bytes are bounded in API and pipeline.
- OCR subprocess arguments are passed as an argument list without a shell.
- Backend outputs are validated through the canonical model before export.
- Image decoding and preprocessing enforce page dimensions, decoded pixels, crop pixels, upload bytes, and page-count limits.
- Document deletion is authenticated and bounded to validated private roots; active jobs are protected from deletion races.
- No SQL, template, shell command construction, or user-controlled outbound URL exists in the current release.

## Browser and transport review

No browser frontend or permissive CORS policy is shipped. The operational API uses explicit API-key headers and does not put credentials in URLs. TLS/reverse-proxy configuration is deployment-owned and documented as a production prerequisite.

## Secrets and logging review

No real secrets are in source or .env.example. API keys are read from environment only, compared in constant time, and not logged or returned. Structured logs avoid raw document text and sensitive fields. The metrics route, stage labels, health capability metadata, and tracing fallback are also content-free by contract.

## Dependency review

Declared dependencies are pinned by compatible major/minor ranges in pyproject.toml. A package audit is an environment-dependent check and is recorded in the validation results when the package manager can run it.

## Residual risks

- Static API keys require rotation/secret management and gateway rate limiting before public exposure; staging/production now fail closed when auth is disabled or keys are absent.
- OCR/model licensing and model-level security depend on deployment-specific packages and weights.
- A multi-user reviewer service still needs tenant/object authorization, audit persistence, and CSRF/session decisions.
- PostgreSQL/S3/queue production adapters are not provisioned in this repository; the local worker persists page checkpoints but does not reclaim queued jobs after process restart.
- `pip-audit`, external model/GPU smoke, load testing, and Docker image execution remain `NOT_RUN` because the required external tools/runtimes were unavailable.

## Verification

python -m pytest tests/security tests/api tests/integration/test_pipeline.py -q passed. The full dependency audit and external model tests are run in the Stage 09/12 validation matrix.



