# Operations Runbook

## Startup

1. Inject production configuration and API keys from the secret manager.
2. Mount the artifact volume with ownership compatible with UID 10001.
3. Start the image and wait for `/readyz` to return `ready`; use `/healthz` only for process liveness.
4. Confirm OCR backend binaries/models are installed and licensed for the deployment.

## Monitoring

Monitor process restarts, `/healthz`, `/readyz`, authenticated `/metrics`, request latency, stage latency, upload rejection rates, backend-unavailable warnings, processing failures by reason, retry counts, human-review counts, disagreement rates, tiny-text escalations, artifact volume capacity, queue saturation, and memory use during high-DPI processing. Logs are JSON formatted and must remain free of credentials and raw document text.

## Incident response

- If the service is unhealthy, preserve the artifact volume, collect redacted structured logs and request IDs, and roll back the image if the failure follows a release.
- If OCR quality degrades, compare pipeline/config/backend/model hashes before changing thresholds; route uncertain samples to review and do not relabel them silently.
- If storage approaches capacity, stop intake or apply an approved retention policy only after preserving required source evidence and export manifests.
- If an API key is exposed, revoke/rotate it in the secret manager and restart affected instances; do not edit source files.
- If one page fails in a long document, preserve the job and page artifacts, inspect the page-level warning, and retry only that page or the document according to the queue implementation; do not discard successful pages.

## Backup and restore

Back up the artifact root and future metadata database according to retention policy. Verify restoration in an isolated environment by checking source checksums, manifest checksums, and representative canonical exports. A backup that has not passed restore verification is not considered operationally valid.

## Performance profiling

Run the permitted-fixture profiler for representative clean, phone-photo,
multi-column, table, and tiny-text samples:

```powershell
python scripts/profile_pipeline.py .\fixture.pdf --dpi 300 450 600 --output .\var\profile-results.json
```

Compare elapsed time, peak memory, artifact bytes, warning counts, and model
configuration. Do not interpret the profile as an OCR accuracy result; use the
Phase 10 benchmark for accuracy and regression gates.
