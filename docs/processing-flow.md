# Processing Flow and Operational State Model

## Document metadata

| Field | Value |
|---|---|
| Project | High-Accuracy Universal OCR & Document Dataset Pipeline |
| Release baseline | 0.1.0 |
| Scope | Ordered processing flow, routing, retries, provenance, status, and failure behavior |
| Implementation entry point | src/ocr_platform/pipeline.py |
| Related contracts | docs/architecture.md and docs/data-model.md |

## Required end-to-end flow

The pipeline must preserve this order. A later phase may split an implementation step into smaller services, but it must not bypass the evidence or review gates:

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

## Phase 9 API execution boundary

The HTTP submission path wraps this flow with an explicit job boundary:

```text
validate multipart size/name/signature/MIME
 -> compute source/configuration/mode fingerprint
 -> reuse idempotent job or persist queued job and immutable upload artifact
 -> return 202
 -> bounded worker marks running and persists page/stage progress
 -> invoke DocumentPipeline with the effective mode settings
 -> persist canonical DocumentResult and terminal job status
 -> serve canonical JSON, manifest, page images, and policy-aware exports
```

`JobStatus` is operational state (`queued`, `running`, `completed`,
`completed_with_warnings`, `failed`, or reserved `cancelled`). It is never
used as a substitute for line/block `VerificationStatus`. The current local
worker is a single-process adapter; durable distributed queues and recovery
remain deployment-specific ports.

## Current implementation mapping

| Stage | Responsibility | Current implementation | Output/evidence | Failure behavior |
|---|---|---|---|---|
| 1. Ingest | Accept a local path or API upload and establish a document identity | api/app.py, cli.py, pipeline.py | Bounded source path, filename, declared type, source checksum | Reject missing/oversized/unreadable sources |
| 2. Inspect source | Verify signature/content type and create immutable source metadata | ingestion/source.py, ingestion/service.py, storage/artifacts.py | DocumentSource, source/original.bin, SHA-256, artifact URI | Reject unsupported signatures, empty files, unsafe names, traversal |
| 3. Native PDF extraction when reliable | Read embedded text and discover image regions before OCR | ingestion/pdf_reader.py, PdfReader._native_lines, _native_evidence, _image_regions | PageInput with PDF-point native lines, reliability boolean/reason, image regions | Mark native text unreliable and route page/regions to raster processing |
| 4. Page rendering when needed | Render only OCR-required pages under DPI/pixel bounds | ingestion/pdf_reader.py, ingestion/image_reader.py, imaging/policy.py | RenderedPage, rendered artifact URI, source/render dimensions and DPI | Reject excessive render dimensions or unavailable parser/decoder |
| 5. Image quality analysis | Determine whether the available pixels are suitable and whether higher quality is warranted | imaging/quality.py, ImageQualityAnalyzer, reader quality metadata | Brightness, contrast, sharpness/blur, skew, perspective/background hints, text scale, compression evidence, and explicit flags | Signals are hints; preserve unknown values and route suspicious pages/regions to verification |
| 6. Preprocessing | Produce bounded, named variants and crop/scale tiny regions | imaging/profiles.py, operations.py, service.py, preprocess.py, geometry.py | Immutable per-step artifacts, transformation metadata, profile, warnings, and mapping to rendered/page coordinates | Reject invalid crop, empty region, oversized output, unsupported profile/operation, or immutable path collision |
| 7. Layout detection | Detect provider-neutral regions, lines, geometry, confidence, and order | layout/service.py, layout/normalization.py, layout/reading_order.py over `LayoutBackend` | Ordered `LayoutResult` with regions, line hints, direction, columns, and warnings | Invalid geometry is rejected per region; unavailable providers remain typed warnings/errors |
| 8. Region classification | Map provider labels into title/paragraph/header/footer/page-number/table/formula/form/image/handwriting/sidebar/list/multi-column/tiny-text/unknown and route hints | layout/classification.py, domain enums, heuristic.py, providers.py | `LayoutRegion` and OCR `OcrRegion` metadata | Unknown, low-confidence, or unsupported classes remain reviewable; no silent rich-class default |
| 9. OCR/HTR/table routing | Select a capability-specific adapter for each layout region and execute it on a bounded crop/variant | ocr/routing/region_router.py, ocr/backends/, handwriting/, tables/, pipeline.py | OcrResult or structured TableResult with backend/model/version, confidence scale, runtime metadata, warnings, geometry, and candidates | Handwriting/table capability never silently falls back to printed OCR; only an explicitly configured fallback may preserve text, and it remains review-required |
| 10. Reading-order reconstruction | Sort blocks and lines spatially in document order | layout/reading_order.py, layout/service.py, ocr/routing/page_router.py, pipeline block assembly | Non-negative block/line `reading_order`; RTL horizontal order without string reversal | Ambiguous order stays in evidence and can trigger review; no character mutation |
| 11. Normalization | Create a comparison/search form while preserving returned text | normalization/persian.py, normalize_text | raw_text untouched; normalized_text plus versioned policy and configuration hash | Invalid normalization policy is a configuration error, not silent fallback |
| 12. Verification/retry | Assess confidence, compare attempts, retry bounded variants/backends, and persist history | pipeline.py _recognize_region, ocr/verification/engine.py | AttemptCandidate, VerificationOutcome, VerificationAttempt, flags | Low confidence/disagreement/tiny text/scale mismatch becomes review-required |
| 13. Quality status | Aggregate line/block review signals and metric hooks | pipeline.py _quality, quality/metrics.py | QualityAssessment and document warnings | Do not report CER/WER/table accuracy without references; processing status must be separate |
| 14. Canonical result | Serialize the evidence hierarchy | domain/models.py, Document.canonical_dict | Versioned Document JSON | Validation errors fail the result rather than publish malformed evidence |
| 15. Dataset export | Write deterministic views and integrity manifest | dataset/exporter.py | JSON, text, Markdown, page images, line crops, page manifests, labels, manifest | Explicit policy filters review evidence; stage writes atomically; existing incompatible export is rejected |

