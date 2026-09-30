# Project Integrity Manifest

## Baseline

This is a greenfield repository at the start of implementation. No existing source files, routes, APIs, database migrations, tests, integrations, assets, or deployment configuration were present. No Git metadata was present.

## Protected elements after initialization

- Canonical document/page/block/line/word schema and enums.
- Raw source files and immutable source metadata.
- Native-first PDF extraction path.
- OCR/layout/handwriting/table adapter interfaces.
- Normalization, verification, retry history, and uncertainty flags.
- Deterministic dataset exporters and integrity hashes.
- API, configuration, test, security, and deployment documentation.

## Phase 7 additive baseline

Phase 7 preserves the protected elements above and adds the following audited
contracts:

- backend-aware candidate comparison/scoring and finite retry planning;
- selected-candidate identity, reason codes, verification history, and bounded
  confidence fields in canonical domain models;
- immutable page review JSON/overlay artifacts and audit-complete crop labels;
- configurable verification thresholds, candidate budgets, and PDF high-DPI
  escalation settings;
- focused Phase 7 tests for mixed-script text, disagreement, tiny text,
  malformed output, settings, geometry, retries, and review provenance.

No existing route, API, database path, content asset, or prior test was removed
or disabled by this phase.

## Phase 8 additive baseline

Phase 8 preserves the canonical evidence hierarchy, raw OCR/native text,
normalization provenance, review history, immutable artifact storage, and
existing exporter compatibility paths. It adds:

- versioned configurable Persian/mixed-script normalization with protected
  identifiers, URLs, emails, dates, and serials;
- normalization policy serialization in settings hashes and canonical document
  metadata;
- explicit accepted/verified, strict-verified, and all-with-status dataset
  export policies;
- structured page manifests and line labels with raw/normalized text, page
  coordinate mapping, model inventory, status counts, and artifact hashes;
- Phase 8 tests for normalization, provenance, filtering, partitioning, and
  deterministic page/crop packaging.

No existing route, API, database path, content asset, or prior test was removed
or disabled by Phase 8.

## Phase 9 additive baseline

Phase 9 preserves the synchronous `/v1/documents/process` compatibility route,
canonical document contracts, artifact layout, exporter policies, existing
authentication behavior, and all prior tests. It adds:

- asynchronous `POST /v1/documents` submission with `fast`, `balanced`, and
  `accurate` mode contracts;
- job polling, document/manifest/page-image/export retrieval, stable error
  correlation, and idempotent source/configuration submissions;
- bounded in-process worker orchestration with persisted page/stage progress;
- atomic local job/document metadata repositories behind persistence ports;
- signature-first upload validation and traversal-safe `artifact://` reads;
- Phase 9 API, worker, and repository regression tests.

No existing route, API field, database path, content asset, or prior test was
removed or disabled by Phase 9.

## Phase 10 additive baseline

Phase 10 preserves the canonical pipeline, existing quality metric hooks, API
and worker contracts, all prior tests, and the existing CI/runtime boundaries.
It adds:

- strict versioned benchmark ground-truth and stored-prediction contracts;
- safe dataset-relative loading with synthetic non-private coverage for all
  required document categories;
- category-level CER/WER, exact-line, geometry, reading-order, table-cell,
  review-routing, disagreement, and tiny-text stage metrics;
- directional baseline comparison, configurable non-destructive quality gates,
  deterministic JSON/Markdown reports, and a module CLI;
- explicit unit/integration/benchmark/model/GPU test separation in project
  validation documentation and CI.

No existing route, API field, database path, content asset, or prior test was
removed or disabled by Phase 10.

## Phase 11 additive baseline

Phase 11 preserves all prior routes, canonical evidence, export policies,
provider ports, and test coverage. It adds:

- retention-class and review-audit contracts with secret-free configuration
  hashing;
- traversal-safe document/artifact/export deletion with active-job protection;
- temporary export staging, authenticated deletion, giant-image rejection, and
  content-redacting structured logging;
- security/privacy documentation and OpenAPI coverage for the lifecycle routes.

No existing route, API field, database path, content asset, or prior test was
removed or disabled by Phase 11.

## Phase 12 additive baseline

Phase 12 preserves the prior modular-monolith/API-first scope and adds:

- validated CPU/CUDA device, model-load, GPU inference, and page-concurrency
  settings with provider-neutral lazy model/capability contracts;
- bounded content-free metrics, optional tracing hooks, capability-aware
  readiness, and authenticated metrics retrieval;
- page-level failure isolation, persisted completed-page checkpoints, and
  profile tooling for DPI, time, memory, and artifact-size comparisons;
- non-root container defaults, private runtime volumes, model-weight exclusion,
  local Compose configuration, and production operations guidance.

No existing route, API field, database path, content asset, or prior test was
removed or disabled by Phase 12.
