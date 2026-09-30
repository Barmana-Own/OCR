# Architecture Baseline and Repository Audit

## Document metadata

| Field | Value |
|---|---|
| Project | High-Accuracy Universal OCR & Document Dataset Pipeline |
| Repository | E:\OCR |
| Release baseline | 0.1.0 |
| Phase | Phase 13 — final integration, end-to-end audit, and hardening |
| Runtime | Python 3.12+, src layout |
| Architecture | API-first modular monolith |
| Authority | This document is the cross-cutting architecture baseline; delivery-stage documents remain authoritative for narrower concerns |

## Purpose and scope

This document records the architecture that downstream implementation phases must use. It is based on the current repository rather than an idealized layout. The repository already contains a tested synchronous processing baseline, so this phase defines and reconciles the stable seams around that baseline; it does not add model weights, a worker fleet, a browser review application, or a second implementation of the pipeline.

The central design constraint is evidence preservation. A processing result is not just text: it is a versioned set of page- and region-linked observations whose raw inputs, coordinate space, extraction method, confidence semantics, preprocessing history, and review state remain inspectable.

The canonical cross-cutting flow is:

~~~text
ingest
 -> inspect source
 -> native PDF extraction when reliable
 -> page rendering when needed
 -> image quality analysis
 -> preprocessing
 -> layout detection
 -> region classification
 -> OCR/HTR/table routing
 -> reading-order reconstruction
 -> normalization
 -> verification/retry
 -> quality status
 -> canonical result
 -> dataset export
~~~

## Repository audit

### Runtime, packaging, and dependencies

| Concern | Current evidence | Architectural disposition |
|---|---|---|
| Packaging | pyproject.toml uses setuptools with src package discovery | Preserve the package boundary; keep public contracts importable from focused packages |
| Package/install | python -m pip with setuptools/wheel build backend | Keep editable installs and deterministic package builds; do not add a second package manager |
| Python | requires-python = >=3.12 | Use typed Python 3.12+ features |
| HTTP API | FastAPI application factory in src/ocr_platform/api/app.py | Keep transport thin; call the application pipeline through injected dependencies |
| Validation/schema | Pydantic v2 models in domain/models.py | Treat these models as the canonical evidence contract |
| PDF | PyMuPDF is required; PdfReader extracts text and renders pages | Keep native extraction before raster OCR; expose extraction and rendering as separate future ports |
| Raster images | Pillow is required; OpenCV is optional under the vision extra | Pillow remains the core decode/encode path; OpenCV-backed preprocessing is optional |
| OCR | Tesseract is an external adapter; PaddleOCR is optional | Keep every provider behind a protocol and fail closed when no backend is available |
| Persistence | LocalArtifactStore plus atomic local job/document JSON repositories are implemented; repository ports exist in database/ports.py | Keep local single-node persistence for the current profile; add shared durable adapters only for a justified deployment profile |
| Workers | Bounded in-process executor in workers/orchestrator.py; no external queue runtime | Keep the worker behind a processor/repository boundary; add Redis/RQ/Celery or another queue only for multi-instance/restart requirements |
| Tests | pytest tests cover domain, ingestion, preprocessing, routing, verification, API, storage, exports, and security | Extend tests at contract boundaries when target ports become executable code |
| Quality tooling | Ruff, compileall, pytest-cov, package build, and CI configuration are present | Keep these commands as the baseline gate; model-quality benchmarks are separate |
| Static type checking | No mypy or pyright configuration is present; runtime Pydantic validation and compileall are current checks | Add a static checker only with a scoped configuration decision; do not claim one is currently configured |
| Deployment | Dockerfile, compose.yaml, .env.example, and CI workflow exist | Treat these as deployment adapters, not domain dependencies |
| Source control | No .git metadata was present during audit; project-integrity-manifest.md records the greenfield baseline | Preserve the manifest and do not assume branch/commit provenance until source control is initialized |

### Reusable implementation

