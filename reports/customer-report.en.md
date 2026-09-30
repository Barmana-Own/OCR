# Customer Delivery Report

| Field | Value |
|---|---|
| Project | High-Accuracy Universal OCR & Document Dataset Pipeline |
| Report type | Customer delivery report |
| Language | English |
| Jalali date | 1405-07-08 |
| Gregorian date | 2026-09-30 |
| Release | 0.1.0 incremental implementation program |
| Delivery status | Program implementation integrated through configurable HTR; external model and infrastructure validation remains pending |

## Executive summary

The incremental implementation program extends the existing auditable OCR foundation without replacing its modular architecture. It preserves source evidence, page structure, raw OCR text, normalized text, geometry, backend provenance, confidence, verification history, and review flags. Optional capabilities fail visibly when their runtime or model is unavailable.

## Delivered capabilities

- Native-first PDF extraction remains in place, and validated native readers now cover DOCX, XLSX, optional legacy XLS, PPTX, UTF-8 TXT, CSV, JSON, and HTML.
- Office container signatures and members are checked before native extraction; embedded visual regions retain an explicit OCR/rendering requirement.
- PaddleOCR printed recognition, PP-Structure, configurable local-only Transformers HTR, PostgreSQL, S3-compatible storage, and Redis queue integrations are isolated behind optional adapters. Paddle language/model selection, device, loading mode, cache/model paths, timeout, and download policy are configurable; HTR model choice, processor, revision, generation bound, and language/script metadata remain configurable.
- Table regions preserve printed OCR text when structure extraction is unavailable and emit explicit capability/review warnings; optional PP-Structure cells are validated, mapped from scaled crops, and exported with row/column and provenance metadata.
- Named preprocessing profiles are selected by the primary OCR path, with DPI, scale, and coordinate mapping retained for tiny-text variants.
- Verification distinguishes backend family/name, model, and model version evidence identities; same-engine preprocessing variants are recorded as stability only and cannot create false independent consensus.
- Strict and accepted+verified exports exclude records marked for review, while append-only human corrections preserve original raw text and audit history.
- Schema-driven document intelligence exposes typed fields and evidence links to source spans or cells.
- Benchmark execution can run real predictions against local external ground truth and rejects synthetic-only data when strict evaluation is requested.
- Processing timeout enforcement, bounded resources, a distributed Compose profile, and a dedicated worker entrypoint are included.

## Quality and security status

The automated suite passed 273 tests; three optional model smoke tests were skipped by configuration, with two dependency deprecation warnings. Ruff, compilation, dependency consistency, package build, Compose configuration, base-import, and the repository OpenAPI checks passed. HTR/Paddle failures remain explicitly review-required, and no handwriting, Persian, or model accuracy claim was made: real OCR/HTR/table quality still requires permitted ground truth and installed runtimes.

## Production status and limitations

No external deployment was made. Production validation still requires selected licensed OCR/layout/handwriting/table model binaries, a configured HTR model with language coverage evidence, permitted labeled ground truth, secret-manager and gateway configuration, live PostgreSQL/S3/Redis checks where selected, queue recovery validation, Docker runtime smoke tests, and external security/dependency scans. These checks are not represented as completed by this report.

## Handover

The repository contains setup instructions, safe environment templates, API documentation, deployment configuration, operations guidance, tests, and the implementation program record in docs/phase13-program.md. Uncertain OCR remains explicitly flagged for verification and is not presented as confirmed ground truth.
