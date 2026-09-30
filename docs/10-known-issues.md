# Known Issues

## Release-relevant limitations

- The default layout router currently emits a page-wide printed-text region for OCR-required pages. Model-backed layout/table/form/handwriting adapters are defined but require deployment-specific implementations and weights.
- Real OCR quality and CER/WER are not measured without a labeled benchmark and an installed production OCR backend.
- Local artifact storage plus atomic local job/document metadata are single-node adapters; PostgreSQL/S3-compatible storage, distributed queue workers, and restart recovery remain ports.
- Static service API keys require gateway rate limiting, rotation, and secret-manager integration before public exposure.
- `pip-audit`, Docker smoke, load testing, and external model tests were not run because the required tools/runtime were unavailable.
- Starlette emitted two dependency deprecation warnings during tests; no project-source warning caused a failure.

These items are explicit scope or deployment dependencies, not hidden fallbacks. Missing backends produce review-required output rather than fabricated text.
