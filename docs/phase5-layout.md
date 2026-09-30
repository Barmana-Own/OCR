# Phase 5 — Layout Detection, Region Classification, and Reading Order

## Status

Phase 5 is implemented in the synchronous modular-monolith pipeline. The
layout stage is provider-neutral and runs before OCR routing for raster pages;
reliable native PDF pages receive equivalent layout evidence from their native
PDF lines.

## Scope

This phase establishes the contract and execution boundary for:

- provider-neutral page regions and pre-OCR line geometry;
- stable block taxonomy and next-stage route hints;
- geometry validation, clipping, and provider-polygon preservation;
- single-column, multi-column, header/footer, sidebar, table, and page-number
  reading order;
- Persian/Arabic RTL spatial ordering without character or string reversal;
- explicit confidence/uncertainty propagation into OCR regions;
- deterministic fallback behavior when an optional model backend is unavailable.

The stage does not claim handwriting recognition, formula recognition, form
field extraction, or table-cell accuracy without a deployed backend that
provides that evidence.

## Execution flow

```text
page input
  -> native line layout (reliable PDF text) or raster layout backend
  -> provider-label/taxonomy mapping
  -> geometry validation and page-bound clipping
  -> layout confidence gate
  -> block and pre-OCR line reading order
  -> route hints and OCR-region metadata
  -> OCR/HTR/table adapter
```

`DocumentPipeline` keeps native text first. A reliable native page is not
rasterized solely for layout. A scanned, image-only, or unreliable-text page
is rendered at the configured DPI, analyzed once, and the resulting layout
regions are handed to `PageRouter` and then to the injected OCR backend. A
mixed page preserves native blocks and only routes its image regions to OCR.

## Module boundaries

| Module | Responsibility |
|---|---|
| `layout/ports.py` | `LayoutBackend`, `LayoutRegion`, `LayoutLine`, `LayoutResult`, warnings, and route hints. |
| `layout/classification.py` | Maps provider labels into stable `BlockType`, `TextType`, and `RegionRouteHint` values. |
| `layout/normalization.py` | Validates finite geometry, clips to page dimensions, derives bbox from polygons, and preserves provider-native polygons. |
| `layout/heuristic.py` | Bounded Pillow projection detector for visual lines, columns, bands, tiny text, and simple grid regions. It never creates OCR text. |
| `layout/providers.py` | Optional PaddleOCR PP-Structure adapter and explicit backend factory. Provider SDK imports remain here. |
| `layout/reading_order.py` | Spatial block/line ordering and column estimation. RTL changes traversal direction only. |
| `layout/service.py` | Orchestrates backend invocation, normalization, confidence gating, warnings, and ordering. |
| `ocr/routing/page_router.py` | Converts normalized layout regions into typed OCR region metadata while retaining the native-first route. |
| `pipeline.py` | Connects layout results to canonical blocks and OCR calls without selecting cross-backend confidence winners. |

## Stable taxonomy and routing

The internal block taxonomy includes:

`title`, `paragraph`, `text_line_group`, `printed_text`, `handwriting`,
`table`, `form`, `formula`, `image`, `figure`, `caption`, `header`, `footer`,
`page_number`, `sidebar`, `list`, `multi_column`, `tiny_text`, and `unknown`.

The smaller route-hint vocabulary is intentionally conservative:

`printed_text`, `handwriting`, `table`, `form`, `formula`, `image`,
`tiny_text`, and `unknown`.

Unrecognized provider labels map to `unknown` with
`unknown_provider_class`. Low provider confidence is retained and adds
`low_layout_confidence`. The service applies the configured
`layout_min_confidence` gate independently of any provider-specific score
meaning. Layout confidence is not compared with OCR confidence.

The Pillow fallback detects visual structure, not semantic content. It marks
the text type as unknown and requires review where it cannot distinguish
printed text from handwriting. A simple full-line grid may be surfaced as an
atomic table region with `table_cells_not_detected`; it does not fabricate
cells or cell text.