- src/ocr_platform/domain/models.py defines the Document -> Page -> Block -> Line -> Word hierarchy, geometry, provenance, extraction metadata, verification history, and closed enums.
- src/ocr_platform/ingestion/ separates source validation, PDF/image readers, page input records, and reader selection.
- src/ocr_platform/imaging/ provides bounded DPI/scale policy, quality hints, composable preprocessing profiles, immutable derived variants, and cumulative geometry mappings.
- src/ocr_platform/ocr/models.py, layout/, handwriting/ports.py, and tables/ports.py provide typed provider seams for most model families. Phase 5 adds provider-label mapping, geometry normalization, a bounded Pillow projection detector, an optional Paddle PP-Structure adapter, and spatial reading-order reconstruction.
- src/ocr_platform/ocr/routing/page_router.py provides conservative native-first/tiny-text routing and spatial RTL-aware reading order without reversing Unicode strings.
- src/ocr_platform/ocr/verification/ preserves provider-neutral comparison, backend-aware scoring, bounded retry planning, consensus decisions, persisted reason codes, and review artifacts.
- src/ocr_platform/normalization/persian.py keeps raw text unchanged and applies configurable Persian/Arabic variant and digit policies to normalized_text.
- src/ocr_platform/storage/artifacts.py provides traversal-safe, immutable-by-default, atomic local artifact writes with checksums.
- src/ocr_platform/dataset/exporter.py produces deterministic JSON, text, Markdown, page-image, page-manifest, crop, label, and provenance-manifest outputs under explicit certainty policies.
- src/ocr_platform/quality/metrics.py provides CER/WER, geometry, reading-order, exact-match, review-rate, disagreement, and tiny-text metric functions.

### Technical debt and deliberate gaps

1. PdfReader is a concrete PyMuPDF adapter that implements the named PdfExtractor and PageRenderer contracts; its extraction and rendering methods remain separate within the adapter.
2. DocumentResult now carries ProcessingStatus separately from VerificationStatus; job lifecycle must never be inferred from OCR certainty.
3. ArtifactStore and QualityEvaluator are now executable protocols; LocalArtifactStore is the current storage adapter and quality.metrics remains the pure-function basis for a future evaluator implementation.
4. OCRCandidate, VerificationRecord, and typed extraction metadata are now canonical domain models; the legacy verification records remain compatibility aliases where required.
5. ProcessingWarning and ProcessingManifest are implemented typed models. Legacy warning strings remain only for serialized compatibility.
6. Phase 4 adds a bounded Pillow quality analyzer for brightness, contrast, sharpness/blur, skew, perspective hints, background variation, text scale, and compression evidence. These remain routing hints rather than absolute truth; real model-quality evaluation still requires labeled data.
7. LayoutBackend, HandwritingBackend, and TableExtractionBackend are available as ports. The default pipeline executes LayoutAnalysisService with a bounded Pillow projection detector before OCR routing; printed OCR is adapter-backed, while HTR and table capability remain explicit fail-closed adapters until real model runtimes are deployed.
8. DocumentPipeline is intentionally the 0.1.0 orchestration boundary, but it owns multiple phases. Future extraction into application services must preserve the same canonical output and provenance behavior.
9. get_settings() caches a module-level settings object. It is safe for the current process-start configuration model, but application construction should prefer explicit settings injection if runtime reconfiguration or multi-tenant configuration is introduced.
10. No relational migrations or durable review repository are shipped. Phase 9 does ship atomic local job/document repositories; shared relational persistence and queue recovery remain an explicit deployment boundary, not an implicit in-memory production fallback.
11. Dataset export is policy-aware by design: the canonical document remains complete, while derived labels default to accepted/verified evidence and never silently include review-required records.

## Target module boundaries

The repository remains a modular monolith. Boundaries are dependency boundaries, not deployment boundaries.

