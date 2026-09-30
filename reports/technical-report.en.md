# Technical Delivery Report

| Field | Value |
|---|---|
| Project | High-Accuracy Universal OCR & Document Dataset Pipeline |
| Report type | Technical engineering handoff |
| Language | English |
| Jalali date | 1405-07-08 |
| Gregorian date | 2026-09-30 |
| Release | 0.1.0 incremental implementation program |
| Repository | `E:\OCR` |
| Repository revision | `6a8e777` (Task 03 HTR implementation checkpoint) |
| Delivery status | Incremental implementation integrated through configurable HTR; external model, GPU, and infrastructure validation remains pending |

## Scope and architecture

The repository is a Python 3.12+ API-first modular monolith using FastAPI, Pydantic v2, PyMuPDF, Pillow, typed OCR/layout/handwriting/table ports, local immutable artifact storage, deterministic dataset export, and structured logging. No browser frontend is shipped in 0.1.0; the future operator UI is specified separately.

The canonical hierarchy is `Document -> Page -> Block -> Line -> Word`. Raw and normalized text are separate fields. Coordinates carry their coordinate space, and lines retain backend/model/version, confidence scale, DPI, region scale, preprocessing variant, provenance, verification status, uncertainty flags, and attempt history.

## Implemented changes

- Source ingestion validates signatures, filenames, sizes, page counts, and source checksums.
- Reliable embedded PDF text is extracted natively before OCR.
- Mixed PDFs preserve native text blocks and route embedded image regions to OCR.
- OCR-required regions support bounded crop/preprocessing variants, tiny-text scale retries, backend adapters, and reversible geometry mapping.
- Verification preserves all attempts, flags disagreement/low confidence/tiny text/mismatched confidence scales, and fails closed on unavailable backends.
- Verification now exposes an evidence key of `(backend_family, backend, model, model_version)`, separates same-key stability from independent consensus, and records deterministic evidence counts/reason codes without treating preprocessing variants as independent engines.
- Line, table-cell, block, page, and document validators prevent `needs_review=true` from remaining `accepted` or `verified`; parent certainty is propagated from child evidence.
- Persian normalization is configurable and never overwrites raw text.
- Dataset export produces canonical JSON, plain text, Markdown, page images, line crops, labels, and deterministic manifests.
- Table extraction now has a real optional lazy PP-Structure adapter with `paddle`, `paddle-table`, and `ppstructure` aliases. Provider cells are validated in local crop coordinates, retain row/column/raw/normalized/provenance data, and map safely through non-origin and tiny-text scaled crops.
- Table backend absence, failure, timeout, empty output, or unusable structure triggers printed OCR fallback with explicit table-structure review flags; fallback text is never presented as structured cells.
- Markdown table export retains raw and normalized text, row/column, review state, bounding box, and backend/model/version; plain text is deterministic row-then-column order.
- Handwriting routing now has a real lazy Transformers/TrOCR-style adapter selected by model ID or local path, with bounded generation, local-only and remote-code-safe defaults, typed capability failures, and explicit provenance.
- HTR preserves generated raw text, configured language/script metadata, model revision, runtime parameters, crop geometry, and an explicit uncalibrated confidence state; Persian/Arabic handwriting capability is not claimed without a validated model and benchmark.
- HTR failure remains review-required. Printed OCR fallback is optional, explicitly labeled as fallback, and is never treated as handwriting ground truth or independent verification evidence.
- Quality hooks cover CER, WER, confidence, disagreement, IoU line detection precision/recall, reading order, exact-match field/cell text, review rate, and tiny-text recovery.
- API boundaries provide request correlation, streaming upload limits, typed auth errors, safe error envelopes, health/readiness, and production/staging auth fail-closed configuration.
- Security hardening covers path traversal, source immutability, bounded resources, subprocess argument safety, redaction, secret-pattern review, and regression tests.
- Security/governance adds retention policy contracts, traversal-safe authenticated deletion, private export staging, review audit records, upload pixel limits, and redacted content logging.
- Production operations add device/model-load/concurrency settings, lazy model/capability contracts, bounded metrics, optional tracing, readiness capability checks, page-failure isolation, completed-page checkpoints, a DPI/resource profiler, non-root container volumes, and model-weight exclusions.
- Deployment artifacts include `.env.example`, `.dockerignore`, `Dockerfile`, `compose.yaml`, CI workflow, OpenAPI updates, deployment documentation, and operations runbook.
- Phase 13 adds a deterministic synthetic end-to-end audit covering 11 representative scenarios, canonical schema validation, line/cell provenance checks, raw-versus-normalized reproducibility, mixed printed/handwritten routing, tiny-text escalation/mapping, retained candidates, uncertainty states, deterministic exports, and repository anti-pattern/security scans. The audit produced `docs/final-audit.md`.
- Audit model provenance: production capability inventory reported `tesseract/tesseract-lstm@external` unavailable, `heuristic-projection/pillow-projection@1` available, and HTR/table capability adapters unavailable; the synthetic benchmark recorded `embedded-text@1`, `fixture@1`, and `synthetic-primary`.

