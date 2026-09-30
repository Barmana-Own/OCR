# Software Test Results

## Executed validation

| Command | Result | Evidence |
|---|---|---|
| `python -m pytest -q --cov=ocr_platform --cov-report=term-missing` | PASS | 213 passed; 86% total line coverage; 2 dependency deprecation warnings |
| `ruff check src tests scripts` | PASS | no findings |
| `python -m compileall -q src tests scripts` | PASS | no syntax errors |
| `python -m pip check` | PASS | no broken requirements |
| `python -m build --no-isolation` | PASS | source distribution and wheel built successfully; Phase 9 API, repository, and worker modules inspected in the wheel |
| `docker compose config` | PASS | local production-like Compose topology parsed |
| repository secret-pattern scan | PASS | no private-key, token, or hardcoded-credential matches |
| `pip-audit` | NOT_RUN | advisory tool is not installed in the environment |
| Real Tesseract/optional model smoke | NOT_RUN | executable/model packages are not installed; missing-backend behavior is tested explicitly |
| Independent Codex verification | NOT_RUN | no independent verifier was available in the execution environment |

## Test behavior

The suite verifies native PDF text bypasses OCR when reliable, image-only PDFs require an OCR backend, missing backends fail closed, raw text is preserved alongside Persian-normalized text, heterogeneous confidence scales are not compared, low-confidence OCR retries using a safe alternate preprocessing variant, selected-attempt geometry remains traceable, source artifacts are immutable, and export targets are deterministic.

Coverage is 86% total line coverage. The fixtures cover native Persian/mixed PDF text, scanned and mixed pages, rotation, corrupt/password-protected PDFs, tiny text, EXIF orientation, TIFF/WEBP, resource bounds, artifact safety, deterministic quality signals, skew estimation, preprocessing profiles, immutable derived artifacts, coordinate mappings, bounded 2x/3x/4x recovery, asynchronous job lifecycle, persisted completed-page checkpoints, upload signature/MIME checks, idempotent resubmission, authenticated deletion, protected artifact retrieval, policy-aware exports, malformed resource identifiers, capability readiness, content-free metrics, stage tracing, and programmatic traversal-filename rejection. The two warnings originate in installed Starlette compatibility layers (`python_multipart` import deprecation and AnyIO portal alias deprecation); they do not fail the suite and are outside project source.

## Unresolved test limitations

Accuracy metrics that require reference labels, real handwriting/table/layout models, throughput/load testing, container smoke testing, and external advisory scanning are `NOT_RUN` until the corresponding benchmark, runtime, or tool is supplied.








