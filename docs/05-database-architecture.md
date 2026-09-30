# Database and Persistence Architecture

## Decision

Release 0.1.0 uses ports, immutable local artifacts, and atomic local JSON job/document metadata rather than silently coupling business logic to a database. PostgreSQL, object storage, and distributed job queue implementations are optional deployment adapters for the next operational profile.

## Durable entities

A production persistence adapter should store:

- source documents and immutable checksum/metadata;
- processing jobs and idempotency keys;
- canonical document/page/block/line records;
- OCR/layout/HTR attempts and verification history;
- review decisions and actor/audit events;
- export manifests and artifact references.

## Integrity constraints

- Source checksum plus configuration/backend versions identify a processing input.
- Document/page/line IDs are stable within a processing result.
- Raw text and source URIs are immutable after creation.
- Review decisions append records; they do not overwrite raw OCR.
- Page numbers are positive and contiguous within a document.
- Artifact names and storage scopes are path-safe.
- Multi-record status transitions must be committed atomically by a future database adapter.

## Indexes and query paths

A PostgreSQL adapter should index (source_checksum, configuration_hash), (document_id, page_number), (line_id), (verification_status, needs_review), and (job_status, created_at). Indexes must be validated against real query plans before production rollout.

## Transactions and idempotency

Processing creation should be idempotent on source checksum + pipeline/configuration/backend selection. Export writes should be staged and atomically published. Review writes append an audit event and update a materialized status in one transaction.

## Retention and recovery

Source evidence and raw OCR have a configurable retention policy. Hard deletion is not used by the core pipeline; an explicit retention job must write an audit event, remove dependent artifacts in dependency order, and preserve deletion metadata. Destructive migrations require a backup and a tested restore procedure; roll-forward is preferred when rollback is unsafe.

## Validation

Pure storage/checksum tests are runnable without PostgreSQL. Database migration and query-plan checks are NOT_RUN until a deployment profile and disposable PostgreSQL instance are available.

## Handoff to Stage 06

The API may use the local artifact store for development but must not expose database internals. Future repositories implement the ports in src/ocr_platform/database/ports.py.
> Cross-cutting canonical baseline: [architecture.md](architecture.md), [data-model.md](data-model.md), and [processing-flow.md](processing-flow.md). This stage document remains scoped to its delivery concerns.