## Incremental implementation program

The following workstreams are implemented in the existing modular monolith. Adapter availability and accuracy remain environment-dependent and are not represented as model-quality claims.

| Workstream | State | Evidence |
|---|---|---|
| 01 Verification and export safety | IMPLEMENTED | Independent backend-family evidence, review-safe exports, append-only corrections |
| 02 Table extraction | IMPLEMENTED | Optional PP-Structure adapter, typed cell mapping, printed-OCR fallback |
| 03 Secondary printed OCR | IMPLEMENTED | Lazy PaddleOCR adapter with 2.x/3.x result-shape compatibility |
| 04 Handwriting HTR | IMPLEMENTED | Local-only Transformers adapter with explicit unavailable capability errors |
| 05 Advanced preprocessing | IMPLEMENTED | Named profile selection and provenance-bearing tiny-text variants |
| 06 DOCX support | IMPLEMENTED | Signature-validated native paragraphs, page breaks, and visual-region routing |
| 07 XLSX/XLS support | IMPLEMENTED | Native cells, shared strings, coordinates, and optional legacy XLS reader |
| 08 PPTX support | IMPLEMENTED | Native slide text, geometry, and embedded-image routing |
| 09 Document intelligence | IMPLEMENTED | Typed field/entity schemas with source-span and cell evidence links |
| 10 Review and correction | IMPLEMENTED | Append-only audited corrections with immutable raw text |
| 11 Real benchmark execution | IMPLEMENTED | Pipeline prediction command with external-ground-truth guard |
| 12 Docker and timeout hardening | IMPLEMENTED | Optional extras, non-root image, bounded timeout and resource settings |
| 13 Distributed production backends | IMPLEMENTED | PostgreSQL metadata, S3-compatible artifacts, acknowledged Redis in-flight queue, worker entrypoint |
| 14 Additional document formats | IMPLEMENTED | Signature-validated TXT, CSV, JSON, and HTML native readers |

## Principal files and components

- Configuration and deployment: pyproject.toml, .env.example, Dockerfile, compose.yaml, README.md.
- Ingestion: src/ocr_platform/ingestion/source.py, service.py, office_reader.py, and text_reader.py.
- OCR and structure: src/ocr_platform/ocr/backends/paddle.py, tables/paddle.py, handwriting/transformers.py, pipeline.py, and verification/engine.py.
- Governance and intelligence: src/ocr_platform/governance/review.py, intelligence/models.py, intelligence/engine.py, and dataset/exporter.py.
- Distributed adapters: database/postgres.py, storage/s3.py, workers/redis_queue.py, workers/factory.py, and worker.py.
- Benchmarks and tests: benchmarks/predict.py, benchmarks/run.py, tests/ingestion/test_office_and_text_formats.py, tests/ocr/test_optional_adapters.py, tests/intelligence/, and tests/storage/test_distributed_adapters.py.
- Documentation and state: docs/phase13-program.md, docs/openapi.yaml, project-state.json, release-manifest.json, and the bilingual reports.

## Architecture decisions

- The base installation remains usable without heavyweight model packages or downloads.
- Provider-specific OCR, HTR, table, metadata, artifact, and queue integrations remain behind typed ports and lazy adapters.
- Native text and Office structure are extracted before raster OCR; embedded visual regions retain an explicit later OCR requirement.
- Review and export policy is object-aware: default text/Markdown/page-structured/crop exports exclude review-required or blocking-evidence lines/cells, while `all_with_status` retains explicit status/review metadata and the canonical JSON remains complete.
- Configuration hashes omit secrets, and source/artifact identifiers are bounded and deterministic.
- Queue, metadata, and object-store selection is explicit through environment settings; the default remains a local modular monolith.

## Current validation evidence

| Check | Result |
|---|---|
| PYTHONPATH=src pytest -q | PASS — 273 passed, 3 skipped; two dependency deprecation warnings |
| python -m compileall -q src tests | PASS |
| ruff check src tests | PASS |
| python -m pip check | PASS |
| python -m build --no-isolation | PASS |
| docker compose config | PASS |
| docker compose --profile distributed config | PASS |
| OpenAPI structure validation | PASS |
| Secret-pattern review | PASS — no private-key or known-token pattern found |
| Real model and HTR/table runtime smoke | NOT_RUN — optional runtimes, weights, or executables unavailable |
| External-ground-truth accuracy benchmark | NOT_RUN — no permitted labeled external corpus is included |
| pip-audit | NOT_RUN — tool unavailable |
| Static type checker | NOT_RUN — no configured checker was available |
| Docker build and runtime smoke | NOT_RUN — Docker daemon unavailable |
| External deployment | NOT_PERFORMED — no target or credentials authorized |