## Routing rules

### Native PDF pages

1. PdfReader inspects the embedded text layer.
2. If the reliability heuristic passes and no embedded image regions require OCR, the page is emitted as native text in PDF_POINT coordinates.
3. The native line stores native_pdf_text extraction metadata, normalization output, and VERIFIED status because no OCR uncertainty was introduced by the pipeline.
4. If the page has reliable native text plus image regions, native blocks are retained and only image regions are sent through OCR. The page is MIXED.
5. If the text layer is empty or unreliable, the page is SCANNED and is rasterized for OCR.

The reliability reason is retained in PageInput.native_text_reason. It is not sufficient to store only the chosen route.

### Raster images and scanned pages

Raster input is decoded through Pillow, bounded by configured pixel limits, and represented as one SOURCE_PIXEL page. OCR processing creates a separate rendered/derived artifact; source bytes remain immutable.

### Tiny text

The tiny-text path is bounded:

1. Detect a suspiciously small native line or receive a tiny-text hint from a layout/router.
2. Select tiny-text DPI, currently configured at 600 by default.
3. Crop to the region when geometry is available.
4. Apply safe named preprocessing variants and region scales up to the configured maximum.
5. Run OCR on each permitted attempt.
6. Compare normalized text and backend-specific confidence only within a compatible confidence scale.
7. Select only when policy allows; otherwise retain attempts and set tiny_text plus review flags.

The current implementation supports bounded region scaling, deterministic preprocessing profiles, per-step derived artifacts, and a Pillow quality analyzer. Quality metrics remain evidence for routing and verification, not ground truth. Tiny-text recovery returns a 450/600 DPI recommendation and persists bounded 2x/3x/4x variants; it never claims super-resolution recovered unavailable information.

### Region types

The stable taxonomy supports title, paragraph, text_line_group, printed_text, handwriting, table, form, formula, image, figure, caption, header, footer, page_number, sidebar, list, multi_column, tiny_text, and unknown. Route hints additionally distinguish printed_text, handwriting, table, form, formula, image, tiny_text, and unknown. Current routing is intentionally conservative:

- reliable native text becomes printed text;
- embedded PDF image regions become image OCR regions;
- OCR-required full pages become printed_text or tiny_text based on available signals;
- handwriting-only claims route only to HTR by default; an explicit printed-OCR fallback may preserve visible text while remaining review-required; table claims route only to the table adapter; forms/mixed regions may run printed OCR and HTR independently; unsupported capability remains reviewable and never becomes a fabricated handwriting result.

This prevents an unconfigured model from silently producing a false structural label.

## Provider invocation and adapter rules

Provider adapters receive bytes plus a typed region and processing metadata. They are responsible for:

- invoking their own SDK or executable safely;
- parsing provider output into OcrResult, LayoutRegion, or TableCell;
- reporting backend, model, model version, and confidence scale;
- preserving provider geometry and words when available;
- raising a typed unavailable/processing error when execution cannot occur.

