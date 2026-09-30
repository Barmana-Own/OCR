# Phase 12 — Production Deployment, Performance, and Observability

## Deployment shape

Release `0.1.0` remains a modular monolith. The API process owns a bounded
in-process worker executor because the repository has no shared queue contract
yet. This keeps the HTTP boundary non-blocking while avoiding an unverified
fake distributed worker. A future Redis/RQ/Celery adapter can run the same
`DocumentProcessor` port as a separate worker after durable queue and restart
recovery are implemented.

`Dockerfile` builds a non-root Python 3.12 runtime image. The image contains
application code only; OCR/layout/HTR model weights are mounted or installed by
the deployment according to their licenses. `PYTHON_BASE_IMAGE` permits a
controlled CPU or vendor-compatible GPU base image without changing application
code. `compose.yaml` is a development topology with private named volumes for
artifacts, temporary work, model files, and cache; it is not a production HA
deployment.

## Runtime and model lifecycle

The validated settings surface provides:

- `OCR_DEVICE=auto|cpu|cuda`, with CPU fallback only for `auto`;
- `OCR_MODEL_LOAD_MODE=lazy|startup`;
- `OCR_GPU_INFERENCE_CONCURRENCY`, default `1`;
- `OCR_MAX_PAGES_IN_FLIGHT`, default `1`;
- `OCR_WORKER_COUNT` and `OCR_MAX_QUEUED_JOBS` for bounded process-level
  backpressure;
- `OCR_MAX_RENDER_PIXELS`, crop limits, page limits, and upload limits.

`LazyModel` loads a model once behind a lock and exposes a safe capability state
after a failed load. Explicit CUDA selection fails with a typed capability
error when CUDA is unavailable; `auto` resolves to CPU. `/healthz` reports
capabilities without making liveness depend on model availability. `/readyz`
rejects readiness in staging/production when a configured backend is unavailable.

The current default Tesseract adapter is capability-aware and fails closed when
its executable or trained data is missing. No page is relabeled with fabricated
text. Model caches and weights are separate container volumes and are not
copied into the image.

## Concurrency and recovery

Queue admission uses a bounded semaphore covering active workers and queued
jobs. Rendered pixels, crop pixels, page count, upload size, and backend timeout
settings are bounded. Accurate mode retains its verification/retry policy.

`DocumentPipeline` isolates page failures: a failed page becomes an explicitly
flagged page, the remaining pages continue, and the document/job becomes
`completed_with_warnings` when non-critical work can be preserved. Job progress
is persisted at ingestion/page/verification stages. Page-level retry and
restart recovery across process boundaries remain deployment work because the
current local executor does not reclaim queued jobs after process restart.

## Metrics and tracing

`MetricsRegistry` is thread-safe, bounded, deterministic, and content-free.
The authenticated `GET /metrics` endpoint exposes counters and latency
summaries without document text or high-cardinality identifiers. Current
signals include submissions, completions, processed pages, failures by safe
reason code, retry counts, review lines, stage events, stage latency, export
latency, and document latency.

`trace_span` records metrics-only spans when OpenTelemetry is not configured and
accepts an OpenTelemetry-compatible tracer when one is supplied. Spans cover
ingestion, native PDF extraction/image decode, PDF/image rendering, layout,
preprocessing, printed/handwriting OCR, table extraction, verification, quality
assessment, document processing, and export. Span attributes must remain
content-free; document IDs and raw text are never emitted by the built-in
metrics path.

## Profiling

The DPI cost utility runs the real pipeline against a supplied permitted fixture
and records source checksum, 300/450/600 DPI measurements, elapsed time, peak
`tracemalloc` memory, page count, warnings, processing status, artifact bytes,
configuration hash, and an optional CUDA memory snapshot:

```powershell
python scripts/profile_pipeline.py .\fixture.pdf --dpi 300 450 600 --output .\var\profile-results.json
```

The script is a measurement tool, not an accuracy claim. Model-backed accuracy
must be evaluated with the Phase 10 labeled benchmark and permitted model
runtimes. Do not treat higher DPI or generated detail as ground truth.

## Health and production checks

- `/healthz` is a process liveness endpoint and returns safe capability metadata.
- `/readyz` checks artifact-store writability and required backend capability.
- The container health check uses `/healthz`; deployment probes should use
  `/readyz` for traffic admission.
- TLS, trusted proxy headers, gateway body limits, rate limiting, alerting,
  secret-manager injection, backup/restore, and external deployment remain
  infrastructure responsibilities.

Docker daemon smoke and GPU/model deployment tests are `NOT_RUN` in the current
environment when those tools or runtimes are unavailable. The repository does
not claim a production deployment without those external prerequisites.