## Task 03 configurable handwriting recognition evidence

| Requirement | Result |
|---|---|
| Configurable provider-neutral HTR adapter | PASS — `TransformersHandwritingBackend` accepts model ID/local path, processor ID, revision, device, cache, generation, image, and timeout settings without exposing provider objects to the domain layer |
| Optional dependency and no model download in standard tests | PASS — Torch/Transformers imports are lazy, the `htr` extra includes `sentencepiece`, local-files-only defaults to true, and the base-import smoke confirms both optional modules remain unloaded |
| Honest capability declaration | PASS — configured language/script are metadata only; no Persian/Arabic capability claim is made without a validated model; model revision and confidence scale are explicit |
| Provenance and confidence handling | PASS — raw generated text, crop geometry, DPI/scale, preprocessing variant, model/revision, runtime parameters, and `confidence=None` with `uncalibrated_none` are preserved |
| Routing and failure safety | PASS — HTR regions prefer HTR; unavailable/failing HTR produces typed errors and review flags; opt-in printed fallback is labeled and cannot become clean handwriting ground truth |
| Regression coverage | PASS — 22 targeted tests passed with the opt-in model smoke skipped; full suite passed with 263 tests and 2 model skips |

Task 03 implementation was committed at `6a8e777`; the implementation and evidence commits were pushed to `origin/main` through `98a9e79`. A real HTR/GPU model smoke was not run because no permitted model weights or GPU runtime were available. No handwriting accuracy or Persian handwriting support claim is made.

## Task 01 verification and export safety evidence

| Requirement | Result |
|---|---|
| Same Tesseract identity across three preprocessing variants cannot independently verify low-confidence text | PASS — deterministic regression test; independent count remains 1 and status is human review required |
| Independent backend families can satisfy configured consensus | PASS — backend-family regression test |
| Model version participates in the documented evidence identity | PASS — versioned identity regression test |
| Review state cannot coexist with accepted/verified line or table-cell status | PASS — leaf and parent aggregation model tests |
| Default and `all_with_status` exports are policy-safe | PASS — line/table text, Markdown, structured page manifest, crop label, and canonical-evidence tests |
| Candidate ordering, provenance, history, and reason-code retention | PASS — existing and new verification/export regression suite |

The Task 01 change was committed and pushed to `origin/main` at `6e78341`.

## Task 02 real table extraction and safe text fallback evidence

| Requirement | Result |
|---|---|
| Optional concrete table backend and aliases | PASS — `PaddleStructureTableBackend`/`PaddleTableBackend` with lazy PP-Structure loading and fail-closed unavailable behavior |
| Six-cell 2x3 structure and Persian/English preservation | PASS — deterministic adapter tests with zero-based row/column addresses and untouched raw text |
| Geometry validation and page mapping | PASS — invalid/out-of-region/duplicate/overlapping cells are rejected or flagged; non-origin and `region-scale-2` mappings are tested |
| Missing, failed, empty, and unusable table fallback | PASS — printed OCR text remains in the canonical block with explicit warnings and review flags |
| Table-aware exports | PASS — JSON/Markdown preserve structure/provenance; text export is row-then-column deterministic; review-required cells remain excluded by default |
| Base installation safety | PASS — importing `ocr_platform` and `ocr_platform.tables` does not require PaddleOCR; model smoke is isolated behind `model` and explicit local-runtime settings |

Task 02 was committed at `86267f9`. The optional PaddleOCR runtime/model was not installed in the validation environment; no real model accuracy claim is made.

## Task 04 independent Paddle printed OCR evidence

| Requirement | Result |
|---|---|
| Independent printed backend | PASS — `PaddleOcrBackend` is a lazy/startup optional adapter alongside Tesseract; provider imports remain isolated and the base package imports without PaddleOCR |
| Language/model configuration | PASS — `OCR_PADDLE_LANGUAGES` configures one provider language per recognizer; mixed `fas,eng` expands deterministically to Arabic-script `ar` and English `en`, with no Persian accuracy claim from the Arabic mapping |
| Provider result mapping | PASS — Paddle 2.x nested records and 3.x `predict` records map to typed lines/words, preserve raw text, confidence scale, polygon/word geometry, DPI, scale, preprocessing, language, model/package version, device, and runtime metadata |
| Confidence policy | PASS — Paddle scores are accepted only on the declared 0..1 scale; percentage-like or malformed values are not silently rescaled and generate explicit warnings/unknown confidence |
| Runtime lifecycle and failure behavior | PASS — per-backend model construction is lazy and lock-protected, reused across regions, downloads are disabled by default, CPU/CUDA selection is explicit, and missing runtime/model/GPU/OOM paths raise typed failures |
| Verification independence | PASS — Tesseract and Paddle have distinct evidence families; multiple Paddle preprocessing variants retain one evidence identity and cannot independently verify low-confidence text |
| Regression coverage | PASS — adapter, settings, geometry, malformed output, missing scores, import absence, factory expansion, lazy reuse, CPU selection, and Paddle-specific consensus tests are covered |

