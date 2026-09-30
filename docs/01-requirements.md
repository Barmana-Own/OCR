# Requirements: High-Accuracy Universal OCR & Document Dataset Pipeline

## Functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| FR-001 | Accept native-text PDFs, scanned PDFs, raster photos, printed pages, handwritten pages, and mixed documents through a typed ingestion boundary. | Reader contract tests and API validation |
| FR-002 | Preserve immutable source metadata including document ID, filename, content type, byte size, checksum, and processing configuration hash. | Domain/storage tests |
| FR-003 | Represent `Document -> Page -> Block -> Line -> Word` with page dimensions, block type, reading order, raw/normalized text, coordinates, confidence, language/script, text type, and extraction metadata. | Pydantic schema tests |
| FR-004 | Attempt reliable embedded PDF text extraction before raster OCR and record the decision/fallback reason. | Native-first pipeline tests |
| FR-005 | Render OCR-required pages/regions with bounded configurable DPI and preserve original images separately from derived images. | Imaging/storage tests |
| FR-006 | Route pages/regions to printed, handwriting, table, form, formula, image, header/footer, multi-column, or tiny-text paths when signals support the classification. | Routing tests |
| FR-007 | Keep OCR/layout/HTR/table backends behind replaceable typed adapters with backend/model/version metadata. | Adapter contract tests |
| FR-008 | Preserve backend-specific confidence values without treating scores from different engines as directly comparable. | Domain and verification tests |
| FR-009 | Preserve raw OCR text untouched and create normalized text separately. | Normalization tests |
| FR-010 | Normalize Persian/Arabic character variants and digits through a configurable, testable policy without reversing mixed-direction strings. | Persian/mixed-content fixtures |
| FR-011 | Detect suspicious tiny text and support targeted crop/re-render/scale variants with bounded resource limits. | Tiny-text routing tests |
| FR-012 | Retry low-confidence or suspicious outputs with alternate preprocessing, higher DPI, or alternate backend when configured, preserving attempt history. | Verification tests |
| FR-013 | Compare attempts using confidence/consensus/difference rules and end in `accepted`, `verified`, `uncertain`, or `human_review_required`. | Verification state tests |
| FR-014 | Set uncertainty and human-review flags instead of silently hallucinating or repairing text. | Negative verification tests |
| FR-015 | Trace every line/region to source document/page coordinates and optional source image/crop URI. | Provenance schema tests |
| FR-016 | Export deterministic canonical JSON, plain text, Markdown, page images, and line crops/labels with version/config/source/processing hashes. | Export tests |
| FR-017 | Provide quality metric hooks for CER, WER, line detection, reading order, table/field accuracy, review rate, disagreement, and tiny-text recovery. | Metric unit tests |
| FR-018 | Expose health/readiness and authenticated processing API endpoints with safe error envelopes and upload limits. | API tests |
| FR-019 | Keep persistence, object storage, and worker queues behind ports so deployment can evolve without changing domain logic. | Architecture tests/docs |
| FR-020 | Record retry, verification, review, and export provenance as auditable data. | Canonical model/export tests |

## Non-functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| NFR-001 | Deterministic processing: identical source/config/backend versions produce stable IDs/order/content where backend determinism permits. | Hash/export tests |
| NFR-002 | Fail closed when required parser/OCR dependencies or backends are unavailable; never emit fabricated text. | Unavailable-backend tests |
| NFR-003 | Validate all untrusted inputs and reject invalid enum values, unsupported MIME types, traversal paths, oversized uploads, and unsafe render settings. | Security tests |
| NFR-004 | Do not log secrets, tokens, raw document payloads, or unnecessary personal data. | Redaction tests/review |
| NFR-005 | Bound page dimensions, pixel counts, crop scales, retry count, and export sizes to protect memory/CPU. | Configuration/security tests |
| NFR-006 | Preserve backwards-compatible canonical field semantics and explicitly version schema/pipeline/configuration. | Model/docs review |
| NFR-007 | Support Persian, Arabic, English, and mixed-direction Unicode without destructive bidi manipulation. | Unicode fixture tests |
| NFR-008 | Separate health from readiness and return safe diagnostic information without internal paths or stack traces. | API tests |
| NFR-009 | Provide structured logs/correlation IDs and extension points for OpenTelemetry metrics/traces. | Logging/config review |
| NFR-010 | Provide reproducible local setup, dependency lock policy, environment template, CI, and production runbook. | Deployment validation |
| NFR-011 | Support data retention and deletion decisions without silently destroying source evidence. | Persistence documentation |
| NFR-012 | Make human-review flags and uncertainty visible in canonical exports and labels. | Export tests |
| NFR-013 | Maintain clear module boundaries and avoid hidden global mutable state. | Architecture review |
| NFR-014 | Test core logic with deterministic fixtures and keep external model/infrastructure tests isolated. | Test plan/results |
| NFR-015 | Accessibility and future operator UI must preserve keyboard/focus/error semantics and not encode review state only by color. | Stage 02 design contract |

## Requirement exclusions

The initial release does not claim model-level OCR quality metrics without reference labels or a deployed OCR engine. Such evaluations are supported as hooks and are marked `NOT_RUN` until a labeled benchmark and backend are supplied.
