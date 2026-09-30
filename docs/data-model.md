# Canonical Data Model and Evidence Contract

## Document metadata

| Field | Value |
|---|---|
| Project | High-Accuracy Universal OCR & Document Dataset Pipeline |
| Schema baseline | 1.0.0 |
| Code source | src/ocr_platform/domain/models.py |
| Scope | Canonical evidence model, provenance, certainty, serialization, and ingestion evidence |
| Preservation rule | Raw source bytes and raw OCR/native text are evidence and are never silently replaced |

## Model hierarchy

The canonical result is a typed hierarchy:

~~~text
Document
  -> Page
      -> Block
          -> Line
              -> Word (optional)
          -> TableCell (for structured table blocks)
~~~

The hierarchy is intentionally richer than plain text. It preserves enough geometry and history to reconstruct a page, generate crops and labels, compare attempts, and send uncertain evidence to human review.

## Canonical entities

### Document

Current executable model: ocr_platform.domain.Document.

| Field | Type/meaning | Required rule |
|---|---|---|
| id | Stable document identifier | Non-empty; derived from caller identity or source checksum policy |
| schema_version | Canonical schema version | Required and versioned |
| pipeline_version | Processing implementation version | Required |
| source | DocumentSource | Immutable source metadata and checksum |
| configuration_hash | SHA-256 of effective processing configuration | Required; binds output to limits and policy |
| normalization_policy | Versioned normalization payload | Required for new Phase 8 results; makes normalized text reproducible |
| processing_checksum | SHA-256 of source/config/backend selection | Required; supports deterministic export identity |
| processing_started_at | UTC timestamp | Required |
| processing_finished_at | UTC timestamp | Optional until processing completes |
| pages | Ordered Page list | Page numbers must be contiguous starting at 1 |
| processing_status | ProcessingStatus | Operational job lifecycle; independent from extraction certainty |
| quality | QualityAssessment | Optional until quality assessment is available |
| processing_warnings | list[ProcessingWarning] | Typed scoped warnings; legacy warnings remain compatibility-only |

`processing_status` is carried separately from the document extraction/review assessment. The current `status` field must not be interpreted as job state by workers or dashboards; asynchronous job state belongs to `JobRecord`.

### DocumentSource

| Field | Type/meaning |
|---|---|
| filename | Original metadata filename, validated for control characters and length |
| content_type | Server-detected or validated content type |
| byte_size | Source byte count |
| checksum_sha256 | Lowercase SHA-256 of source bytes |
| source_uri | Private immutable source artifact URI |
| source_created_at | Optional source timestamp |
| metadata | Safe source metadata map |

The source URI is an indirection, not a public URL. Access control belongs to the storage/application boundary.

### Page

| Field | Type/meaning | Required rule |
|---|---|---|
| page_number | 1-based page number | Positive and contiguous within Document |
| width, height | Page dimensions in coordinate units | Positive |
| coordinate_space | PDF_POINT, SOURCE_PIXEL, or RENDERED_PIXEL | Required; dimensions use the same space |
| page_type | Native text, scanned, image, mixed, or unknown | Required |
| source_uri | Source artifact reference | Required |
| rendered_uri | Derived page-image artifact | Optional for native-only pages |
| source_dpi | Source image DPI when known | Optional |
| blocks | Ordered block list | Block provenance must point to this page |
| native_text_reliable | Native PDF layer decision | Required boolean |
| native_text_reason | Decision evidence/fallback reason | Recommended when a PDF is inspected |
| page_flags | Page-level uncertainty/review flags | Default empty |
| verification_status | Aggregate evidence certainty for the page | Propagated from blocks; default accepted |
| needs_review | Aggregate human-review gate | True when page or child evidence requires review |
| uncertainty_flags / reason_codes | Aggregate review evidence | Stable, deduplicated child explanations |

A native page can have no rendered URI. A mixed page may retain native blocks and have a rendered URI for OCR-routed image regions.

### Block

| Field | Type/meaning |
|---|---|
| id | Stable page-local or document-scoped block identifier |
| block_type | Title, paragraph, text-line group, printed text, handwriting, table, form, formula, image/figure, caption, header, footer, page number, sidebar, list, multi-column, tiny text, or unknown |
| bbox | Axis-aligned bounding box in the page coordinate space |
| polygon | Optional non-rectangular region geometry |
| reading_order | Spatial/document order among blocks |
| confidence | Provider-specific or layout confidence; null when not available |
| source | Document/page/URI/coordinate provenance |
| lines | Line records belonging to this block |
| table_cells | Structured cell records for table blocks; never flattened as canonical text |
| table_cells | Structured cell records for table blocks; never flattened as canonical text |
| needs_review | Block review indicator, propagated from child evidence |
| uncertainty_flags | Block uncertainty/review reasons, including propagated child flags |

