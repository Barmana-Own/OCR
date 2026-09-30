# Phase 8 — Text Normalization, Provenance, Dataset Packaging, and Export

## Scope

Phase 8 turns the canonical OCR result into an auditable dataset package. The
canonical `Document -> Page -> Block -> Line -> Word` result remains the source
of truth; exports are deterministic views and never rewrite recognition
evidence.

## Raw and normalized text

Every text-bearing model retains `raw_text` and `normalized_text` separately.
`raw_text` is the exact native/PDF/OCR/HTR value selected by the pipeline and
is not changed by normalization, verification, or export. `normalized_text` is
derived from the active `NormalizationConfig` and is safe to regenerate.

The policy is versioned and serialized in both `Settings.configuration_hash`
and `DocumentResult.normalization_policy`. Supported controls are:

- Unicode normalization form: NFC, NFKC, NFD, or NFKD;
- Arabic/Persian character-variant mapping;
- Persian, Arabic, ASCII, or preserved digits;
- optional tatweel removal;
- whitespace, line-break, and zero-width-character policies;
- edge trimming.

Digit normalization excludes protected URL, email, date, serial, and mixed
Latin/number tokens unless a future explicitly named policy changes that
contract. Text is never reversed for RTL display. Environment overrides use
the `OCR_NORMALIZATION_*` variables in `.env.example`; invalid values fail
configuration loading.

## Export policies

`DatasetExporter` exposes three explicit policies:

| Policy | Eligible derived labels |
|---|---|
| `strict_verified_only` | `verified` lines/cells only |
| `accepted_verified` | `accepted` and `verified` lines/cells; default |
| `all_with_status` | all statuses, with status retained in text views and partitioned crop paths |

The canonical `document.json` always contains all evidence and all statuses.
The default policy excludes `uncertain`, `human_review_required`, and `failed`
records from plain text, Markdown, and line-crop labels. A caller must opt into
`all_with_status` to export those records as derived training artifacts.
Eligibility is evaluated against the complete line or table-cell record, not
only its enum status. `needs_review`, blocking uncertainty flags, and
unresolved disagreement/quality reason codes are excluded from the default
policies even if a malformed legacy record still carries `accepted` or
`verified`. `all_with_status` includes every record and labels status plus the
review marker in text/Markdown while structured labels retain the full flags,
reason codes, candidates, and verification history.

## Package layout

An export is written atomically beneath a document and processing/policy
identity:

```text
<destination>/<document_id>/export-<processing-prefix>-<policy>/
  manifest.json
  document.json
  document.txt
  document.md
  pages/
    page_0001/
      page.json
      image.png
      lines/<verification-status>/<line-id>.png
      lines/<verification-status>/<line-id>.json
  page-images/page-0001.png          # compatibility view
  line-crops/<line-id>.png            # compatibility view
  labels/<line-id>.json               # compatibility view
```

Page manifests retain the canonical page model and image checksum/reference.
Line labels retain raw and normalized text, polygon/bbox, coordinate space,
page/rendered dimensions, reading order, extraction metadata, candidates,
verification history, uncertainty flags, and review references. `pixel_bbox`
is the clamped crop rectangle in the referenced rendered page image; the
original `page_bbox` is preserved beside it.

## Manifest contract

The export manifest records:

- source filename, content type, byte size, and SHA-256;
- document, schema, pipeline, exporter, configuration, and processing versions;
- the complete normalization policy;
- processing start/end timestamps and elapsed processing time;
- page count, status counts, export counts, warnings, and table-cell counts;
- backend/model/version/confidence-scale inventory and model identifiers;
- selected export policy and formats;
- sorted artifact paths, byte sizes, and SHA-256 checksums.

Manifest timestamps are audit metadata. Export identity and directory naming
use document processing identity plus the explicit policy, so repeated exports
of the same canonical result are reused and different policies cannot collide.
Artifact ordering and JSON serialization use stable sorting and UTF-8 output.

## Storage and security

The exporter accepts the `ArtifactStore` protocol and does not depend on local
filesystem storage in its domain contract. The current local implementation
validates document/artifact path components, reads immutable source-derived
artifacts, and writes the export through a temporary directory followed by an
atomic rename. Unsafe document or line identifiers are rejected. The source
artifact is never overwritten. No raw document contents are written to logs by
the exporter.

## Evidence and limitations

No language model repairs OCR in this phase. Review-required text remains
available in canonical JSON and, when explicitly requested, in
`all_with_status` outputs with its status and verification evidence. OCR/HTR
accuracy, confidence calibration, table accuracy, and CER/WER still require
deployed model runtimes and labeled benchmark data; export validation does not
claim those model-level metrics.

## Tests

Phase 8 tests cover configurable mixed-script normalization, raw-text
immutability, protected identifiers/URLs/emails/dates, environment validation,
configuration-hash changes, policy filtering, explicit review partitions,
page/crop geometry mapping, manifest provenance, model inventory, and
deterministic artifact ordering. Existing Phase 1–7 tests remain part of the
full repository test suite.