| Boundary | Current location | Owns | Must not own |
|---|---|---|---|
| Transport/API | api/app.py, api/auth.py, api/schemas.py | HTTP parsing, upload bounds, auth dependency, request IDs, safe errors | OCR routing, persistence queries, provider-specific logic |
| Configuration | config/settings.py | environment parsing, immutable limits, configuration hash | per-document business decisions |
| Ingestion | ingestion/source.py, ingestion/service.py, ingestion/image_reader.py, ingestion/models.py | file signature/type validation, source metadata, page descriptors, reader selection | OCR, normalization, model confidence interpretation |
| PDF analysis | ingestion/pdf_reader.py today; future pdf ports | embedded text extraction, text-layer reliability, image-region discovery, PDF page geometry | OCR-provider calls and dataset export |
| Page rendering | PdfReader.render_page and ImageReader.render today | bounded rasterization and render metadata | text recognition and normalization |
| Imaging/preprocessing | imaging/policy.py, imaging/preprocess.py, imaging/quality.py, imaging/geometry.py, imaging/profiles.py, imaging/operations.py, imaging/service.py | safe DPI/scale decisions, quality hints, composable variants, immutable transformation manifests, coordinate transforms, tiny-text escalation | model selection, confidence calibration, and acceptance decisions |
| Layout | layout/ports.py, classification.py, normalization.py, heuristic.py, providers.py, reading_order.py, service.py | provider-neutral regions/lines, stable taxonomy, geometry clipping, routing hints, column/RTL spatial order, backend provenance | text normalization, OCR winner selection, and provider SDK imports outside adapters |
| Routing | ocr/routing/page_router.py | native/OCR decisions, region hints, reading-order reconstruction | inventing text or unsupported classification |
| OCR adapters | ocr/models.py, ocr/backends/ | provider invocation, response parsing, backend/model/version/confidence scale | cross-backend score calibration and final review decisions |
| Handwriting | handwriting/ports.py and future adapters | HTR invocation and typed result conversion | changing raw text or hiding uncertainty |
| Tables/forms | tables/ports.py and future adapters | cell/field geometry and extraction metadata | generic OCR policy or persistence |
| Normalization | normalization/persian.py | configurable raw-to-normalized transformation | overwriting raw evidence or UI bidi reordering |
| Verification | ocr/verification/comparison.py, scoring.py, retry.py, engine.py | Unicode-aware comparison, backend-specific scoring, bounded escalation, status, reason codes, flags, attempt history | silent repair, LLM correction, or cross-scale comparison |
| Quality | quality/metrics.py and future evaluator | reference-based metrics and quality assessment | backend-specific calibration unless configured |
| Canonical domain | domain/models.py | evidence schema, invariants, closed enums, serialization | filesystem, HTTP, OCR SDKs, database clients |
| Storage | storage/artifacts.py and future adapters | immutable bytes, URIs, checksums, artifact reads | OCR/business decisions |
| Persistence | database/ports.py and future repositories | documents, jobs, review events, manifests, audit records | source parsing or provider execution |
| Dataset export | dataset/exporter.py | deterministic dataset views, labels, manifest hashes | changing canonical evidence |
| Application orchestration | pipeline.py | ordered use of boundaries and fail-closed behavior | provider-specific implementation or UI concerns |
| Workers | workers/models.py, ports.py, policy.py, orchestrator.py | mode policy, bounded submission, job lifecycle, progress, safe failures, pipeline invocation | OCR/provider logic, HTTP parsing, or a second processing implementation |

### Dependency direction

~~~text
FastAPI / CLI
    -> application orchestration
        -> ingestion, imaging, routing, verification, normalization, export
            -> domain models and provider/storage/persistence protocols
                -> concrete adapters (PyMuPDF, Pillow, Tesseract, local files, future services)

domain
    -> standard library / Pydantic only
domain -X-> FastAPI, OCR SDKs, filesystem clients, database clients
~~~

A provider adapter may depend on domain-neutral result records and domain enums, but domain models must not import a provider SDK. The worker and future database repositories may depend on application ports; the application service must not depend on a specific queue or database implementation.

## Stable provider and infrastructure contracts

The following signatures are the architecture target. Existing contracts are preserved where they already exist. Contracts marked target extraction are documented now and should be introduced later only when there is a concrete adapter or persistence consumer.

### PDF extraction

~~~python
class PdfExtractor(Protocol):
    name: str
    version: str

    def extract(
        self,
        source_path: Path,
        *,
        document_id: str,
        source_uri: str,
    ) -> tuple[PageInput, ...]:
        """Return page geometry, native lines, image regions, and reliability evidence."""
~~~

Current implementation: PdfReader.extract, with read retained as a compatibility alias. The adapter preserves PDF-point coordinates and retains the reason a native text layer was accepted or rejected.

### Page rendering

~~~python
class PageRenderer(Protocol):
    name: str
    version: str

    def render_page(
        self,
        source_path: Path,
        *,
        page_number: int,
        dpi: int,
    ) -> RenderedPage:
        """Render one page under configured pixel/resource limits."""
~~~

Current implementation: PdfReader.render_page for PDFs and ImageReader.render for raster input. The ingestion service selects the adapter and records source/render provenance without duplicating native-only rasterization.

### Layout

Current executable contract in src/ocr_platform/layout/ports.py:

~~~python
class LayoutBackend(Protocol):
    name: str
    model: str
    model_version: str

    def detect(
        self,
        image_bytes: bytes,
        *,
        page_width: float,
        page_height: float,
    ) -> tuple[LayoutRegion, ...]:
        ...