Block type is a classification claim. When evidence is insufficient, use unknown and surface the reason; do not silently default to printed text.

### Layout evidence records

The provider-neutral layout boundary in `src/ocr_platform/layout/` uses these
records before OCR text exists:

| Record | Purpose |
|---|---|
| `LayoutRegion` | Region bbox/polygon, stable block taxonomy, confidence, route hint, text-type/tiny-text hints, optional line geometry, and review flags. |
| `LayoutLine` | Pre-OCR line bbox/polygon and line-level uncertainty/order metadata. |
| `LayoutResult` | Backend/model/version, page coordinate space, ordered regions, reading direction, column count, and warnings. |
| `LayoutWarning` | Scoped invalid-geometry, resource, or provider warning that must remain auditable. |
| `RegionRouteHint` | Stable next-stage hint for printed text, handwriting, table, form, formula, image, tiny text, or unknown. |

Layout coordinates use the top-left origin of the referenced rendered page or
PDF-point page and are clipped to the known page dimensions when valid. A
provider polygon is retained in `provider_polygon`; the normalized polygon and
convenience bbox are separate evidence fields. The layout service assigns
numeric `reading_order` values using spatial relationships. Persian/Arabic
direction changes horizontal spatial ordering only and never reverses raw text.

### Line

Current executable model: ocr_platform.domain.Line.

| Field | Type/meaning | Required rule |
|---|---|---|
| id | Stable line identifier | Non-empty |
| raw_text | Exact native/OCR/HTR text returned by the selected attempt | Never normalized in place |
| normalized_text | Configurable normalized representation | Can differ from raw_text |
| bbox | Axis-aligned line geometry | Ordered, non-negative coordinates |
| polygon | Optional line polygon | Preserve when supplied |
| confidence | Backend-specific confidence or null | Never compare across scales without calibration |
| language | BCP-47-like language code or undetermined | Default is undetermined |
| script | Script label | Default is Unknown |
| text_type | Printed, handwritten, mixed, or unknown | Classification may be uncertain |
| reading_order | Line order within its block/page | Non-negative |
| tiny_text | Tiny-text routing signal | Adds tiny-text uncertainty flag |
| needs_review | Explicit human-review gate | Synchronized with uncertainty flags |
| source | Document/page/crop/coordinate provenance | Required |
| extraction | Method/backend/model/version/DPI/scale/preprocessing | Required |
| verification_status | accepted, verified, uncertain, human_review_required, or failed | Extraction certainty only |
| uncertainty_flags | Low confidence, disagreement, tiny text, missing backend, unreliable native text, invalid geometry, language uncertainty, confidence-scale mismatch, manual review | Default empty |
| verification_history | All bounded attempts | Preserve, do not collapse |
| candidates | All bounded backend/preprocessing candidates retained for verification | Preserve raw evidence |
| words | Optional word geometry and confidence | Preserve when backend supplies it |
| candidates | All bounded backend/preprocessing candidates retained for verification | Preserve raw evidence |

The current Pydantic validators enforce that `needs_review=true` cannot remain
paired with `accepted` or `verified`; the status is promoted to
`human_review_required` while an existing `failed` status is preserved. Review
and blocking evidence propagate through `BlockResult`, `PageResult`, and
`DocumentResult`, so a parent cannot claim a cleaner certainty state than a
review-required child. Low-confidence/tiny-text flags may remain on a verified
record only when the verification reason explicitly records independent
consensus; benign high-confidence retry stability remains auditable without
automatically forcing human review.

### Word

| Field | Type/meaning |
|---|---|
| id | Stable word identifier |
| raw_text | Backend/native word text |
| normalized_text | Normalized word text |
| bbox | Word geometry in the parent line/page coordinate space |
| polygon | Optional word polygon |
| confidence | Backend-specific word confidence |
| reading_order | Order within the line |

Words are optional because some backends expose only line-level results. Absence of words must not imply absence of line provenance.

## Geometry and coordinate spaces

### BoundingBox