Task 04 remains pending real model validation because PaddleOCR/Paddle runtime packages and permitted local model weights are not installed in this environment. No Paddle accuracy or Persian-language capability claim is made. The provider runtime is available through the existing optional `[paddle]` extra plus the platform-specific Paddle runtime selected by deployment.

## Prior twelve-stage baseline status

| Stage | Status | Evidence |
|---|---|---|
| 01 Project analysis | PASS | brief, requirements, risks, integrity baseline |
| 02 Design/UI architecture | PASS | design tokens and operator/API surface architecture |
| 03 Frontend architecture | PASS_NOT_APPLICABLE | API-first 0.1.0; no browser frontend in scope |
| 04 Backend architecture | PASS | modular pipeline, typed ports, errors, configuration |
| 05 Database architecture | PASS | persistence/storage ports; local immutable adapter documented |
| 06 API integration | PASS | FastAPI endpoint, OpenAPI contract, real pipeline wiring |
| 07 Authentication/authorization | PASS | service API key, constant-time compare, negative tests |
| 08 Application security | PASS | threat review, fixes, security regression tests |
| 09 Software testing | PASS | 214 tests, 86% total coverage |
| 10 QA/debugging | PASS | no open P0/P1 defects; mixed-page and retry regressions fixed |
| 11 Deployment/production | PASS | package build, Compose config, governance, and config validated; Docker daemon unavailable |
| 12 Final review | PASS | final traceability, integrity, security, observability, and release checks |
| Phase 13 final integration audit | PASS | 11/11 scenarios passed; 18 lines and 4 table cells; provenance, schema, mixed-route, uncertainty, tiny-text, deterministic-export, and anti-pattern checks passed |

## Historical baseline validation evidence

| Check | Result |
|---|---|
| `python -m pytest -q --cov=ocr_platform --cov-report=term-missing` | PASS — 214 passed; 86% total coverage; 2 dependency deprecation warnings |
| `ruff check src tests scripts` | PASS |
| `python -m compileall -q src tests scripts` | PASS |
| `python -m pip check` | PASS |
| `python -m build --no-isolation` | PASS — sdist and wheel built; wheel contents inspected |
| `docker compose config` | PASS — local production-like topology parsed |
| OpenAPI YAML parse | PASS |
| Secret-pattern scan | PASS — no matches |
| Phase 13 synthetic end-to-end audit | PASS — 11/11 required document scenarios; 18 lines and 4 cells audited; tiny-text escalation and source mapping preserved |
| Provider/retry/raw-text anti-pattern audit | PASS — provider calls remain adapter-scoped; retry budgets and DPI defaults are bounded/centralized; no silent exception or silent LLM correction path found |
| `pip-audit` | NOT_RUN — tool not installed |
| Real Tesseract/optional model smoke | NOT_RUN — executables/model weights unavailable |
| Docker build/smoke | NOT_RUN — Docker daemon unavailable |
| External deployment | NOT_PERFORMED — no target or credentials authorized |
| Independent Codex verification | NOT_RUN — verifier unavailable |

## Security and operational review

No known Critical or High issue remains within the implemented scope. Production/staging reject disabled or keyless API authentication. Static service keys still require secret-manager rotation and gateway rate limiting. The local artifact adapter is not a substitute for durable production storage. Model licensing, benchmark accuracy, load testing, distributed queue recovery, external advisory scanning, backup restore verification against production infrastructure, and actual deployment remain explicit prerequisites.

## Integrity and regression review

The initial repository was greenfield with no pre-existing source, routes, APIs, migrations, tests, integrations, assets, or deployment files. No protected element was removed. Source, raw OCR, normalized output, native-first behavior, adapter ports, verification history, export manifests, and review flags remain present. No test was weakened to obtain a pass.

## Handover commands

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
ruff check src tests scripts
python -m compileall -q src tests scripts
docker compose config
uvicorn ocr_platform.api.app:app --host 127.0.0.1 --port 8000
```

Use `.env.example` as a safe template and inject production credentials from a secret manager. Install and configure the selected OCR/layout/HTR adapters and model weights before processing production documents.
