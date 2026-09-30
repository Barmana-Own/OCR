# Project Brief: High-Accuracy Universal OCR & Document Dataset Pipeline

## Project identity

- **Name:** High-Accuracy Universal OCR & Document Dataset Pipeline
- **Release:** 0.1.0 foundation
- **Product type:** API-first document OCR and dataset preparation service
- **Primary language:** Python 3.12+
- **Primary users:** Dataset engineers, document-processing operators, ML engineers, and reviewers

## Executive summary

The service ingests native-text PDFs, scanned PDFs, photographs, printed and handwritten pages, mixed documents, forms, IDs, invoices, contracts, books, tables, and tiny-text pages. It produces a structured, deterministic document representation that keeps raw OCR evidence, normalized text, page geometry, reading order, backend/model provenance, retry history, and review state together. Uncertainty is surfaced instead of silently repaired.

## Product objective

Create trustworthy training-data inputs in which every extracted line can be traced to its source document, page, coordinates, image/crop, OCR/layout backend, model version, preprocessing variant, and verification history.

## Problem statement

Plain-text OCR loses structure and provenance. It also encourages uncertain OCR to become unmarked ground truth. Training datasets need a canonical evidence model that supports native text when reliable, targeted OCR retries when necessary, Persian/mixed-direction correctness, and explicit human review queues.

## Target users and roles

| Role | Responsibilities | Permission intent |
|---|---|---|
| Dataset engineer | Configure pipelines, run jobs, export deterministic datasets, inspect provenance | Read/write processing jobs and exports; no secret administration |
| Document operator | Upload sources, monitor processing, inspect quality/review flags | Submit and read documents within the configured workspace |
| Human reviewer | Inspect uncertain lines/crops, approve or flag labels | Read source evidence and write review outcomes; cannot alter raw OCR |
| ML engineer | Consume versioned exports and quality metrics | Read approved/exportable artifacts; no mutation of source evidence |
| Service administrator | Configure backend adapters, storage, limits, and operational auth | Manage service configuration and operational endpoints |

## Primary user journeys

1. **Ingest and fingerprint:** upload a supported file, validate size/type, calculate checksum, store the immutable source, and create a document identity.
2. **Native-first processing:** inspect every PDF page for a reliable text layer; emit native lines when reliable and record why OCR was skipped.
3. **Adaptive OCR:** render only pages/regions needing OCR at configured DPI, route printed/handwritten/table/form/tiny-text regions to appropriate adapters, and preserve source coordinates.
4. **Verification:** assess confidence, retry low-confidence/tiny text with alternate preprocessing/DPI/backend options, compare attempts, and set an explicit final verification status.
5. **Review:** expose uncertain lines, crops, flags, and histories for a human reviewer without overwriting raw evidence.
6. **Export:** produce versioned canonical JSON, plain text, Markdown, page images, line crops/labels, and integrity manifests deterministically.
7. **Evaluate:** calculate CER/WER and pipeline metrics from reference labels where available; report review rate and backend disagreement without conflating backend confidence scales.

## Core modules

- **API/config:** HTTP boundary, request validation, auth, safe errors, environment configuration.
- **Domain/schemas:** canonical document hierarchy, enums, provenance, verification and quality models.
- **Ingestion/PDF/imaging:** source metadata, checksum, PDF native text extraction, bounded rendering, image metadata.
- **Layout/routing:** page/block classification and reading-order candidates.
- **OCR/handwriting/tables:** replaceable adapter ports, backend results, backend-specific metadata.
- **Normalization/quality:** Persian-safe normalization and metrics.
- **Verification:** retries, consensus, uncertainty, human-review state machine.
- **Dataset/storage:** immutable source/artifact storage and deterministic exports.
- **Workers/observability:** future queue boundaries, structured logs, health/readiness, correlation IDs.

## Business rules

