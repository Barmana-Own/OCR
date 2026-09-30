# Phase 13 Final Integration Audit

Generated: 2026-09-27T11:28:43.374883+00:00

## Verdict

**PASS** for the audited pipeline contracts: 11/11 generated scenarios passed page, geometry, provenance, export, and uncertainty checks. This is not a claim of 100% OCR accuracy.

## Architecture Summary

The modular monolith remains native-first: ingestion and PDF inspection choose native extraction or bounded rendering; image quality and preprocessing create immutable derived artifacts; layout produces provider-neutral regions; routing selects printed OCR, handwriting, or table adapters; verification retains candidates and review evidence; normalization never overwrites raw text; deterministic exporters produce canonical and training-safe artifacts; workers persist page checkpoints and bounded progress.

## Supported Inputs and Languages

| Area | Coverage |
| --- | --- |
| Inputs | Native PDFs, scanned PDFs, image PDFs, PNG, JPEG/JPG, TIFF/WEBP where Pillow accepts them |
| Languages | Persian/Farsi, English, mixed Persian-English metadata and normalization paths |
| Structures | Printed text, handwriting route, forms, tables, multi-column regions, tiny text, headers/footers |
| Provenance | Document/page identity, coordinate space, page dimensions, source/crop URI, extraction metadata, candidates, verification history |

## End-to-End Scenario Results

| Scenario | Pages | Lines | Cells | Processing | Quality | Geometry/provenance | Raw/normalized | Tiny escalation | Mixed routes | Uncertainty | Deterministic export |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| native_persian_pdf | 2 | 6 | 0 | completed | verified | PASS | PASS | PASS | PASS | PASS | PASS |
| scanned_persian_pdf | 1 | 1 | 0 | completed | verified | PASS | PASS | PASS | PASS | PASS | PASS |
| mixed_persian_english_pdf | 1 | 1 | 0 | completed | verified | PASS | PASS | PASS | PASS | PASS | PASS |
| phone_photo_perspective | 1 | 1 | 0 | completed | verified | PASS | PASS | PASS | PASS | PASS | PASS |
| tiny_font_document | 1 | 1 | 0 | completed_with_warnings | human_review_required | PASS | PASS | PASS | PASS | PASS | PASS |
| handwritten_page | 1 | 1 | 0 | completed | accepted | PASS | PASS | PASS | PASS | PASS | PASS |
| form_labels_handwriting | 1 | 2 | 0 | completed | accepted | PASS | PASS | PASS | PASS | PASS | PASS |
| table_heavy_document | 1 | 0 | 4 | completed | accepted | PASS | PASS | PASS | PASS | PASS | PASS |
| multi_column_page | 1 | 2 | 0 | completed_with_warnings | human_review_required | PASS | PASS | PASS | PASS | PASS | PASS |
| low_quality_scan | 1 | 1 | 0 | completed_with_warnings | human_review_required | PASS | PASS | PASS | PASS | PASS | PASS |
| mixed_native_scanned_pdf | 2 | 2 | 0 | completed | verified | PASS | PASS | PASS | PASS | PASS | PASS |

Audited output volume: 18 lines and 4 structured table cells.

## OCR Backends and Model Versions

| Backend | Model | Version | Available | Device | Reason |
| --- | --- | --- | --- | --- | --- |
| tesseract | tesseract-lstm | external | no | cpu | backend unavailable |
| heuristic-projection | pillow-projection | 1 | yes | cpu |  |
| unavailable | none | none | no | cpu | handwriting recognition backend is not configured |
| unavailable | none | none | no | cpu | table extraction backend is not configured |

The repository's production factory is fail-closed when optional model runtimes are unavailable. The environment used for this audit did not provide the external Tesseract executable, Paddle model runtime, HTR weights, or table model. The scenario adapter names beginning with `phase13-audit-` are deterministic contract fixtures used only by this audit script and are not production backends.

## Tiny-Text Recovery

The recovery audit returned `is_tiny=True`, recommended `600` DPI, scales `[2, 3, 4]`, and `3` bounded variants. Source mapping preservation: `True`.

## Benchmark Results

The versioned synthetic benchmark `synthetic-phase10-1.0.0` ran in `accurate` mode across 13 categories. Configured quality gates: `PASS`. Overall CER: `0.0`; line-detection recall: `1.0`; tiny-text recovery improvement: `0.05555555555555555`. These are synthetic fixture metrics; model versions: `['embedded-text@1', 'fixture@1', 'synthetic-primary']`; configuration hash: `8a9b3c3de36f7c3f17381f1235c2d7ba5d1e28c2889ac1b2b1d855d772d4037c`. They are not production accuracy claims.

## Human-Review Workflow

Low confidence, backend disagreement, tiny text, unavailable HTR/table capabilities, and malformed or incomplete evidence remain explicit verification flags. Review records retain competing raw candidates, normalized candidates, confidence values, backend/model/version, preprocessing variant, source/crop references, and the highlighted review artifact. Strict exports exclude uncertain and human-review-required records; all-with-status exports retain status labels for audit.

## Known Failure Modes

OCR can fail or require review when source pixels are missing, pages are severely blurred or compressed, handwriting is illegible, content is occluded, pages are damaged, fonts are unusual, scripts are unsupported, or a required model/runtime is unavailable. Super-resolution is not treated as ground truth. The pipeline preserves the candidate and surfaces uncertainty rather than silently repairing text.

## Deployment and Operations

1. Copy `.env.example` to a private environment configuration and provide authentication keys for staging/production.
2. Build with `python -m build --no-isolation` or the repository Dockerfile.
3. Run local CPU orchestration with `docker compose config` followed by `docker compose up --build` when Docker Engine is available.
4. Use `/healthz`, `/readyz`, and authenticated `/metrics`; run the worker entrypoint separately for queued processing.
5. Mount private artifact, temporary, model, and cache storage; do not package proprietary model weights without license approval.

## Remaining Risks

- Real OCR quality cannot be certified on this host because the production OCR executable and optional model runtimes are unavailable.
- GPU utilization, model memory behavior, and long-document throughput require dedicated hardware validation.
- `pip-audit`, static type checking, and a live Docker build/runtime smoke test require tools not available in the audit environment.
- Benchmark fixtures are synthetic and demonstrate contract behavior, not representative production accuracy.

## Next Optimization Priorities

1. Run the benchmark and end-to-end audit with licensed Persian-capable OCR/HTR/table models on CPU and GPU runners.
2. Calibrate confidence policies per backend using permitted labeled samples; preserve backend-specific scales.
3. Measure 300/450/600 DPI cost and tiny-text recovery on real, redacted documents.
4. Add dedicated model-worker health and memory metrics after selecting the production model runtimes.

## Audit Limitations

No 100% accuracy claim is made. Contract-level checks passed for generated scenarios, while actual recognition accuracy remains dependent on the selected, licensed OCR/HTR/table runtimes and source quality.