~~~

LayoutRegion contains provider-neutral bbox/polygon geometry, block type, confidence, reading order, route hint, text-type hint, tiny-text signal, optional line geometry, and uncertainty flags. LayoutResult adds backend/model provenance, coordinate space, reading direction, column count, and warnings. `normalize_layout_region` clips valid finite geometry to page bounds, derives an internal bbox from a polygon, and preserves the provider-native polygon separately. An adapter that cannot classify a region must return an explicit unknown or unavailable result; it must not silently label it as printed text.

The executable `LayoutAnalysisService` normalizes provider output, applies the configured confidence gate, orders regions and lines spatially, and exposes deterministic warnings. `HeuristicLayoutBackend` is the dependency-light production fallback; `PaddleStructureLayoutBackend` is an optional model adapter and raises a typed unavailable error when its runtime is absent. Layout evidence is converted into OCR-region routing metadata without changing raw text or provider confidence semantics.

### OCR

Current executable contract in src/ocr_platform/ocr/models.py:

~~~python
class OcrBackend(Protocol):
    name: str
    model: str
    model_version: str
    confidence_scale: str

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        ...
~~~

OcrResult contains backend/model/version, extraction method, confidence scale, DPI, region scale, preprocessing variant, typed line/word geometry, runtime metadata, and warnings. The backend owns parsing its native response; verification owns selection. The pipeline copies runtime metadata and warnings into canonical ExtractionMetadata without comparing provider scores across confidence scales.

### Handwriting

Current executable contract in src/ocr_platform/handwriting/ports.py:

~~~python
class HandwritingBackend(Protocol):
    name: str
    model: str
    model_version: str
    confidence_scale: str

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        ...
~~~

HTR output uses the same geometry/provenance shape as OCR but must report ExtractionMethod.HANDWRITING_RECOGNITION and an explicit handwritten or mixed text type when supported.

### Tables and structured regions

The repository currently calls this TableExtractionBackend; the architecture-level name is TableBackend to match the requested boundary.

~~~python
class TableBackend(Protocol):
    name: str
    model: str
    model_version: str

    def extract(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
    ) -> tuple[TableCell, ...]:
        ...
~~~

TableCell carries row, column, raw text, optional normalized text, bounding box/polygon, language/script, backend confidence, and raw candidate alternatives. TableResult adds backend/model/version, confidence scale, DPI/scale/preprocessing, runtime metadata, and warnings. A future form/key-value contract may extend this with field IDs and key/value relationships without changing the generic OCR line contract.

### Quality evaluation

Target extraction contract; the current repository provides metric functions but not this protocol:

~~~python
class QualityEvaluator(Protocol):
    name: str
    version: str

    def evaluate(
        self,
        document: Document,
        *,
        reference: ReferenceDocument | None = None,
    ) -> QualityAssessment:
        """Return quality/review evidence without mutating document text."""
~~~

Reference data is optional for production processing. CER/WER and detection/table/field accuracy require labeled references. Without a reference, the evaluator may report confidence/disagreement/review-rate signals but must not fabricate accuracy.

### Artifact storage

Target extraction contract; LocalArtifactStore is the current concrete adapter:

~~~python
class ArtifactStore(Protocol):
    def put_bytes(
        self,
        document_id: str,
        artifact_name: str,
        data: bytes,
        *,
        overwrite: bool = False,
    ) -> StoredArtifact:
        ...

    def get(self, document_id: str, artifact_name: str) -> StoredArtifact:
        ...

    def read_bytes(self, document_id: str, artifact_name: str) -> bytes:
        ...

    def exists(self, document_id: str, artifact_name: str) -> bool:
        ...
~~~

Implementations must validate path/object components, preserve checksum and byte size, write atomically, and never overwrite the original source as a side effect of derived-artifact generation.

## Status model

Job lifecycle and OCR certainty are separate axes.

### Processing/job status

The target job status is:

~~~text
pending
processing
completed
completed_with_warnings
failed
~~~

This belongs to a job/document-processing record and future JobRepository. It answers “did the requested processing run?” It does not answer whether every line is trustworthy.

### Extraction/review status

The current closed enum VerificationStatus is:

~~~text
accepted
verified
uncertain
human_review_required
failed
~~~

It answers “how should this extracted evidence be treated?” It belongs to lines, verification attempts, quality assessment, and—until the job model is split—the current Document.status.

