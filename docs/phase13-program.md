# OCR Platform Implementation Program

This document records the incremental implementation delivered after the Phase 12 runtime baseline. It describes real adapter boundaries and runtime behavior; it does not claim model accuracy without an external model and labeled ground truth.

## Implemented capabilities

### Verification and export safety

- Candidate verification records the backend family separately from the backend name.
- Same-backend preprocessing retries do not count as independent-engine evidence.
- Configurable independent-backend consensus is enabled by default for verified overrides.
- `needs_review=true` records are excluded from `strict_verified_only` and `accepted_verified` exports, even if a status field is inconsistent.
- Human corrections remain append-only revisions and exports expose both the original raw text and the effective corrected value.

### Native document formats

The ingestion detector validates container signatures and OOXML members rather than trusting an Office extension or MIME declaration. Native readers are available for:

- DOCX paragraphs and page breaks;
- XLSX sheets, shared strings, inline strings, and cell coordinates;
- legacy XLS when the optional `office` extra provides `xlrd` and `olefile`;
- PPTX slide text, geometry, and embedded-image regions;
- UTF-8 TXT, CSV, JSON, and HTML as logical native-text pages.

Office pages with embedded visual regions retain an explicit visual-OCR requirement. LibreOffice/`soffice` is an optional local renderer for those pages; it is never downloaded by the pipeline.

### Optional model adapters

- `PaddleOcrBackend` is a lazy printed OCR adapter with backend-family metadata and support for common PaddleOCR 2.x/3.x result shapes.
- `PaddleStructureTableBackend` maps provider cell geometry/text into typed row/column cells and emits warnings when the provider omits structure.
- `TransformersHandwritingBackend` loads only an explicitly configured local model with `local_files_only=True`; it reports no fabricated confidence.
- When a table backend is unavailable, printed OCR still runs on table regions and structure capability/review warnings are retained.

Install optional capabilities explicitly:

```powershell
python -m pip install -e ".[paddle,office]"
python -m pip install -e ".[htr]"
python -m pip install -e ".[distributed]"
```

The base installation remains usable without model packages or model downloads.

### Advanced preprocessing and benchmarking

The primary pipeline now selects named preprocessing profiles while creating OCR variants. The selected profile is recorded in extraction metadata. Tiny-text variants retain DPI, region scale, profile, and cumulative coordinate mappings.

The benchmark CLI can execute the real pipeline against local/file ground-truth sources:

```powershell
python -m ocr_platform.benchmarks.run `
  --dataset benchmarks/data `
  --run-pipeline `
  --sources-root . `
  --require-external-ground-truth `
  --mode accurate `
  --output benchmark-results.json
```

Synthetic fixtures remain valid for contract/regression tests, but `--require-external-ground-truth` rejects synthetic-only evaluation. Predictions, candidates, verification state, and tiny-text stages are written separately from ground truth.

## Distributed deployment boundary

The default remains a local modular monolith with file metadata and local immutable artifacts. Explicit environment settings can select:

| Concern | Local default | Distributed adapter |
| --- | --- | --- |
| Artifacts | `LocalArtifactStore` | `S3ArtifactStore` |
| Metadata | `FileDocumentRepository` / `FileJobRepository` | PostgreSQL JSONB repositories |
| Jobs | bounded executor | Redis reliable-list queue with in-flight acknowledgement plus `python -m ocr_platform.worker` |

Relevant settings are documented in `.env.example`:

- `OCR_ARTIFACT_STORE_BACKEND`, `OCR_S3_ENDPOINT_URL`, `OCR_S3_PREFIX`, `OCR_ARTIFACT_BUCKET`;
- `OCR_METADATA_BACKEND`, `OCR_POSTGRES_DSN`, `OCR_POSTGRES_SCHEMA`;
- `OCR_QUEUE_BACKEND`, `OCR_REDIS_URL`, `OCR_REDIS_QUEUE_NAME`;
- `OCR_PROCESSING_TIMEOUT_SECONDS`, which is enforced before and after document processing and at progress callbacks.

Connection strings are never included in the configuration hash. Distributed adapters are lazy about optional imports and fail with typed capability/storage errors when dependencies or connections are unavailable.

The Compose file keeps the default API service local and provides an opt-in `distributed` worker profile. It does not create cloud services, inject credentials, or package model weights.

## Failure and safety policy

- Unsupported signatures, malformed Office containers, invalid structured text, missing optional runtimes, and unavailable remote dependencies produce typed errors or explicit warnings.
- Original source artifacts are immutable. Derived Office renders, crops, and review artifacts are separate objects.
- Document IDs, artifact names, S3 keys, schema identifiers, filenames, upload bytes, rendered pixels, and queue capacity remain bounded and validated.
- Raw OCR/native text remains separate from normalized and corrected text.
- No general-purpose language model silently repairs OCR or replaces raw evidence.

## Current limitations

- PaddleOCR, PP-Structure, HTR, LibreOffice, PostgreSQL, Redis, and S3-compatible services were not available in the current local validation environment; their adapters are contract-tested with deterministic boundary fakes where appropriate.
- The current benchmark corpus is synthetic/contract-oriented. Accuracy, CER/WER, table-cell accuracy, handwriting quality, and tiny-text improvement claims require permitted external ground truth and installed models.
- DOCX/XLSX embedded visual regions are marked for visual routing; precise per-object extraction remains dependent on the Office renderer and later layout/OCR processing.
- The Redis queue moves dequeued jobs to an in-flight list and acknowledges them after processing; stale-message reclamation, autoscaling, and deployment-specific monitoring remain infrastructure responsibilities.
