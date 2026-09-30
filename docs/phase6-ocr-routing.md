# Phase 6 — OCR Routing and Structured Recognition

## Status

Phase 6 is implemented in the synchronous modular-monolith pipeline. The
implementation adds provider-neutral execution paths for printed OCR,
handwriting recognition, and table extraction while preserving raw evidence,
page coordinates, backend-specific confidence semantics, and verification
history.

## Implemented boundaries

| Capability | Contract | Current runtime behavior |
|---|---|---|
| Printed OCR | `ocr.models.OcrBackend` | `TesseractBackend` is a real external CLI adapter. Language selection is configured through `OCR_LANGUAGES` and defaults to `fas+eng` in the settings-backed pipeline factory. |
| Handwriting | `handwriting.ports.HandwritingBackend` | `UnavailableHandwritingBackend` fails explicitly when no acceptable HTR model is installed. A handwriting region never falls back to printed OCR. |
| Tables | `tables.ports.TableBackend` | `PaddleStructureTableBackend` is an optional PP-Structure adapter selected by `paddle`, `paddle-table`, `ppstructure`, or equivalent aliases. `TableResult` preserves structured cells, coordinates, row/column indexes, confidence, runtime metadata, warnings, review flags, and raw cell candidates. The default unavailable adapter fails closed. |
| Region routing | `ocr.routing.RegionRouter` | Stable block/text/layout hints select printed, handwriting, table, or both printed+HTR routes for mixed forms. |

Provider-specific SDK/CLI data remains inside adapters. The canonical domain
does not import Tesseract, PaddleOCR, Surya, or another provider.

## Backend evidence

`OcrResult` and `TableResult` retain backend/model/version, confidence scale,
runtime metadata, warnings, DPI, region scale, preprocessing variant, and
geometry-bearing output. The pipeline copies this evidence into
`ExtractionMetadata`; it never compares confidence values across different
scales without a calibration policy.

Tesseract records the selected language bundle, executable identity, timeout,
and model identifier. Its subprocess invocation uses an argument list and a
bounded timeout. A non-zero exit or timeout becomes a typed processing failure;
missing executables and unavailable language/model runtimes remain explicit
review warnings.

## Canonical assembly

Printed and handwriting results are assembled as:

```text
Document -> Page -> Block -> Line -> Word
```

Table regions are assembled as:

```text
Document -> Page -> Block -> TableCell
```

Each line retains raw text, normalized text, language/script, text type,
geometry, confidence, extraction metadata, candidate alternatives, verification
attempts, uncertainty flags, and a deterministic source-derived line-crop URI
when the crop can be stored. Table cells retain raw/normalized text, row and
column indexes, geometry, confidence, extraction metadata, and raw candidates;
they are not flattened into canonical plain text.

Table adapter coordinates are zero-based pixels in the local prepared crop. The
pipeline validates every cell before assembly: row/column addresses must be
bounded and unique, boxes and polygons must be finite and inside the crop,
near-identical overlapping duplicates are rejected, and excessive empty values
make the structure unusable. Invalid or unusable structure is retained as
warnings/review flags and never repaired by inventing coordinates or cells.
If PP-Structure omits row/column indexes, the adapter derives them only from
valid cell boxes using deterministic row-center grouping and left-to-right
ordering; missing geometry never receives a fabricated address.

## Mixed documents and failure behavior

- A form or explicit mixed region selects both printed OCR and HTR. If HTR is
  unavailable, printed evidence is retained and the block/document is marked
  for review with a capability warning.
- A handwriting-only region selects only HTR. No printed OCR result can be
  produced for it by fallback.
- A table region first selects the configured table adapter. When the adapter
  is unavailable, fails, times out, returns no cells, or returns unusable
  structure, the pipeline routes the same region through printed OCR. The OCR
  lines are retained as text evidence with `table_structure_uncertain` and the
  relevant capability/failure warning; they are never represented as table
  cells. When structured cells are usable, they remain the canonical table
  representation and the pipeline does not silently merge a duplicate OCR
  transcript.
- Tiny table regions use the first configured bounded region-scale candidate
  (normally `region-scale-2`) and map cell geometry back to rendered page
  coordinates. Normal table regions use the source-render crop.
- Plain-text table export is deterministic row-then-column order. Markdown and
  structured page exports retain row/column addresses, raw and normalized text,
  review state, bounding boxes, and extraction backend/model provenance.
- Backend warnings are preserved in extraction metadata and document warning
  records. Processing completion and extraction certainty remain separate.
- A provider cannot normalize or repair raw text; normalization happens only in
  the separate normalized field.

## Configuration

The following settings are validated and included in the configuration hash:

- `OCR_ENABLED_OCR_BACKENDS`
- `OCR_LANGUAGES`
- `OCR_BACKEND_TIMEOUT_SECONDS`
- `OCR_HANDWRITING_BACKEND`
- `OCR_TABLE_BACKEND`
- confidence/retry/DPI and crop limits from earlier phases

The optional PP-Structure runtime is installed with `pip install
ocr-platform[paddle]`. The base installation remains importable without
PaddleOCR or model weights; a configured but unavailable table backend produces
an explicit capability warning and activates printed-OCR fallback.

The default environment does not claim that Tesseract, Persian traineddata,
HTR weights, or table models are installed. Model smoke validation remains a
deployment concern.

## Validation

Phase 6 tests cover multilingual provider evidence, typed unavailable
capabilities, route selection, timeout handling, mixed printed/handwritten
regions, structured Persian/English table cells, deterministic 2x3 cell
ordering, malformed-cell validation, non-origin and scaled geometry mapping,
empty/failed table fallback to printed OCR, candidate retention, line crop
provenance, backend failure warnings, and the existing native-first, layout,
retry, API, security, storage, and export behavior.

The full repository suite currently passes with 254 tests and one optional
model test skipped by default. Static type checking, dependency advisory
scanning, and Docker validation are not claimed unless separately executed in
the target deployment environment.

## Remaining limitations

1. No production HTR or table-cell model is installed in the current runtime;
   the HTR unavailable adapter and optional PP-Structure boundary are
   intentional capability boundaries, not fake recognition. Printed OCR remains
   the safe text fallback for table regions when a table model is unavailable.
2. The Tesseract adapter is real but model/`fas` traineddata availability and
   recognition quality require deployment validation with labeled Persian,
   English, and mixed-script fixtures.
3. Form key/value semantics remain spatial evidence only. The pipeline does
   not infer a semantic key/value pair from nearest text alone.
4. Backend confidence calibration and CER/WER/table accuracy require labeled
   references and per-backend evaluation.

## Recommended next phase

Add a deployed, licensed HTR adapter and a real structure/table adapter behind
the existing ports, then benchmark them on representative Persian/English,
mixed-script, handwriting, small-font, form, and table datasets before changing
the default capability configuration.