Current model fields are x0, y0, x1, y1. Coordinates must be non-negative and ordered so x1 is not less than x0 and y1 is not less than y0. The model serializes as a four-value list through as_list().

A bounding box is meaningful only with its coordinate space and page dimensions. Current schema validation enforces ordering and non-negativity; the pipeline clips and maps rendered regions, while future schema validation may additionally enforce page bounds where the parent page is available.

### Polygon

A polygon is an ordered list of non-negative PolygonPoint values. It is optional and preserves rotated or irregular geometry when a backend supplies it. The raw polygon must not be reconstructed from an axis-aligned box when that would discard provider evidence.

### Coordinate-space rules

| Coordinate space | Typical producer | Meaning |
|---|---|---|
| PDF_POINT | PyMuPDF native extraction | PDF page points; native lines remain in this space |
| SOURCE_PIXEL | Raster image reader | Original decoded image pixels |
| RENDERED_PIXEL | PDF renderer/preprocessing/OCR | Pixels of the retained rendered page image |

Geometry mapping must be recorded in extraction metadata and be deterministic. A crop may be stored in a derived artifact URI, but its coordinates remain traceable to the parent page through the line source and coordinate space.

## Extraction metadata

Current executable model: ocr_platform.domain.ExtractionMetadata.

| Field | Meaning |
|---|---|
| method | native_pdf_text, ocr, handwriting_recognition, layout, table_extraction, or manual_review |
| backend | Adapter identity |
| model | Model family/name |
| model_version | Deployed model or adapter version |
| dpi | Render/recognition DPI, when applicable |
| region_scale | Region scale factor |
| preprocess_variant | Named deterministic preprocessing variant |
| confidence_scale | Backend-specific score semantics |
| configuration_hash | Effective processing configuration hash |
| runtime_metadata | Redacted provider/runtime key-value evidence such as device, executable, language, or model identifier |
| warnings | Provider warnings retained with the extraction evidence |
| runtime_metadata | Redacted provider/runtime key-value evidence such as device, executable, language, or model identifier |
| warnings | Provider warnings retained with the extraction evidence |

The metadata is attached to each line and verification attempt so a selected line can be audited independently of the current process configuration.

## OCR candidates and verification

### OCRCandidate

The target canonical name is OCRCandidate. The current implementation uses ocr.verification.AttemptCandidate and constructs a domain VerificationAttempt for persistence.

Target fields:

| Field | Meaning |
|---|---|
| raw_text | Candidate text exactly as returned |
| normalized_text | Candidate normalized under the active policy |
| confidence | Backend score, or null |
| extraction | Backend/model/version/preprocessing metadata |
| reason | Why this attempt was run |
| tiny_text | Whether the candidate came from the tiny-text path |
| candidate_id | Stable attempt identifier when persisted |

Candidate selection must preserve all candidates, not just the winner. A candidate from a different confidence scale cannot win merely because its numeric value is larger.

### TableCell

`TableCellResult` is the canonical representation of structured table output.
It contains `row`, `column`, raw and normalized text, bbox/polygon geometry,
confidence, language/script, text type, reading order, provenance, extraction
metadata, uncertainty flags, and raw `OCRCandidate` alternatives. A table
block may have no line records while still containing valid cell records. A
missing table backend creates a review-required block rather than an invented
cell or flattened paragraph.

### VerificationResult

Current executable output: ocr.verification.VerificationOutcome.

Target fields:

| Field | Meaning |
|---|---|
| selected | Selected candidate, or null when no usable candidate exists |
| processing_status | ProcessingStatus | Operational job lifecycle; independent from extraction certainty |
| flags | Deduplicated uncertainty/review flags |
| attempts | Ordered VerificationAttempt records |
| reason | Stable decision reason such as consensus_verified, disagreement, low_confidence, or missing_backend |

The result is line-scoped in the canonical model. Page/document quality is aggregated from line/block results without hiding individual flags.

### Verification status

~~~text
accepted
verified
uncertain
human_review_required
failed
~~~

Accepted means a candidate was usable under the configured policy. Verified means the configured verification policy found sufficient confidence/consensus. Uncertain and human_review_required are explicit non-ground-truth states. Failed means no valid extraction result was produced for that evidence path; it is not permission to fabricate a replacement.

## Processing lifecycle status

Processing lifecycle is deliberately separate from VerificationStatus.

Target job status:

~~~text
pending
processing
completed
completed_with_warnings
failed
~~~

Meaning:

