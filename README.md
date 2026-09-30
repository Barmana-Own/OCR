# OCR Platform

A provenance-preserving OCR and document dataset pipeline for native-text PDFs, scanned documents, raster images, and auditable OCR verification workflows.

## Release scope

Version 0.1.0 is an API-first modular monolith with synchronous compatibility processing and bounded asynchronous job submission. It provides:

- native PDF text extraction before raster OCR when the embedded text layer is reliable;
- bounded PDF rendering and immutable local source/derived artifact storage;
- bounded Pillow quality analysis, deterministic preprocessing profiles, and auditable per-step derived image artifacts;
- tiny-text escalation with configurable 450/600 DPI recommendations, 2x/3x/4x regional variants, and cumulative page-coordinate mappings;
- typed OCR backend, layout, handwriting, and table adapter contracts;
- provider-independent printed/handwriting/table routing with explicit fail-closed capability handling;
- bounded heuristic layout detection, provider-label normalization, geometry validation, and spatial reading-order reconstruction before OCR routing;
- configurable Persian/Arabic normalization that keeps raw OCR text unchanged;
- low-confidence retry with bounded grayscale/contrast preprocessing and tiny-region scaling;
- backend-specific confidence, verification history, disagreement detection, and human-review flags;
- structured table cells, raw OCR candidates, backend runtime warnings, and deterministic source-derived line crops;
- canonical `Document -> Page -> Block -> Line -> Word` output;
- deterministic JSON, text, Markdown, page-image, line-crop, and label exports with explicit strict-verified, accepted-plus-verified, and all-with-status policies;
- authenticated processing endpoint support with safe error envelopes and request IDs;
- asynchronous document submission with fast/balanced/accurate processing modes, durable local job metadata, bounded worker execution, progress polling, idempotent resubmission, protected page images, manifests, and policy-aware exports.
- authenticated metrics and capability-aware liveness/readiness endpoints, bounded model lifecycle/concurrency settings, stage tracing hooks, page-level failure recovery, and DPI/memory/artifact profiling.
- native Office/text readers for DOCX, XLSX, PPTX, optional legacy XLS, TXT, CSV, JSON, and HTML; Office container detection is signature/member based;
- optional Paddle printed OCR, PP-Structure table cells, configurable Transformers HTR, PostgreSQL/S3-compatible metadata/artifacts, and Redis worker dispatch adapters;
- schema-driven semantic extraction with source evidence links and append-only human correction revisions;
- real-pipeline benchmark execution mode that rejects synthetic-only ground truth when external evaluation is required;
- enforced processing deadlines and an opt-in distributed worker Compose profile.

Heavy OCR/layout/handwriting model packages are optional deployment dependencies. The default Tesseract adapter fails closed when its executable is unavailable; the optional Paddle printed backend is independently configured and fails closed when its runtime or local model provisioning is unavailable. The pipeline never fabricates OCR text. NumPy/OpenCV remain optional; the required preprocessing path is bounded Pillow code. See [docs/phase6-ocr-routing.md](docs/phase6-ocr-routing.md) for Paddle language/model configuration and confidence semantics.

## Requirements

- Python 3.12 or newer
- Pillow and PyMuPDF for the core ingestion/rendering path
- an installed OCR backend for non-native pages (Tesseract is supported as an external adapter; model-backed adapters can be added through the typed ports)

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
# Optional capabilities are installed explicitly when required:
# python -m pip install -e ".[paddle,office]"
# python -m pip install -e ".[htr]"
# python -m pip install -e ".[distributed]"
```

## Validate

```powershell
python -m pytest -q
ruff check src tests
python -m compileall -q src tests
```

## Run the API

```powershell
$env:OCR_ENVIRONMENT = "development"
uvicorn ocr_platform.api.app:app --host 127.0.0.1 --port 8000
```

The public health endpoints are `/healthz` and `/readyz`. Asynchronous clients use `POST /v1/documents` with multipart field `file` and optional `mode=fast|balanced|accurate`, then poll `GET /v1/jobs/{job_id}`. Results are retrieved through `/v1/documents/{document_id}`, `/manifest`, `/pages/{page}/image`, and `/exports/{format}`. The compatibility endpoint `POST /v1/documents/process` remains synchronous. Set `OCR_REQUIRE_AUTH=true` and provide semicolon-delimited `OCR_API_KEYS` before exposing processing or artifact routes beyond a trusted local environment.

`GET /metrics` requires the same API-key boundary when authentication is enabled and returns bounded counters/latency summaries without document contents. `DELETE /v1/documents/{document_id}` is also authenticated and removes a document only when no queued or running job remains. `/healthz` reports capability metadata; `/readyz` additionally rejects unavailable configured OCR capabilities in staging and production. See [docs/phase11-security-privacy.md](docs/phase11-security-privacy.md) and [docs/phase12-production.md](docs/phase12-production.md) for retention, deletion, concurrency, recovery, and observability behavior.

## CLI

```powershell
ocr-platform process .\document.pdf --output .\document.json
```

The CLI writes canonical JSON and uses the same pipeline and artifact policy as the API.

## Production profiling

Measure representative DPI/resource costs with the real configured pipeline:

```powershell
python scripts/profile_pipeline.py .\fixture.pdf --dpi 300 450 600 --output .\var\profile-results.json
```

Use labeled benchmark data for accuracy claims; profiler output is operational evidence only.

## OCR benchmarks

Phase 10/13 provide a versioned benchmark fixture and evaluation CLI. Stored synthetic predictions are suitable for contract regression; `--run-pipeline --require-external-ground-truth` executes the configured pipeline against real local sources and refuses synthetic-only evaluation. It reports CER/WER, exact lines, geometry/order, table cells, review routing, backend disagreement, and tiny-text stage improvement separately by document category.

```powershell
python -m ocr_platform.benchmarks.run `
  --dataset benchmarks/data `
  --mode accurate `
  --output benchmark_results.json
```

