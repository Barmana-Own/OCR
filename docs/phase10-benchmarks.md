# Phase 10 — OCR Benchmarks, Regression Tests, and Quality Gates

## Scope and evidence policy

The benchmark subsystem measures reference-backed OCR behavior without treating
an aggregate score as ground truth. Reference data and candidate outputs are
separate versioned JSON artifacts. The runner never invokes a fake OCR backend
and never copies reference text into a candidate. The checked-in fixture is
synthetic only; private production documents must remain outside the
repository. Public or redacted samples can be added later through the same
versioned manifest contract.

The current fixture at `benchmarks/data` has one synthetic document for each of
these categories:

`clean_persian`, `clean_english`, `mixed_persian_english`, `low_quality_scan`,
`phone_photo`, `skewed_perspective`, `tiny_text`, `handwritten_persian`,
`form_card`, `table`, `multi_column`, `native_text_pdf`, and
`mixed_native_scanned_pdf`.

It contains no page images or private source material. The stored prediction
file is a test candidate fixture and is not a production pipeline output.

## Versioned data contract

`benchmarks/data/manifest.json` identifies the schema and dataset versions and
references dataset-relative files. The loader rejects absolute paths, Windows
path separators, path traversal, missing files, oversized JSON artifacts,
version mismatches, duplicate IDs, and category mismatches. Ground truth
contains:

- document ID, category, and source URI;
- page number and dimensions;
- page text;
- line raw/normalized text, bbox/polygon, reading order, tiny-text flag, and
  optional review label;
- structured table cells with row/column coordinates and text.

Predictions use the same page and region identity plus backend/model/version,
confidence, verification status, verification-routing flag, candidate list,
and tiny-text stage candidates. Raw candidate text remains distinct from any
normalized text.

## Metrics

`ocr_platform.benchmarks.metrics` reuses the existing pure functions in
`ocr_platform.quality.metrics` and reports one `CategoryMetrics` record per
category plus a clearly labeled `overall` record. The category records are the
release-gate evidence; overall values are not a substitute for them.

The report includes:

- page and line CER/WER;
- exact line accuracy using normalized text when provided, otherwise raw text;
- line detection precision/recall using greedy one-to-one bbox IoU matching;
- reading-order accuracy using ordered line IDs;
- exact table-cell accuracy by row/column position;
- accepted-automatically, verification, and human-review rates over predicted
  lines;
- backend disagreement rate over lines with at least two candidates;
- tiny-text stage CER and recovery improvement.

Missing reference lines contribute an empty candidate to text metrics and
missing predicted lines remain visible in detection recall. Confidence values
are retained as evidence but are not recalibrated or compared across backend
names.

## Tiny-text evaluation

For each reference line marked `tiny_text`, the report separately evaluates:

1. `first_pass`;
2. `high_dpi`;
3. `crop_upscaled`;
4. `verified_final`.

`recovery_improvement` is `first_pass CER - verified_final CER`; positive values
show measured improvement, zero shows no change, and negative values expose a
regression. A higher-resolution stage is not considered useful merely because
it ran.

## CLI

The stored-candidate regression CLI is deterministic in ordering and IDs while
recording the actual generation timestamp and host metadata:

```powershell
python -m ocr_platform.benchmarks.run `
  --dataset benchmarks/data `
  --mode accurate `
  --output benchmark_results.json
```

The command writes JSON and a Markdown report beside the requested output by
default. Use `--markdown-output` to choose another Markdown path,
`--predictions <name>` to select a manifest prediction set, `--variant` to
label a backend/DPI/profile run, and `--quality-gates <file>` to apply a gate
configuration. `--fail-on-gate` is opt-in; without it, the command records a
failed gate in the report without changing source data or failing a local
measurement run.

The report records dataset/schema versions, a content hash of the manifest and
ground truth, effective mode configuration hash, prediction-set name, backend
model identifiers/versions, Python/platform hardware metadata, category
metrics, gate evidence, and optional baseline comparison.

## Comparisons and regression policy

Generate a current report, retain it as a baseline artifact, then compare a
later run with `--baseline baseline.json`. Lower CER/WER is better; higher
accuracy, recall, acceptance, and tiny-text improvement are better. A
comparison records every common category/metric delta and flags directional
regressions. `--comparison-tolerance` can absorb a documented numeric noise
floor.

The same contract supports backend A/B, 300 DPI versus adaptive DPI, and
preprocessing profile comparisons: store each candidate set under a distinct
manifest prediction name, run each with a distinct `--variant`, and compare
the resulting reports. No provider-specific logic is required in the metric
layer.

## Quality gates and CI separation

Gate files contain `schema_version` and rules with a category, metric path, and
exactly one `minimum` or `maximum` bound. Example:

```json
{
  "schema_version": "1.0.0",
  "gates": [
    {
      "name": "overall-line-recall",
      "category": "overall",
      "metric": "line_detection_recall",
      "minimum": 0.98
    },
    {
      "name": "tiny-recovery",
      "category": "tiny_text",
      "metric": "tiny_text.recovery_improvement",
      "minimum": 0.0
    }
  ]
}
```

Normal CI can run unit/integration tests without model runtimes. Benchmark
tests and the stored-fixture CLI smoke are a separate deterministic job. GPU or
heavy model tests are opt-in and must be marked with the repository's `gpu` or
`model` pytest markers; they are not part of the normal unit command. The
current environment has no installed GPU/model weights, so real provider
benchmarks are `NOT_RUN`, not simulated.

Recommended commands:

```powershell
python -m pytest -q tests --ignore=tests/benchmarks
python -m pytest -q tests/benchmarks
python -m ocr_platform.benchmarks.run --dataset benchmarks/data --mode accurate --output benchmark_results.json
```

## Known limitations

The checked-in data is synthetic and demonstrates contract/metric behavior,
not production OCR accuracy. Real CER/WER, handwriting, table, and model
comparisons require permitted labeled samples plus installed model runtimes.
The benchmark runner intentionally evaluates stored candidates; a future
model-backed benchmark adapter can generate those candidates without changing
the schema, metrics, comparison, or gate contracts.