Required rule: a job may be completed_with_warnings while one or more lines are human_review_required; a job may be completed even when its result contains accepted-but-not-verified lines. A processing failure must never be represented as a high-confidence OCR result.

## Architecture decision records

### ADR-001 — Prefer reliable native PDF text

Decision: Inspect and use embedded PDF text before raster OCR when page-level reliability checks pass.

Reason: Native text retains the original text layer and PDF-point geometry, avoids unnecessary rasterization, and reduces OCR error. Raster OCR remains required for image-only pages, unreliable layers, or missing image-region text.

Consequence: The reliability reason is part of page provenance. Mixed pages retain native blocks and route only discovered image regions to OCR.

### ADR-002 — Make line-level provenance mandatory

Decision: Every canonical line carries document ID, page number, coordinate space, geometry, source URI, extraction metadata, and optional crop URI.

Reason: Training-data consumers and human reviewers must trace a label to source evidence and reproduce the processing attempt.

Consequence: A line without source/page/geometry provenance is incomplete and must not be exported as canonical training evidence.

### ADR-003 — Keep raw and normalized text separate

Decision: raw_text is immutable backend/native evidence; normalized_text is a separate, versioned policy output.

Reason: Normalization is useful for search, comparison, and evaluation, but must not erase what the backend actually returned. This is essential for Persian/Arabic variants, digits, punctuation, IDs, and mixed RTL/LTR content.

Consequence: Exporters and reviewers can choose the appropriate field, and normalization regressions can be tested independently.

### ADR-004 — Use adaptive DPI and bounded regional scaling

Decision: Default render DPI is approximately 300; high-quality mode is approximately 450; tiny-text mode may use 600 plus bounded region scaling. Re-render or crop only affected pages/regions.

Reason: Tiny text needs more source pixels, but converting every page to a huge raster increases memory, latency, and failure risk without adding information.

Consequence: RenderPolicy, pixel limits, crop limits, and preprocessing variant names are recorded in extraction metadata. Super-resolution is never treated as information recovery.

### ADR-005 — Keep external engines behind adapters

Decision: OCR, HTR, layout, table, PDF, rendering, and storage providers are accessed through protocols and provider-neutral records.

Reason: Deployment, licensing, model quality, and hardware vary. Domain and verification policy must not be rewritten when a provider changes.

Consequence: Provider adapters own SDK parsing and availability errors; the application owns routing, provenance, and review policy.

### ADR-006 — Treat confidence scales as backend-specific

Decision: Store the backend confidence scale and never rank or directly compare scores from different scales without explicit calibration.

Reason: A numeric score is not semantically portable between engines. Cross-engine disagreement is evidence for review, not permission to select the largest number.

Consequence: Verification emits confidence_scale_mismatch and retains all attempts when scales differ.

### ADR-007 — Persist verification history

Decision: Preserve every bounded retry/alternate attempt, its raw and normalized text, confidence, extraction metadata, difference from the previous attempt, reason, and resulting status.

Reason: Dataset provenance requires evidence of how the selected result was reached. Discarding losing attempts hides uncertainty and blocks later policy evaluation.

Consequence: Persistence and exports must retain attempt history; a reviewer can inspect the decision without rerunning the backend.

### ADR-008 — Start as a modular monolith

Decision: Keep one deployable application with explicit ports for storage, persistence, providers, and workers.

Reason: Current requirements need clear seams and deterministic processing, not independent service deployment. A queue, PostgreSQL, S3-compatible store, or OpenTelemetry collector is justified only when operational requirements require it.

Consequence: Later asynchronous execution can invoke the same application service and canonical contracts instead of creating a second pipeline.

### ADR-009 — Separate processing lifecycle from extraction certainty

Decision: Introduce a distinct ProcessingStatus in the durable job/application model and reserve VerificationStatus for extracted evidence.

Reason: A completed job can contain review-required lines, and a failed job is not an OCR certainty state. Conflating them makes operational dashboards and dataset gates ambiguous.

Consequence: This is a Phase 2 schema seam. The current Document.status field is retained for compatibility until the job/document status contract is versioned.

### ADR-010 — Treat preprocessing as auditable derived evidence

Decision: Every named preprocessing operation creates a separate derived
artifact and a transformation record. The record retains input/output
references, parameters, warnings, and a cumulative mapping to the rendered
page and optional PDF-point reference.

