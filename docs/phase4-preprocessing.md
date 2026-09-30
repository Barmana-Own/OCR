# Phase 4 — Image Preprocessing, Quality Analysis, and Tiny-Text Recovery

## Scope

Phase 4 adds a conservative, provider-neutral imaging subsystem on top of the
Phase 3 ingestion and artifact contracts. It measures image quality as routing
evidence, creates named OCR-ready variants, persists every derived operation,
and keeps a cumulative mapping from the derived image to the rendered page and
the source page coordinate system.

The subsystem never overwrites `source/original.bin` or a page's
`original_render_<dpi>dpi.png`. Derived outputs are written below
`pages/page_NNNN/derived/`, and a deterministic JSON manifest records each
transformation's input artifact, output artifact, parameters, warnings, and
mapping.

## Components

| Component | Responsibility |
|---|---|
| `imaging/quality.py` | Bounded Pillow-only brightness, contrast, sharpness/blur, skew, perspective-hint, background, text-scale, and compression signals. |
| `imaging/geometry.py` | Affine/projective coordinate mappings, crop/scale composition, and mapping to a page reference coordinate space. |
| `imaging/profiles.py` | Typed operation names and deterministic `clean_print`, `mobile_photo`, `low_contrast`, `tiny_text`, `handwriting`, and `binary_scan` profiles. |
| `imaging/operations.py` | Independently composable conservative operations and explicit fallback/warning behavior. |
| `imaging/service.py` | In-memory execution plus immutable artifact persistence and per-step manifests through `ArtifactStore`. |
| `imaging/tiny_text.py` | Evidence-based tiny-text decisions, bounded 2x/3x/4x escalation, and recommended DPI. |
| `imaging/preprocess.py` | Backward-compatible OCR retry preparation with cumulative crop/scale mapping. |
| `storage/layout.py` | Safe deterministic names for derived images and preprocessing manifests. |

## Quality signals

`ImageQualityAnalyzer` returns hints, not acceptance decisions:

- image dimensions and pixel count;
- brightness/mean luminance and standard deviation contrast;
- edge-based sharpness and a normalized blur score;
- projection-profile skew estimate within a bounded search range;
- a low-frequency background variation value;
- a border-asymmetry perspective indicator, explicitly heuristic;
- estimated dark-row text scale;
- JPEG quantization/compression evidence where available;
- deterministic quality flags such as `low_contrast`, `skew_detected`,
  `uneven_background`, `tiny_text_suspected`, and
  `compression_artifacts_suspected`.

Large images are downsampled only for analysis. The source pixels used for OCR
are not replaced by the analysis sample. A missing or weak signal remains
unknown or is flagged; it is not converted into a confident quality claim.

## Composable operations and profiles

The operation contract accepts one image and returns a new image, normalized
parameters, warnings, and a local coordinate mapping. Available operations
are grayscale conversion, contrast enhancement, CLAHE with an explicitly
recorded Pillow equalization fallback, mild denoising, deskew, perspective
correction, background normalization, shadow reduction, adaptive/global
thresholding, safe sharpening, border cleanup, and dewarping hook.

`mobile_photo` perspective correction is intentionally a hook until a detector
supplies a validated quadrilateral. Supplying a four-point quadrilateral uses a
projective mapping and retains the mapping in the manifest. The dewarping hook
records `dewarping_hook_not_configured` when no non-generative dewarper is
installed.

Profiles are enabled and selected through `Settings`:

```text
OCR_PREPROCESSING_PROFILES=clean_print,mobile_photo,low_contrast,tiny_text,handwriting,binary_scan
OCR_DEFAULT_PREPROCESSING_PROFILE=clean_print
OCR_MAX_PREPROCESSING_VARIANTS=8
```

Every step is materialized as a PNG artifact by `PreprocessingService`. A
profile's final artifact is not treated as ground truth; OCR verification still
owns candidate selection and uncertainty status.

## Tiny-text workflow

The `TinyTextPlanner` accepts estimated line/box height, text-density and
first-pass failure evidence. A region is escalated only when at least one
explicit signal supports it. The artifact-aware service then performs:

```text
detect small region
 -> choose highest-quality available input
 -> return 450/600 DPI re-render recommendation
 -> crop with a page-coordinate mapping
 -> create bounded 2x/3x/4x variants
 -> run conservative tiny_text operations
 -> persist all attempts for OCR verification
```

The current PDF ingestion and pipeline paths already render page-level tiny
text at the configured tiny-text DPI. Region-level recovery records the
recommended DPI for a caller that can re-render through `PageRenderer`; it does
not claim that a resize recreated information. No super-resolution or
generative detail is used.

## Geometry and provenance

The coordinate convention is top-left origin with pixel units for rendered and
derived images. `CoordinateMapping` stores a 3x3 output-to-source matrix and a
source-to-page matrix. It maps:

1. OCR geometry in a derived crop/upscale back to the rendered page;
2. rendered pixels to PDF points when `page_reference_size` is supplied;
3. polygons and bounding boxes through crop, scale, rotation, and supported
   perspective transforms.

The artifact manifest retains the mapping after every operation. For a PDF
page, callers should pass the rendered dimensions and the PDF page dimensions
with `page_coordinate_space="pdf_point"`. For standalone corrected images,
source and page pixel coordinates can be identical.

## Safety and failure behavior

- original artifacts are separate and immutable;
- all derived writes use `ArtifactStore` and safe deterministic names;
- repeated identical processing reuses matching immutable artifacts;
- a same-path/different-bytes collision fails with `StorageFailureError`;
- crop, scale, output pixels, and profile selection are validated;
- optional vision libraries are not required for the core path;
- quality signals are backend-neutral and are not confidence scores;
- warnings remain visible in the result and manifest.

## Validation

Phase 4 tests cover deterministic quality signals, synthetic skew estimation,
coordinate mapping, named profile stability, conservative operations, source
immutability, artifact manifests, repeated deterministic runs, tiny-text DPI
recommendation, and 2x/3x/4x recovery variants. Existing PDF/image ingestion,
native-first, OCR retry, storage, API, export, security, and dataset tests are
kept as regression coverage.

## Known limitations

The required runtime does not include NumPy/OpenCV in the current environment.
The implementation therefore uses bounded Pillow algorithms. Perspective
distortion is a heuristic until a layout/capture detector supplies a validated
quadrilateral, and real OCR recovery quality remains `NOT_RUN` without a
deployed OCR backend and labeled reference set.