- pending: accepted for processing but not started
- processing: work is active
- completed: processing finished without processing warnings that affect the job result
- completed_with_warnings: processing finished but warnings, missing optional capability, or review-required evidence exist
- failed: processing could not produce a canonical result

A completed_with_warnings job may contain verified lines and review-required lines. A failed job must not publish a plausible-looking OCR result as if it were complete.

## ProcessingWarning

ProcessingWarning is implemented as a typed, scoped Pydantic model. The legacy `warnings: list[str]` field remains only for serialized compatibility; new ingestion warnings use the typed field:

| Field | Meaning |
|---|---|
| code | Stable machine-readable warning code |
| severity | info, warning, or error |
| stage | Pipeline stage that emitted it |
| message | Safe human-readable explanation |
| document_id/page_number/block_id/line_id | Optional scope |
| retryable | Whether a rerun may resolve it |
| created_at | UTC warning timestamp |
| details | Redacted structured context |

Examples include native_text_unreliable, missing_ocr_backend, tiny_text_unverified, confidence_scale_mismatch, unsupported_region_type, and export_artifact_missing. Warning codes must be closed and testable; free-form details must never contain credentials or raw sensitive payloads.

## ProcessingManifest

ProcessingManifest is implemented as a typed, deterministic Pydantic model. DatasetExporter remains responsible for the export-specific manifest view:

Its explicit fields include:

- manifest_version
- document_id
- source_filename, source_content_type, source_byte_size, and source SHA-256
- source_checksum
- configuration_hash
- processing_checksum
- pipeline_version
- schema_version
- exporter_version
- normalization policy
- page and processing-time metadata
- OCR backend/model/version/confidence-scale inventory
- accepted/verified/review/failed and exported-item counts
- warnings and table-cell counts
- ordered artifact entries
- selected export formats
- explicit export policy: strict verified-only, accepted plus verified, or all with status
- generated-at policy (deterministic export identity must not depend on an uncontrolled wall-clock value)
- optional source/model/backend inventory

The manifest is an audit index. It must not be used to replace the canonical document or source evidence.

## Document and page type enums

Current closed enums:

| Enum | Values |
|---|---|
| CoordinateSpace | source_pixel, rendered_pixel, pdf_point |
| PageType | native_text, scanned, image, mixed, unknown |
| BlockType | printed_text, handwriting, table, form, formula, image, header, footer, multi_column, tiny_text, unknown |
| TextType | printed, handwritten, mixed, unknown |
| ExtractionMethod | native_pdf_text, ocr, handwriting_recognition, layout, table_extraction, manual_review |
| VerificationStatus | accepted, verified, uncertain, human_review_required, failed |

The implementation must reject unknown enum values rather than silently coercing them.

## Persian/Farsi and mixed-direction contract

1. Preserve Unicode exactly in raw_text.
2. Normalize Arabic/Persian character variants only in normalized_text.
3. Apply digit conversion only through an explicit NormalizationConfig and record its version/policy in the processing configuration.
4. Do not reverse strings to make the UI appear RTL.
5. Determine reading order spatially from geometry and document direction; the existing router reverses horizontal ordering for RTL rows but does not reverse characters.
6. Keep URLs, emails, identifiers, serial numbers, dates, punctuation, and Latin substrings intact unless a tested normalization policy explicitly changes them.
7. Preserve source coordinates in their declared coordinate space; visual direction is not a coordinate transformation.
8. Mixed Persian-English fixtures must test both raw and normalized values and ensure no bidi corruption.

## Invariants and integrity rules

- Every document has a source checksum, configuration hash, processing checksum, and schema/pipeline version.
- Page numbers are positive and contiguous starting at 1.
- Every block belongs to the page named by its provenance.
- Every line has document/page provenance and extraction metadata.
- A source URI is private and immutable; derived page/crop artifacts have separate URIs.
- Raw source bytes are never overwritten by derived images.
- raw_text is never overwritten by normalization, verification, or review.
- normalized_text is reproducible from raw_text plus a named/versioned normalization policy.
- A missing confidence is represented as null, not zero.
- Confidence values remain associated with their backend and confidence scale.
- Uncertainty flags are retained even when a candidate is selected.
- Review decisions append audit data and do not mutate raw OCR.
- Export files are reproducible from the canonical document, artifact bytes, and version/configuration hashes.
- Derived dataset labels are policy-filtered; the default accepted/verified view excludes uncertain, human-review-required, and failed records.
- An all-with-status export partitions crops by verification state and retains the state in text/Markdown views; uncertain evidence is never silently mixed with accepted labels.
- Processing warnings and model unavailability are visible in canonical/exported output.
- No provider adapter may emit fabricated text when the provider is unavailable.