1. Raw source bytes and raw OCR text are immutable evidence.
2. `normalized_text` may differ from `raw_text`, but normalization must be configurable and testable.
3. A line cannot be marked verified solely because it has a high backend-specific confidence value; the calibration/verification policy must support that backend.
4. Disagreement or unresolved low confidence sets `needs_review` and retains all attempts.
5. Native PDF text is preferred only when page-level reliability checks pass.
6. Every line includes document/page provenance, coordinates, extraction metadata, and a stable reading-order value.
7. Source and processing checksums identify deterministic processing inputs and configuration.
8. Backend/model versions and preprocessing variants are required metadata when OCR/layout is used.

## External integrations

| Integration | Status | Purpose |
|---|---|---|
| PyMuPDF/PDFium-compatible PDF parser | ASSUMED | Native PDF text and bounded rendering |
| Pillow/OpenCV | ASSUMED | Image metadata and preprocessing variants |
| PaddleOCR/PaddleOCR-VL/PP-Structure | OPTIONAL | Primary OCR/layout/structure backends when licensed/deployed |
| Surya-like backend | OPTIONAL | Alternate OCR/layout verifier when licensed/deployed |
| PostgreSQL | OPTIONAL | Durable metadata/jobs for multi-node deployments |
| S3-compatible object storage/MinIO | OPTIONAL | Immutable sources and derived artifacts |
| Redis + worker queue | OPTIONAL | Asynchronous long-running jobs |
| OpenTelemetry-compatible collector | OPTIONAL | Traces/metrics/log correlation |

## Major data domains

- Source document metadata and checksums
- Page geometry, source/render variants, and page classification
- Blocks, lines, words, tables, fields, and layout relationships
- OCR/layout/HTR backend attempts and model metadata
- Normalization policy/version and quality assessments
- Verification history, uncertainty flags, review decisions
- Dataset export manifests, labels, crops, and processing configuration
- Operational jobs, audit events, and access identity

## Initial security and privacy concerns

- Uploaded documents may contain personal, financial, identity, or contractual data.
- Filenames, MIME types, paths, document content, and backend outputs are untrusted.
- Raw sources and private crops must remain outside public web roots and require authorization.
- Upload size, page count, render dimensions, and retry counts must be bounded.
- Logs must redact credentials, tokens, raw document text, and unnecessary personal data.
- Operational endpoints require server-side authentication and role checks.
- Exports must not contain credentials or accidentally include local secrets.

## In scope

- Canonical schemas, native-first ingestion, adapter interfaces, routing/verification, normalization, deterministic exports, API boundary, local storage, tests, security controls, and production-like documentation.

## Out of scope

- Shipping model weights, training OCR models, a review UI, cloud provisioning, production credentials, searchable-PDF generation, and autonomous semantic correction.

## Constraints and assumptions

- External OCR engines are optional and deployment-specific; missing engines must fail closed.
- The initial repository is a modular monolith with ports for later PostgreSQL/S3/Redis integration.
- Coordinates are preserved in source page/image coordinate space with explicit dimensions and units.
- The current local environment starts without FastAPI/Pydantic/PyMuPDF/pytest, so validation must distinguish installed core checks from dependency-dependent checks.

## Risks

- OCR model quality and licensing cannot be proven without deployment-specific backends and representative labeled documents.
- Huge pages/high DPI can exhaust memory; bounded render and region limits are required.
- Confidence scales differ by backend; cross-backend comparison requires calibration.
- Reading order for complex RTL/multi-column content remains heuristic until layout models are installed.

## Initial technical direction

Use a Python 3.12+ `src` layout with FastAPI/Pydantic v2, PyMuPDF, Pillow/OpenCV-compatible ports, adapter interfaces for OCR/layout/HTR/tables, local development storage, deterministic exporters, structured JSON logs, and pytest. Keep model and infrastructure dependencies optional where possible.

## Handoff notes for Stage 02

The design must make raw/native/OCR provenance visible, represent loading/empty/error/review-required states, keep reviewer actions separate from immutable evidence, and treat Persian/mixed LTR/RTL text as data rather than UI-reversed strings. The first release is API-first; operator UI is a later consumer of the same canonical schema.
