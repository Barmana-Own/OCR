# Backend Architecture

## Runtime and layers

The service uses a Python 3.12+ src layout. The transport layer is FastAPI; domain schemas are Pydantic v2 models; application orchestration is in pipeline.py; ingestion, OCR, verification, storage, and export are ports/adapters. Controllers do not own OCR business rules.

## Module ownership

| Module | Ownership |
|---|---|
| domain | Canonical evidence model and closed enums |
| config | Environment parsing and safe bounds |
| ingestion/pdf/imaging | Source reading, native extraction, rendering descriptors |
| ocr/layout/handwriting/tables | Replaceable external engine contracts |
| normalization/quality | Deterministic text policy and metrics |
| ocr/verification | Attempts, consensus, uncertainty, review state |
| dataset | Versioned deterministic output |
| storage/database | Local adapter and future durable ports |
| api | HTTP parsing, auth, error envelopes, request correlation |

## Boundary rules

- Raw source and OCR text are evidence, not presentation state.
- External engines are never imported from domain modules.
- Backend confidence remains backend-specific; verification never ranks candidates across different confidence scales and emits a mismatch review flag.
- API handlers call application services and never concatenate untrusted paths or queries.
- Errors use stable safe codes; stack traces remain server-side.
- Configuration is immutable after startup and validated before use.

## Configuration and logging

Settings.from_env() validates resource limits and production authentication requirements. Structured JSON logs include a request ID and redact credential/token/raw-text fields. The logger does not receive full uploaded payloads.

## Async decision

The release exposes synchronous pipeline interfaces plus an explicit bounded worker/storage boundary. The default single-process executor calls the same pipeline service; it is injected behind repository/processor ports and is not a hidden mutable global job registry. A distributed queue can replace this adapter later.

## Verification

Core model tests are provided in tests/domain/test_models.py. External backend and infrastructure checks are dependency-dependent and are recorded as NOT_RUN until installed/configured.

## Handoff to Stage 05

Persistence ports must store immutable source metadata, processing manifests, canonical documents, attempt history, review decisions, and export manifests without replacing raw evidence.
> Cross-cutting canonical baseline: [architecture.md](architecture.md), [data-model.md](data-model.md), and [processing-flow.md](processing-flow.md). This stage document remains scoped to its delivery concerns.