Adapters must not:

- normalize raw text;
- select winners across attempts;
- convert a missing result into an empty confident string;
- compare confidence values from another provider;
- write directly to database tables;
- expose secrets or raw payloads in logs.

## Verification and retry sequence

The current verification policy uses:

1. A bounded candidate sequence, limited by max_attempts.
2. Confidence-scale inspection.
3. Candidate selection only by confidence when all candidates share a scale.
4. First usable candidate selection when scales differ, with confidence_scale_mismatch.
5. Normalized text comparison for disagreement.
6. Low-confidence, disagreement, tiny-text, and scale-mismatch flags.
7. HUMAN_REVIEW_REQUIRED whenever flags are present.
8. VERIFIED only when the configured verified threshold and consensus policy pass.
9. ACCEPTED when the result is usable but does not meet the verified threshold.
10. An ordered VerificationAttempt record for every candidate, including difference_from_previous and reason.

A later implementation may add calibrated cross-backend comparison, but calibration must be explicit and versioned. It must not be inferred from numeric magnitude.

## Provenance and geometry path

Every derived line follows this provenance chain:

~~~text
source document checksum
 -> source artifact URI
 -> source page number and dimensions
 -> render URI and render DPI (if rasterized)
 -> crop/region coordinates and scale
 -> preprocessing variant
 -> provider/model/version
 -> candidate attempt
 -> selected line and verification history
 -> canonical export label/crop
~~~

Coordinate handling rules:

- Native PDF extraction stays in PDF_POINT coordinates.
- Raster source images use SOURCE_PIXEL coordinates.
- OCR over rendered pages uses RENDERED_PIXEL coordinates.
- A crop may use a derived crop URI, but its parent page and coordinate space remain recorded.
- Geometry is clipped and validated before a provider call.
- Line crops are generated only when their coordinates match the stored rendered artifact space.
- A URI without a checksum and coordinate context is not sufficient provenance.

## Canonical result and export determinism

The canonical Document is the only source for dataset views. Exporters must not reinterpret backend output or apply a second normalization policy. The active `NormalizationConfig` is recorded on the document and in the export manifest, while `raw_text` remains the immutable evidence field.

Determinism is bound by:

- source checksum;
- schema version;
- pipeline version;
- configuration hash;
- selected backend/model/version inventory;
- stable page/block/line/word identifiers and reading order;
- deterministic JSON key ordering and UTF-8 encoding;
- deterministic crop encoding and manifest hashes.

Timestamps may be retained for audit metadata but must not be the only input to processing identity or export target naming.

## Separate operational and extraction states

### Processing status

Implemented result lifecycle:

~~~text
pending -> processing -> completed
                    -> completed_with_warnings
                    -> failed
~~~

Processing status belongs to a job or processing record. The compatibility synchronous API returns a Document directly; the asynchronous Phase 9 API persists a separate JobRecord.

### Extraction/review status

Line and verification status:

~~~text
accepted
verified
uncertain
human_review_required
failed
~~~

These values describe evidence quality/certainty. They must not be used as queue state, retry state, or HTTP job state.

Examples:

- processing = completed_with_warnings; line status = human_review_required because attempts disagree.
- processing = completed; line status = accepted because extraction succeeded but did not meet verified threshold.
- processing = failed; no canonical OCR text is published for the failed region.
- processing = completed; page status may still contain missing optional table/HTR capability warnings if the configured policy allows partial completion.

## Failure and review behavior

The pipeline is fail-closed at evidence boundaries:

- Unsupported or invalid source: reject before processing.
- Missing parser/decoder: return a typed backend-unavailable error.
- Missing OCR backend: retain an empty evidence block, warning, and review flag; do not create text.
- Invalid or out-of-bounds geometry: reject the candidate/region and record an invalid-geometry warning.
- Low confidence: preserve the candidate and trigger retry/review.
- Attempt disagreement: preserve every attempt and require review.
- Confidence scales differ: preserve attempts and require calibration/review.
- Normalization failure: fail the normalization step; never replace raw text with a guessed value.
- Export failure: do not publish a partial manifest as a complete dataset.
- Unexpected API failure: return a safe error envelope with request ID; keep internal details in structured logs.

## Synchronous and asynchronous execution

The compatibility path remains synchronous:

~~~text
HTTP upload or CLI path
 -> DocumentPipeline.process_path
 -> canonical Document response
 -> optional DatasetExporter
~~~

The Phase 9 asynchronous path is:

