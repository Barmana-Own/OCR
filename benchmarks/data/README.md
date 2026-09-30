# Synthetic Phase 10 benchmark fixture

This directory contains a small, versioned, synthetic benchmark fixture for
unit and CLI regression tests. It contains no private production documents,
customer uploads, credentials, or model-generated page images. `source_uri`
values use the `synthetic://` scheme intentionally.

The fixture has one reference document for each required Phase 10 category.
`ground_truth.json` is the immutable reference set and
`predictions/current.json` is a stored candidate set used only by benchmark
tests and the local CLI smoke test. It is not a production OCR backend and
must not be used as a pipeline output source.

The dataset and schema versions are recorded in `manifest.json`. Prediction
files are separate from ground truth so the runner cannot silently score a
reference against itself.
