# Phase 3 — Document Ingestion and PDF Intelligence

## Status

Phase 3 is implemented in the modular monolith. The ingestion boundary accepts bounded PDF and raster inputs, inspects each page independently, preserves native PDF evidence when reliable, renders only pages that require raster processing, and returns typed page descriptors plus immutable artifact references.

The implementation does not perform OCR, layout inference, handwriting recognition, table extraction, normalization, or verification. Those stages consume `PageInput.render_artifact`, `PageInput.native_lines`, page geometry, and the retained classification evidence.

## Supported inputs and validation

| Input | Detection | Decoder | Output coordinate space |
|---|---|---|---|
| PDF | `%PDF-` signature, then PyMuPDF parsing | PyMuPDF | `pdf_point` for native text; rendered pixels for OCR |
| JPEG/JPG | JPEG signature | Pillow | `source_pixel` after EXIF orientation |
| PNG | PNG signature | Pillow | `source_pixel` after EXIF orientation |
| TIFF | Little- or big-endian TIFF signature | Pillow | `source_pixel` after EXIF orientation |
| WEBP | RIFF/WEBP signature | Pillow | `source_pixel` after EXIF orientation |

The declared MIME type is treated as a hint only. A known file signature wins; malformed content is rejected by the actual parser/decoder. Empty files, unsupported signatures, unsafe custom document IDs, configured upload/page/pixel limits, corrupt PDFs, password-protected PDFs, and invalid image dimensions fail with typed application errors.

## Processing flow

```text
ingest
 -> validate size and content signature
 -> compute source SHA-256 and deterministic document ID
 -> persist source/original.bin
 -> inspect each PDF page or decode one raster page
 -> classify native text / scanned / mixed / image
 -> retain page geometry, rotation, evidence, and quality metadata
 -> render only OCR-required pages at bounded DPI
 -> persist pages/page_0001/original_render_<dpi>dpi.png
 -> return IngestionResult for downstream routing
```

The source bytes are never overwritten. Derived artifacts are stored beneath a deterministic document namespace through the `ArtifactStore` contract; the current development adapter is `LocalArtifactStore`.

## PDF inspection

`PdfReader.extract` loads the PDF once and creates one `PageInput` per page. For each page it records:

- visible dimensions (`page.rect`) and unrotated media-box dimensions;
- normalized rotation metadata (`0`, `90`, `180`, or `270` degrees);
- native text lines with exact extracted Unicode, PDF-point bounding boxes, block index, and line index;
- embedded image regions and estimated image coverage;
- character count, line count, text coverage, useful-character plausibility, suspicious-character ratio, and a reliability reason;
- page classification and quality flags, including `tiny_text` and `image_dominant` when detected.

Native text is reliable only when all configured heuristics pass: minimum non-whitespace characters, minimum geometric coverage, maximum replacement/control-character ratio, and minimum alphanumeric plausibility. Empty, sparse, suspicious, implausible, or low-coverage text layers remain in the result but are marked unreliable and routed to raster processing. These thresholds are configurable through environment variables and are not hard-coded in routing logic.

Classification is page-specific:

- reliable native text without embedded image regions → `native_text`;
- any page with both native text objects and embedded image regions → `mixed`;
- a page without reliable usable native text → `scanned`;
- standalone raster input → `image`.

The native line text is not normalized or reversed. Persian/Arabic Unicode, digits, punctuation, identifiers, and mixed RTL/LTR sequences remain exactly as returned by the PDF text layer. Later normalization operates on a separate field.

## Rendering and resource safety

PDF pages are rendered through PyMuPDF at the requested configured DPI. Default page rendering is 300 DPI; high-quality and tiny-text policies expose 450 and 600 DPI settings. Before rendering, the page dimensions and expected pixel count are checked against `max_render_pixels`, `max_page_width`, and `max_page_height`. The rendered PNG records actual pixel dimensions, DPI, rotation, and source URI.

Raster input is decoded with Pillow, materialized before the decoder context closes, and corrected with `ImageOps.exif_transpose`. Original source dimensions and EXIF orientation are retained in `PageQualityMetadata`; the corrected raster is encoded as a separate PNG for downstream OCR. No global Pillow pixel limit is changed, and no derived image replaces the source artifact.

A tiny native text flag is retained as evidence. Reliable native text is not needlessly OCRed merely because it is small. If a page also requires OCR, the ingestion service selects the configured tiny-text DPI; region crops and multi-variant verification remain downstream responsibilities.

## Artifact layout

The default deterministic layout is:

```text
<storage-root>/<document-id>/
  source/
    original.bin
  pages/
    page_0001/
      original_render_300dpi.png
      derived/
      crops/
  manifests/
    processing.json
```

Artifact names are validated component-by-component to prevent traversal. Writes are atomic and content checksums are returned with every stored artifact. Reusing a document ID with different source bytes is rejected.

## Stable contracts

- `PdfExtractor` — provider-neutral page inspection with `extract(...)`.
- `PageRenderer` — bounded page rendering with `render_page(...)`.
- `ArtifactStore` — immutable-by-default byte storage, retrieval, existence, and checksum-bearing references. `QualityEvaluator` is also exposed as a provider-neutral quality aggregation port.
- `IngestionResult` — source metadata, source artifact, ordered page descriptors, typed warnings, and separate processing status.

`PdfReader` implements both PDF contracts. `DocumentReaderService` selects PDF or Pillow adapters without exposing provider SDK types to domain models. A future PDFium or remote storage adapter can replace these implementations without changing downstream routing contracts.

## Failure semantics

| Condition | Error | Behavior |
|---|---|---|
| unsupported or unrecognized input | `UnsupportedDocumentError` | reject before processing |
| malformed PDF | `CorruptPdfError` | reject; preserve no fabricated page result |
| encrypted PDF requiring a password | `PasswordProtectedPdfError` | reject explicitly |
| bounded page render failure | `PageRenderError` | reject page processing with retryability metadata |
| malformed raster | `ImageDecodeError` | reject decoder output |
| invalid dimensions/geometry | `InvalidDocumentError` / `InvalidGeometryError` | reject unsafe work |
| storage write/read failure | `ArtifactStorageError` family | do not return an unreferenced result |

No error path substitutes synthetic OCR text or silently repairs source content.

## Tests and current limitations

The focused fixture suite covers native Persian/mixed PDF text, scanned and mixed pages, rotation metadata, corrupt/password-protected PDFs, tiny embedded text, EXIF orientation, image quality metadata, malformed images, dimension limits, TIFF/WEBP decoding, unsafe custom IDs, and deterministic source/page artifact paths. The full repository suite remains the release gate.

Current limitations are deliberate: TIFF inputs are treated as one decoded page; multipage raster container expansion is not yet implemented. Image quality analysis currently records deterministic luminance/contrast and metadata signals but does not yet estimate blur, skew, illumination, or capture quality. OCR/layout/HTR/table adapters remain separate downstream phases.