~~~text
API
 -> validate and fingerprint upload
 -> JobRepository.save queued JobRecord
 -> bounded local executor
 -> worker invokes the same DocumentPipeline
 -> JobRepository.save terminal state
 -> DocumentRepository.save canonical evidence
 -> review/export consumers read canonical evidence
~~~

The worker must not duplicate native extraction, routing, OCR, or verification logic. Queue retry policy must be distinct from OCR attempt history: a job retry is an operational retry, while a VerificationAttempt is an evidence-level retry.

## Quality metrics

The existing metric hooks in quality/metrics.py cover:

- CER and WER when reference text exists;
- normalized candidate difference and OCR disagreement;
- mean confidence within a single backend scale;
- box IoU and line detection precision/recall;
- reading-order accuracy;
- exact-match accuracy for table/field-like sequences;
- percentage sent to review;
- tiny-text recovery rate.

Metrics that require labels, real layout/HTR/table models, representative benchmarks, throughput infrastructure, or calibrated confidence are NOT_RUN until their inputs and runtimes are supplied. A metric hook is not an accuracy claim.

## Test coverage for this flow

Current evidence is distributed across:

- tests/ingestion/test_source.py and test_policy.py for source and resource boundaries;
- tests/integration/test_pdf_native_first.py for native, scanned, and mixed PDF routes;
- tests/integration/test_pipeline.py for provenance, normalization, verification history, and missing backends;
- tests/integration/test_retry_pipeline.py for low-confidence retries;
- tests/imaging/test_preprocess.py for bounded scaling and geometry mapping;
- tests/ocr/test_routing_verification.py for reading order, confidence scales, and disagreement;
- tests/layout/* and tests/integration/test_layout_pipeline.py for provider-neutral layout contracts, geometry normalization, deterministic heuristic regions, RTL/LTR order, and OCR handoff;
- tests/normalization/test_persian.py for mixed Persian/English text and digit policy;
- tests/domain/test_models.py for geometry/page/model invariants;
- tests/storage/test_artifacts.py, tests/dataset/test_exporter.py, and tests/dataset/test_phase8_export.py for immutable artifacts, policy filtering, provenance, and deterministic output;
- tests/quality/test_metrics.py for quality hooks;
- tests/api and tests/security for upload, auth, request ID, safe errors, and limits.
- tests/ocr/test_contracts.py, tests/ocr/test_backends.py, tests/ocr/test_region_router.py, tests/domain/test_phase6_models.py, and tests/integration/test_ocr_routing_pipeline.py for Phase 6 evidence contracts, capability routing, mixed documents, structured tables, candidate retention, line crops, and backend failures.

## Remaining implementation backlog after Phase 6

1. [COMPLETED] Extract named PdfExtractor and PageRenderer protocols without changing current reader behavior.
2. [COMPLETED] Add ProcessingStatus to the canonical result and the Phase 9 separate JobRecord lifecycle; shared queue persistence remains future work.
3. [COMPLETED] Add typed ProcessingWarning and ProcessingManifest models while preserving legacy serialized compatibility.
4. [COMPLETED] Add the QualityEvaluator port around metric aggregation and reference datasets.
5. [COMPLETED] Add an explicit ImageQualityAnalyzer contract for blur/skew/contrast/illumination/capture signals.
6. [COMPLETED] Wire LayoutBackend through LayoutAnalysisService with deterministic geometry/order contracts and explicit optional model adapter selection.
7. [COMPLETED] Add provider-neutral OCR/HTR/table result contracts, route-specific execution, structured table cells, candidate retention, and explicit fail-closed capability behavior.
8. Deploy and benchmark licensed HTR and table-cell model adapters behind the existing ports before enabling them by default.
9. Split DocumentPipeline into small application services after contract tests protect the current ordering.
10. Add PostgreSQL/object-storage/queue adapters only when deployment scale, retention, review workflows, or throughput justify them.


## Phase 3 implementation update

The first four flow stages are now backed by `DocumentIngestionService`: source signature/size validation, immutable source persistence, page-specific PDF inspection, native text reliability assessment, bounded rendering, EXIF correction, and typed page/artifact output. A native-only page is not rasterized by ingestion; an unreliable, scanned, mixed-image, or standalone raster page receives a bounded render artifact for later OCR. Tiny native lines are flagged without mutating or discarding their native text.

## Phase 5 implementation update

Layout processing is now a first-class pre-OCR stage. Native reliable pages
are converted into ordered layout evidence from their PDF text lines; OCR-needed
pages are rendered once at the selected DPI, analyzed by the configured layout
adapter, and routed using normalized region hints. Geometry is clipped and
validated before provider invocation, provider polygons are preserved, and
invalid regions produce scoped warnings rather than malformed OCR crops.
Headers, footers, page numbers, sidebars, body columns, and tables receive
stable numeric order. RTL and mixed-script pages change spatial traversal only;
raw OCR/native strings remain byte-for-byte/Unicode-preserved. The default
Pillow detector is deterministic and conservative, while PP-Structure remains
an optional real adapter with explicit availability reporting.

## Phase 6 implementation update

OCR-required regions now pass through `RegionRouter` after layout. Printed,
handwriting, table, and mixed-form routes invoke separate injected adapter
sets. OCR/HTR line candidates retain raw and normalized forms, backend-specific
confidence scales, runtime metadata, warnings, verification attempts, and
source-derived line crop references. Table regions remain structured through
`TableResult` and `BlockResult.table_cells`; cells retain row/column indexes
and are not flattened into canonical text. Missing HTR/table runtimes produce
review-required warnings; any explicit printed fallback is marked as OCR
fallback evidence and never treated as HTR output.

## Phase 7 implementation update

The verification stage is now an explicit quality gate:

~~~text
first candidate
 -> score using backend-specific policy
 -> alternate preprocessing within the configured budget
 -> high-DPI PDF rerender/crop when the last result remains weak
 -> alternate scale/backend evidence
 -> Unicode-aware consensus and disagreement analysis
 -> accepted / verified / uncertain / human_review_required / failed
~~~

Candidate comparison uses raw-preserving NFC views, configurable Persian and
Arabic normalization, edit/CER-like distance, and explicit digit,
punctuation, and whitespace difference signals. Mixed RTL/LTR strings are
compared in document order; characters are never reversed. Provider numeric
confidence is used against its own backend threshold and is not ranked across
providers. Clean exact consensus can verify low-confidence passes when policy
allows it; malformed, empty, unresolved, or weak evidence remains reviewable.

The retry budget is finite and persisted in `VerificationRecord` entries. The
pipeline stores selected candidate identity, all raw candidates, reason codes,
confidence scales, DPI/region scale, preprocessing variant, and candidate
differences. Review-needed lines receive an immutable JSON evidence package and
highlighted page overlay. If storage fails, the line remains review-required
and a scoped processing warning records the missing artifact; text is never
silently discarded or repaired.

## Phase 8 implementation update

Normalization now supports explicit Unicode form, character-variant, digit,
whitespace, line-break, zero-width, tatweel, and edge-trimming policies. The
digit pass protects URLs, emails, dates, serials, and mixed Latin/number
identifiers. Settings environment overrides are validated and included in the
configuration hash; the selected policy is serialized in `DocumentResult` and
the export manifest. No string is reversed for RTL presentation.

`DatasetExporter` now accepts the provider-neutral `ArtifactStore` protocol and
has three explicit policies: `strict_verified_only`, `accepted_verified` (the
default), and `all_with_status`. Canonical JSON always retains all evidence.
Derived text/Markdown/crop views filter by policy, and all-with-status crops
are partitioned by verification state. Each page receives a page manifest and
each line label retains the page bbox, clamped rendered-pixel crop bbox, page
dimensions, source/rendered artifact references, raw/normalized values, and
verification history. The manifest records source/configuration/model/pipeline
provenance, processing time, status counts, warnings, normalization policy,
and sorted artifact checksums.

Phase 8 tests cover protected mixed-script normalization, environment/hash
provenance, policy filtering, explicit review partitioning, crop mapping,
manifest inventory, and deterministic export reuse. Model-level OCR accuracy,
confidence calibration, and benchmark metrics remain unclaimed without
deployed model runtimes and labeled references.

## Phase 9 implementation update

`DocumentJobService` now validates the upload a second time at the application
boundary, computes deterministic source/configuration/mode fingerprints, keeps
immutable submitted bytes in `ArtifactStore`, persists `JobRecord` and
canonical documents through replaceable repository ports, and invokes the
existing pipeline through a bounded executor. Optional pipeline callbacks
persist page/stage progress without changing canonical OCR behavior.

FastAPI exposes asynchronous submission and protected job/document/manifest,
page-image, and export retrieval routes. The local adapter uses atomic JSON
metadata files under the artifact root; it is a single-node persistence
adapter, not a hidden distributed queue. The legacy synchronous endpoint is
retained for compatibility. API errors include stable codes and request/job/
document correlation without returning stack traces or document contents.


