# Deployment

## Intended target

The repository provides provider-neutral container configuration. No external account, DNS, cloud resource, or production deployment was created. Actual deployment status is `NOT_PERFORMED`.

## Build and run

```powershell
docker build -t ocr-platform:0.1.0 .
docker run --rm -p 8000:8000 `
  -e OCR_ENVIRONMENT=production `
  -e OCR_REQUIRE_AUTH=true `
  -e OCR_API_KEYS=<secret-from-manager> `
  -v ocr-artifacts:/var/lib/ocr-platform/artifacts `
  ocr-platform:0.1.0
```

`Dockerfile` uses a Python 3.12 slim base by default, installs the package without development dependencies, runs as UID 10001, exposes port 8000, persists artifacts, temporary work, model cache, and atomic local job/document metadata in private volumes, and includes a `/healthz` health check. `OCR_WORKER_COUNT`, `OCR_MAX_QUEUED_JOBS`, `OCR_MAX_PAGES_IN_FLIGHT`, and `OCR_GPU_INFERENCE_CONCURRENCY` bound resource use. `compose.yaml` is a local orchestration convenience and is not a high-availability production topology. The image does not package OCR model weights; a licensed CPU/GPU runtime must provide them separately.

## Configuration and secrets

Use `.env.example` only as a safe template. Production secrets must be injected by the deployment secret manager. Production/staging processing endpoints require API keys; keys must not be committed, logged, placed in URLs, or baked into images.

## Migration and persistence

Version 0.1.0 has no relational database migration. The active adapters are immutable local artifacts plus atomic JSON metadata under the same private volume. The repository exposes database and storage ports for a subsequent PostgreSQL/S3-compatible implementation. A future rollout must use additive migrations, checksum/versioned manifests, backup prerequisites for destructive changes, durable queue recovery, and a tested restore path.

## Health and proxy

- `/healthz` verifies process-level health and returns safe version information.
- `/readyz` verifies the configured artifact root can be created and is writable, and in staging/production verifies configured backend capabilities.
- `/metrics` is authenticated and returns bounded content-free counters and stage latency summaries.
- `/v1/documents` returns quickly after bounded signature validation and job persistence; `/v1/jobs/{job_id}` exposes lifecycle/progress; document and export routes require the same API-key boundary when authentication is enabled.
- TLS termination, trusted proxy handling, body limits, timeouts, CORS, and gateway rate limits belong at the deployment edge and must be explicitly configured before public exposure.

## Release gates

CI runs dependency installation, Ruff, compile validation, and pytest on Python 3.12 and 3.13. The local package build was validated with `python -m build --no-isolation`, including wheel-content inspection. The DPI profiling utility is available at `scripts/profile_pipeline.py`. Docker build/smoke, external OCR model tests, load testing, GPU profiling, and advisory scanning are `NOT_RUN` in the current environment because the Docker daemon and required tools/models were unavailable.

## Rollback

Rollback is image-based: retain the previous image and artifact volume, stop the new container, restore the prior image, and preserve source, job, document, and export artifacts. Do not delete source artifacts or queued metadata as part of application rollback. Future schema/queue changes must define roll-forward/rollback compatibility before deployment.