Reason: OCR training data must remain traceable to the pixels that produced a
candidate. In-place image mutation loses the source evidence and makes retries
irreproducible.

Consequence: The local artifact store is used through `ArtifactStore`, source
artifacts are never overwritten, and a same-path/different-bytes collision is a
storage failure rather than a silent replacement.

### ADR-011 — Use conservative, bounded quality hints and regional escalation

Decision: Analyze large images on a bounded sample, render ordinary pages at
the configured default DPI, and escalate only evidence-supported pages or
regions to high/tiny DPI and bounded 2x/3x/4x crops.

Reason: Quality metrics are imperfect signals and aggressive processing can
erase strokes or create misleading detail. Dataset integrity is more important
than treating every page as a maximum-resolution case.

Consequence: Tiny-text decisions carry reasons, recommended DPI, and an
explicit verification requirement. No generated detail is treated as ground
truth.

### ADR-012 — Normalize layout geometry and spatial order before OCR

Decision: All layout output passes through a provider-neutral normalization and
reading-order service before it is handed to OCR/HTR/table routing.

Reason: Provider taxonomies and polygon conventions vary, while downstream
canonical output requires stable block/line geometry and numeric order. A
single service provides one place to clip safe coordinates, reject impossible
geometry, preserve provider-native polygons, and retain uncertainty.

Consequence: RTL affects spatial column and line ordering only; it never
reverses characters or mutates raw text. Tables remain atomic layout regions
until a table adapter supplies cell evidence. Unknown, low-confidence, or
model-unavailable classifications remain explicitly reviewable.

## Phase 1 handoff and implementation gates

Downstream implementation phases can proceed against:

1. domain/models.py for current canonical evidence fields and invariants.
2. The provider contracts above for typed adapter boundaries.
3. docs/data-model.md for target status and audit extensions.
4. docs/processing-flow.md for ordered orchestration and failure behavior.
5. docs/04-backend-architecture.md, docs/05-database-architecture.md, and docs/06-api-design.md for stage-specific constraints.
6. Existing tests under tests/domain, tests/ingestion, tests/ocr, tests/integration, tests/quality, tests/storage, tests/dataset, and tests/security.

At the Phase 3 gate, bounded PDF/image inspection and artifact-backed page
descriptors were added without implementing downstream OCR/layout/HTR/table
engines. Phase 5 now implements the provider-neutral layout stage and its OCR
handoff; rich HTR/table-cell model execution remains deployment-dependent.



## Phase 3 implementation update

The ingestion boundary is now executable rather than only architectural. `DocumentIngestionService` computes a content-addressed document ID, persists the immutable source under `source/original.bin`, uses `PdfReader` or `ImageReader` per detected content type, and returns an `IngestionResult` with ordered `PageInput` records, typed warnings, and processing status. `PdfReader` implements `PdfExtractor` and `PageRenderer`; `ArtifactStore` is an injectable protocol. Native text reliability, PDF-point geometry, page rotation, embedded image regions, EXIF correction, pixel limits, and render artifacts are covered by `tests/ingestion/test_phase3_ingestion.py`.

The former Phase 2 target notes remain valid for real HTR/table adapters and
durable persistence/worker adapters. QualityEvaluator now has a stable
protocol, Phase 4 adds image-quality hints, and Phase 5 adds a real bounded
layout fallback plus an optional model adapter without claiming model-level
accuracy. Reference-dataset aggregation remains future work.

## Phase 4 implementation update

The imaging boundary now exposes `ImageQualityAnalyzer`, deterministic
preprocessing profiles, conservative Pillow operations, projective geometry
mapping, and `PreprocessingService`. Each persisted derived step records its
input/output artifact references, normalized parameters, warnings, and mapping
back to the source/page coordinate space. Tiny-text recovery is explicit and
bounded: it recommends a higher DPI when appropriate, persists 2x/3x/4x
regional variants, and marks all variants for downstream verification. The
source and original page render remain immutable.

## Phase 5 implementation update

The layout boundary is now executable. `LayoutAnalysisService` accepts native
PDF line evidence or raster page bytes, validates/clips provider geometry,
normalizes provider labels into the stable `BlockType`/`RegionRouteHint`
taxonomy, applies a layout-confidence gate, and reconstructs spatial reading
order for headers, body columns, sidebars, tables, footers, and page numbers.
`HeuristicLayoutBackend` provides bounded Pillow projection detection without
fabricating text or unsupported handwriting/formula/cell semantics;
`PaddleStructureLayoutBackend` is an optional adapter that fails closed when
PaddleOCR is unavailable. The pipeline now passes layout-derived regions and
reading-order metadata into OCR and reconciles native blocks with layout
classification while preserving the existing native-first behavior.