## Serialization example

The following is illustrative and intentionally keeps raw and normalized text separate:

~~~json
{
  "id": "line-001",
  "raw_text": "شماره قرارداد ١٢٣٤٥",
  "normalized_text": "شماره قرارداد ۱۲۳۴۵",
  "bbox": [120, 340, 1820, 430],
  "polygon": null,
  "confidence": 0.97,
  "language": "fa",
  "script": "Arabic",
  "text_type": "printed",
  "reading_order": 12,
  "tiny_text": false,
  "needs_review": false,
  "source": {
    "document_id": "doc-x",
    "page_number": 1,
    "crop_uri": null,
    "coordinate_space": "rendered_pixel"
  },
  "extraction": {
    "method": "ocr",
    "backend": "backend-name",
    "model": "model-name",
    "model_version": "version",
    "dpi": 450,
    "region_scale": 2,
    "preprocess_variant": "deskew_denoise",
    "confidence_scale": "backend-specific"
  },
  "verification_status": "verified",
  "uncertainty_flags": [],
  "verification_history": []
}
~~~

## Current-to-target mapping

| Requested contract | Current repository shape | Phase 1 decision |
|---|---|---|
| Document/Page/Block/Line/Word | Pydantic models in domain/models.py | Current and canonical |
| BoundingBox/Polygon | BoundingBox and PolygonPoint | Current and canonical |
| OCRCandidate | OCRCandidate Pydantic model | Current canonical candidate record for backend/preprocessing verification |
| ExtractionMetadata | Pydantic model | Current and canonical |
| VerificationResult | VerificationStatus plus VerificationRecord | Current canonical certainty and retry-history representation |
| ProcessingWarning | Typed ProcessingWarning Pydantic model | Current canonical scoped warning; legacy strings remain compatibility-only |
| ProcessingManifest | Typed ProcessingManifest Pydantic model | Current canonical deterministic manifest metadata |
| ProcessingStatus | ProcessingStatus enum on DocumentResult | Implemented operational lifecycle; do not conflate with VerificationStatus |
| PdfExtractor/PageRenderer | Protocols in ingestion/ports.py implemented by PdfReader | Provider-neutral extraction/rendering boundaries |
| QualityEvaluator/ArtifactStore | Metric functions / ArtifactStore protocol plus LocalArtifactStore | ArtifactStore and QualityEvaluator protocols implemented; evaluator aggregation remains future work |

## Tests and evidence

Current tests already validate the core model contract:

- tests/domain/test_models.py validates raw/normalized separation, review promotion, contiguous pages, and inverted bounding boxes.
- tests/normalization/test_persian.py validates Persian variants, mixed text, raw preservation, and explicit digit policies.
- tests/ocr/test_routing_verification.py validates RTL spatial order, confidence-scale mismatch, and disagreement review.
- tests/layout/test_contracts.py, test_heuristic.py, test_provider_mapping.py, test_reading_order.py, and tests/integration/test_layout_pipeline.py validate layout contracts, provider-label mapping, geometry clipping, conservative detection, RTL/LTR ordering, and OCR handoff.
- tests/integration/test_pipeline.py validates provenance, normalization, verification history, and missing-backend review.
- tests/integration/test_pdf_native_first.py validates reliable native text, scanned pages, and mixed native/image pages.
- tests/quality/test_metrics.py validates metric hooks and input bounds.
- tests/storage/test_artifacts.py and tests/dataset/test_exporter.py validate immutable storage and deterministic exports.
- tests/dataset/test_phase8_export.py validates policy filtering, review partitioning, page manifests, crop geometry mapping, raw/normalized labels, and provenance counts.

Serialization, geometry, Persian Unicode, raw-vs-normalized, status, warning scoping, deterministic manifest, and ingestion artifact tests are covered before changing the public schema version.


## Phase 3 ingestion records

The ingestion layer uses typed reader-neutral records in `src/ocr_platform/ingestion/models.py`:

| Record | Purpose |
|---|---|
| `NativeTextLine` | Exact native PDF line text, PDF-point bbox, and PDF block/line order indexes |
| `NativeTextEvidence` | Character count, line count, coverage, plausibility, suspicious ratio, reliability, and reason |
| `PageQualityMetadata` | Pixel, luminance/contrast, text/image coverage, EXIF orientation, and quality flags |
| `ArtifactReference` | URI, SHA-256, byte size, media type, kind, and optional rendered dimensions/DPI |
| `PageInput` | Page number, page ID, dimensions, coordinate space, page type, rotation, native lines, image regions, quality, and OCR route hint |
| `IngestionResult` | Document/source metadata, source artifact, ordered pages, typed warnings, and `ProcessingStatus` |

PDF native line coordinates remain in `pdf_point` space and raster source coordinates remain in `source_pixel` space. Rendered page artifacts record their actual pixel dimensions and DPI. A downstream OCR line must retain the page number, coordinate space, source/render URI, and extraction metadata when it is materialized into the canonical `LineResult` hierarchy.

`ProcessingStatus` (`pending`, `processing`, `completed`, `completed_with_warnings`, `failed`) is operational state. `VerificationStatus` (`accepted`, `verified`, `uncertain`, `human_review_required`, `failed`) is evidence certainty. They are intentionally independent.

## Phase 4 image quality and transformation records

`PageQualityMetadata` now carries optional brightness/mean luminance, contrast,
sharpness, blur score, skew angle, perspective-distortion indicator,
background variation, estimated text scale, compression-artifact score, and
quality flags. These values are deterministic hints and must not be treated as
OCR confidence or as calibrated scores across engines.

The artifact-aware imaging boundary adds the following records:

| Record | Purpose |
|---|---|
| `ImageQualityMetrics` | Bounded quality signals for a source/rendered image. |
| `CoordinateMapping` | Homogeneous output-to-source and source-to-page mapping for derived geometry. |
| `ImageArtifact` | URI, checksum, dimensions, media type, DPI, and region scale for a preprocessing input/output. |
| `TransformationMetadata` | Operation name, normalized parameters, input artifact, output artifact, cumulative mapping, and warnings. |
| `PreprocessingResult` | Final artifact, ordered transformation history, input/output quality, profile, mapping, and manifest URI. |
| `TinyTextDecision` | Reasons, recommended DPI, bounded regional scales, and explicit verification requirement. |

Each transformation is persisted under the page's `derived/` directory. A
transformation record is incomplete without both artifact references and its
mapping. The mapping uses top-left pixel coordinates for rendered/derived
images and can map to PDF points when a page reference size is supplied.

## Phase 7 verification evidence

The canonical evidence contract now distinguishes three layers of OCR text:

1. `raw_text` is the exact backend/native output and is never modified by
   verification or normalization.
2. `normalized_text` is the configurable comparison/export view produced by
   the Persian/Arabic normalization policy.
3. `OCRCandidate` and `VerificationRecord` retain every bounded attempt,
   backend/model/version, confidence scale, preprocessing variant, DPI,
   region scale, raw/normalized values, candidate ID, and reason codes.

`VerificationStatus` remains separate from `ProcessingStatus`. Candidate and
line decisions are one of `accepted`, `verified`, `uncertain`,
`human_review_required`, or `failed`; job execution remains
`pending`, `processing`, `completed`, `completed_with_warnings`, or `failed`.
`selected_candidate_id`, `reason_codes`, `verification_history`, and
`review_artifact_uri` make the decision auditable in canonical JSON.

Reason codes include low primary confidence, backend or normalized
disagreement, digit/punctuation/whitespace differences, tiny text, malformed
or empty output, language/script mismatch, explicit-format mismatch, low image
quality, confidence-scale mismatch, insufficient evidence, retry exhaustion,
and consensus across variants/backends.

Confidence is backend-specific. A score is evaluated against the configured
threshold for its backend and is comparable for selection only within the same
backend and declared scale. Agreement across providers can verify clean text
without selecting the numerically largest provider score. All other candidates
remain in `candidates`; no correction step replaces raw OCR.

For every review-needed line, the artifact store may contain a deterministic
page-scoped JSON package and highlighted PNG overlay under
`pages/page_NNNN/reviews/`. The package links the source page, rendered page,
line crop, coordinate space, bbox/polygon, selected candidate, alternatives,
confidence/extraction metadata, flags, reason codes, and history. Storage
collisions are immutable: identical bytes are reused and incompatible bytes
produce a scoped warning.

The dataset crop labels include these same audit fields so line crops are
usable as training evidence without losing uncertainty context.