## Geometry and provenance

Layout geometry uses top-left origin coordinates in the declared
`CoordinateSpace`:

- `PDF_POINT` for native PDF line/layout evidence;
- `SOURCE_PIXEL` for source raster dimensions;
- `RENDERED_PIXEL` for OCR page images.

Coordinates are floating-point values in the page reference dimensions. Every
normalized region and line has a positive-area bbox. Finite out-of-bounds
coordinates are clipped. Reversed, non-finite, degenerate, or invisible
geometry is rejected for that region and emitted as a scoped
`LayoutWarning(code="invalid_geometry")`; it is not passed to OCR.

When a provider supplies a polygon, the normalized polygon is available for
internal use and `provider_polygon` retains the original provider geometry.
The bbox is derived from the normalized polygon when one is present. This
preserves both safe downstream coordinates and audit evidence about what the
provider returned.

## Reading order

`order_layout_regions` assigns stable zero-based order values to blocks and
lines. The current geometry policy is:

1. headers and titles lead the page;
2. body regions are grouped into horizontal columns using page-relative gaps;
3. LTR columns traverse left-to-right and RTL columns right-to-left;
4. regions within a column traverse top-to-bottom;
5. tables remain one atomic region until a table adapter supplies cells;
6. sidebars are retained as separate regions after body content;
7. footers and page numbers trail the page.

Mixed-script content is not handled by reversing strings. Spatial ordering is
derived from geometry and, for native text, from detected script direction.
The text payload remains exactly as returned by PDF extraction or OCR; RTL UI
rendering is a consumer concern, not a normalization step.

## OCR handoff

Each layout region becomes an `OcrRegion` with:

- stable region ID and page coordinate space;
- block type and text type hint;
- tiny-text signal;
- numeric reading order;
- layout confidence and provider label;
- pre-OCR line bboxes when supplied.

The OCR adapter still owns provider invocation, model/version, confidence
scale, and line/word parsing. Verification still owns retry and candidate
selection. Layout metadata is provenance and routing evidence; it does not
silently rewrite OCR output or calibrate backend scores.

## Configuration

The following settings are environment-overridable and included in the
configuration hash:

| Setting | Default | Purpose |
|---|---:|---|
| `OCR_LAYOUT_BACKEND` | `heuristic` | `heuristic`, `pp_structure`, `unavailable`, or an explicit supported alias. |
| `OCR_LAYOUT_MAX_PIXELS` | `4000000` | Maximum pixels analyzed by the bounded fallback sample. |
| `OCR_LAYOUT_MAX_REGIONS` | `512` | Maximum normalized regions accepted from one backend call. |
| `OCR_LAYOUT_MIN_CONFIDENCE` | `0.35` | Review gate for provider layout confidence. |

The backend factory raises a typed configuration error for an unknown backend.
The optional PP-Structure adapter raises a typed unavailable error when the
runtime/model cannot initialize. It never returns fake layout output.

## Validation evidence

Phase 5 tests cover:

- positional layout contract compatibility and serialization-adjacent fields;
- provider-label taxonomy mapping and unknown/low-confidence flags;
- bbox/polygon clipping, provider polygon preservation, and impossible geometry;
- deterministic two-column Pillow detection and line regions;
- conservative handling of unsupported handwriting semantics;
- RTL/LTR column order, mixed-direction lines, headers, tables, footers, and
  ambiguous review flags;
- layout-to-OCR handoff and native-line reconciliation;
- settings defaults, environment overrides, validation, and config hashing.

## Known limitations

- The default Pillow detector is structural and cannot reliably classify
  handwriting, formulas, forms, captions, or complex tables.
- PP-Structure smoke execution is not available when PaddleOCR/model weights
  are not installed; the adapter remains explicit and fail-closed.
- Column grouping and band classification are deterministic heuristics and
  require benchmark evaluation on representative Persian, English, mixed, and
  complex-document samples.
- The current pipeline remains synchronous and does not add a worker queue or
  durable layout-result repository.