## Phase 6 implementation update

Region execution is now selected by `RegionRouter` from stable block, text,
and layout hints. Printed regions use configured `OcrBackend` adapters;
handwriting regions use only `HandwritingBackend`; table regions use only
`TableBackend`; forms and explicitly mixed regions can invoke printed OCR and
HTR independently. Missing HTR/table capability is surfaced as a typed warning
and review-required evidence rather than a printed-text fallback.

`OcrResult` and `TableResult` retain runtime metadata and warnings. The
pipeline copies that evidence into `ExtractionMetadata`, maps all provider
geometry back to rendered page coordinates, preserves all line candidates and
verification attempts, and stores deterministic source-derived line crops when
the artifact store accepts them. Structured table cells are represented by
`BlockResult.table_cells` with row/column indexes, raw and normalized text,
geometry, confidence, provider provenance, and candidate alternatives.

## Phase 7 implementation update

Verification now treats every OCR/HTR/table-cell output as candidate evidence.
`comparison.py` performs NFC-aware, normalization-aware, edit-distance,
digit/punctuation/whitespace difference analysis without changing raw text.
`scoring.py` applies backend-specific thresholds and text-quality signals;
numeric confidence values are never ranked across different providers.
`retry.py` defines a finite sequence for first pass, preprocessing variants,
higher-resolution rendering, region scales, and alternate backends. The
pipeline enforces a candidate budget and escalates PDF pages to configured
high-quality DPI only when the last evidence remains weak.

Canonical candidates, attempts, lines, table cells, and blocks retain selected
candidate IDs, structured reason codes, and verification history. Unresolved
disagreement, malformed text, low confidence without consensus, and missing
evidence remain explicit rather than being repaired. Review-needed lines store
an immutable JSON evidence package plus a highlighted page overlay containing
the source page, crop URI, geometry, candidates, confidences, preprocessing
metadata, reasons, and attempt history. No general-purpose LLM is used to
overwrite OCR evidence.

## Phase 8 implementation update

`NormalizationConfig` is now an explicit, versioned policy object with
environment-backed Unicode, character-variant, digit, whitespace, line-break,
zero-width, tatweel, and edge-trimming controls. It is included in the
effective configuration hash and copied to `DocumentResult.normalization_policy`.
Protected URL, email, date, serial, and mixed Latin/number tokens are not
digit-converted by the default normalization pass. Raw text remains unchanged.

`DatasetExporter` depends on `ArtifactStore`, validates export/document/line
path components, writes page manifests and structured crop labels, and uses
an atomic temporary export directory. `strict_verified_only`,
`accepted_verified`, and `all_with_status` policies are separate export
identities. The canonical JSON is never filtered; derived text, Markdown, and
line crops are filtered explicitly and manifests record counts, warnings,
source/configuration/model provenance, processing time, normalization policy,
and sorted artifact hashes.

## Phase 9 implementation update

The API/worker boundary is now executable. `api/app.py` keeps transport,
authentication, request IDs, bounded multipart reads, and safe error mapping
separate from `workers/orchestrator.py`, which owns submission fingerprints,
mode policy selection, bounded executor capacity, progress transitions, and
worker failure state. `workers/models.py` defines `JobStatus`,
`ProcessingMode`, `JobProgress`, `JobError`, and `JobRecord`; these operational
records remain separate from canonical OCR `VerificationStatus`.

`database/ports.py` now exposes document/job repository seams. The local
`FileJobRepository` and `FileDocumentRepository` use atomic JSON metadata under
the private artifact root, while in-memory adapters remain test-only injection
options. `storage/artifacts.py` validates and reads `artifact://` references
without turning request path segments into filesystem paths. Large source,
page, crop, and export artifacts remain outside metadata records.

The default application uses a bounded single-process executor because no
queue/database infrastructure exists in the repository. The worker invokes the
existing `DocumentPipeline` through a narrow processor port and supports a
future queue adapter without duplicating OCR logic. The local adapter is not a
multi-instance recovery solution; shared persistence, distributed workers,
signed artifact access, rate limits, and restart recovery remain deployment
decisions rather than hidden assumptions.

