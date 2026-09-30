# Phase 11 — Security, Privacy, and Training-Data Governance

## Scope and status

Phase 11 adds privacy-preserving defaults and an auditable document lifecycle to
the API-first modular monolith. Uploaded documents are treated as sensitive by
default. The implementation is local-storage based in release `0.1.0`; shared
object storage, tenant identity, and centralized retention workers remain
deployment-specific adapters.

## Sensitive-data controls

- Uploads are validated by signature, declared MIME type, size, page dimensions,
  and bounded decoded pixel count before parsing.
- Filenames and resource identifiers are validated independently of the client
  extension. Artifact paths are generated from opaque, content-addressed IDs.
- Source files, page renders, line crops, review artifacts, manifests, and
  exports remain under private artifact-store roots. API access is protected by
  the configured `X-OCR-API-Key` boundary when authentication is enabled.
- Structured logging redacts marked text-bearing fields and does not include raw
  document contents by default. Sensitive debug logging is rejected in staging
  and production.
- Configuration hashes include operational policy but exclude API keys, paths,
  and other secret-bearing values.

## Retention and deletion

`RetentionPolicy` defines separate windows for temporary processing artifacts,
source files, derived page images, and verified dataset artifacts. The policy
is configurable through `OCR_RETENTION_*` environment variables and is included
in the configuration provenance payload without secrets.

Retention deadlines are UTC-aware and are not an implicit destructive job in
the local adapter. A deployment may add a reviewed retention worker using the
same policy and artifact-store port.

`DELETE /v1/documents/{document_id}` is authenticated, rejects documents with
queued or running jobs, removes the document artifact tree and export tree, and
deletes local job/document metadata. The operation is serialized with job
submission and terminal job persistence to prevent deletion races. It returns
counts and a stable document identifier; it never deletes outside the validated
document or export roots.

## Review and training-data governance

Human-review actions are represented by immutable `ReviewAuditEvent` and
`ReviewFieldChange` models. A review record includes the reviewer identity,
timestamp, action, reason, prior value, and replacement value. Raw OCR/native
text remains immutable; corrections belong in a separate audit event or
versioned dataset layer.

Dataset export policies continue to partition `uncertain` and
`human_review_required` records unless the caller explicitly chooses
`all_with_status`.

## Operational limits and residual risks

The current local repositories are single-node adapters. Public production
operation requires a shared metadata database/object store, a durable queue,
authorization tied to an identity or tenant, gateway rate limiting, secret
rotation, malware scanning where required, and verified backup restoration.
No real customer data or credentials are included in the repository.