Use `--baseline` for a directional regression comparison and `--fail-on-gate` for opt-in CI failure when configured thresholds do not pass. The schema, category definitions, gate format, non-private fixture policy, and GPU/model test separation are documented in [docs/phase10-benchmarks.md](docs/phase10-benchmarks.md).

## Configuration

Safe environment templates are in `.env.example`. Important limits include upload bytes, page count, page dimensions, render pixels, crop pixels, layout pixels/regions, DPI, native-text reliability thresholds, retry count, confidence thresholds, layout confidence gates, preprocessing profiles, and normalization policy controls. The configuration hash and active normalization policy are embedded in canonical output and exports. Phase 3 ingestion details are documented in [docs/phase3-ingestion.md](docs/phase3-ingestion.md), Phase 4 preprocessing/quality behavior is documented in [docs/phase4-preprocessing.md](docs/phase4-preprocessing.md), Phase 5 layout behavior is documented in [docs/phase5-layout.md](docs/phase5-layout.md), and Phase 8 dataset packaging is documented in [docs/phase8-dataset-export.md](docs/phase8-dataset-export.md).

## Canonical output

Every extracted line preserves raw and normalized text separately, geometry and coordinate space, language/script, printed/handwritten classification, extraction backend/model/version, DPI, region scale, preprocessing variant, verification status/history, uncertainty flags, and source/page provenance. Native PDF lines remain in PDF-point coordinates; OCR lines are mapped to rendered-pixel coordinates. The canonical JSON retains every certainty state; derived dataset labels default to accepted/verified evidence and require an explicit policy to include review-required records.

## Architecture

The source tree is organized around ingestion, imaging, layout/OCR/HTR/table ports, provider-independent region routing, normalization, verification, quality metrics, storage, dataset export, API transport, configuration, and workers. See [docs/phase9-api-orchestration.md](docs/phase9-api-orchestration.md) for the asynchronous API, job, storage, and worker contract and the stage documents in `docs/` for requirements, backend boundaries, authentication, security, testing, QA, and deployment.

The canonical cross-cutting architecture is documented in [docs/architecture.md](docs/architecture.md), [docs/data-model.md](docs/data-model.md), and [docs/processing-flow.md](docs/processing-flow.md).

Persistence is intentionally port-based in 0.1.0. The local artifact store is immutable, while atomic local JSON job/document repositories provide a single-node operational adapter. PostgreSQL JSONB metadata, S3-compatible artifacts, and Redis queue dispatch are available as explicit opt-in adapters; configure them through `.env.example` and use the opt-in distributed Compose worker profile. Signed artifact URLs and deployment-specific access policies remain infrastructure responsibilities.

## Operational limitations

- No browser operator UI is shipped in 0.1.0; the frontend stage is explicitly API-first.
- Model-level OCR accuracy, CER/WER, table accuracy, and handwriting quality require labeled benchmark data and installed model backends; metric hooks exist but those evaluations are not claimed without evidence.
- Static service API keys require a secrets manager, gateway rate limiting, rotation, and audit integration before public production exposure.
- The default worker executor is bounded and non-blocking for HTTP, but it is single-process; multi-instance deployments require a shared metadata database, object store, queue, worker recovery, and rate limiting.
- The default layout detector is a conservative Pillow projection fallback: it can infer visual lines, columns, basic header/footer/page-number bands, and simple grid-like table regions, but it cannot reliably identify handwriting, formulas, form fields, or table cells without a deployed model adapter. Table/HTR execution is nevertheless routed through explicit ports and fails closed when unavailable.
- A production deployment must install and license the selected OCR/layout/HTR models separately; optional PaddleOCR PP-Structure and Transformers HTR integrations are explicit and fail closed when unavailable. HTR language support is never inferred from the model name; configure and benchmark it before claiming Persian or Arabic handwriting support.
- The default local worker is intentionally single-process. Use the shared Redis/PostgreSQL/S3 adapters and restart-recovery worker process before multi-instance public deployment. The container configuration does not include model weights or external service credentials.


