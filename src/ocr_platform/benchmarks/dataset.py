"""Safe loading of versioned benchmark references and stored candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .models import BenchmarkManifest, GroundTruthDataset, PredictionDataset, QualityGateConfig

MAX_DATASET_JSON_BYTES = 25 * 1024 * 1024


class DatasetLoadError(ValueError):
    """Raised when a benchmark fixture is invalid or unsafe to load."""


@dataclass(frozen=True)
class LoadedBenchmarkDataset:
    root: Path
    manifest: BenchmarkManifest
    ground_truth: GroundTruthDataset
    predictions: dict[str, PredictionDataset]
    quality_gates: QualityGateConfig | None = None


def _dataset_root(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.is_file():
        if candidate.name != "manifest.json":
            raise DatasetLoadError("dataset file must be named manifest.json")
        candidate = candidate.parent
    if not candidate.exists() or not candidate.is_dir():
        raise DatasetLoadError(f"dataset directory does not exist: {path}")
    return candidate.resolve()


def _resolve_reference(root: Path, reference: str) -> Path:
    raw = Path(reference)
    if raw.is_absolute() or not reference.strip() or "\\" in reference:
        raise DatasetLoadError("dataset references must be dataset-relative POSIX paths")
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DatasetLoadError("dataset-relative reference escapes the dataset root") from exc
    return resolved


def _read_json(root: Path, reference: str) -> dict[str, object]:
    path = _resolve_reference(root, reference)
    if not path.is_file():
        raise DatasetLoadError(f"dataset artifact does not exist: {reference}")
    if path.stat().st_size > MAX_DATASET_JSON_BYTES:
        raise DatasetLoadError("dataset JSON artifact exceeds the configured size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetLoadError(f"dataset JSON artifact is unreadable: {reference}") from exc
    if not isinstance(payload, dict):
        raise DatasetLoadError(f"dataset JSON artifact must contain an object: {reference}")
    return payload


def _parse[T: BaseModel](model: type[T], payload: dict[str, object], reference: str) -> T:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise DatasetLoadError(f"invalid benchmark artifact {reference}: {exc}") from exc


def _validate_loaded_documents(
    manifest: BenchmarkManifest,
    ground_truth: GroundTruthDataset,
    predictions: dict[str, PredictionDataset],
) -> None:
    expected_refs = {item.document_id: item.category for item in manifest.documents}
    ground_truth_docs = {item.document_id: item for item in ground_truth.documents}
    if set(expected_refs) != set(ground_truth_docs):
        raise DatasetLoadError("manifest and ground-truth document IDs do not match")
    for document_id, category in expected_refs.items():
        if ground_truth_docs[document_id].category != category:
            raise DatasetLoadError(f"category mismatch for document {document_id}")
    for name, prediction_set in predictions.items():
        prediction_docs = {item.document_id: item for item in prediction_set.documents}
        if set(prediction_docs) != set(expected_refs):
            raise DatasetLoadError(
                f"prediction set {name!r} document IDs do not match ground truth"
            )
        for document_id, category in expected_refs.items():
            if prediction_docs[document_id].category != category:
                raise DatasetLoadError(f"prediction category mismatch for document {document_id}")
        if prediction_set.dataset_version != ground_truth.dataset_version:
            raise DatasetLoadError(f"prediction set {name!r} dataset version does not match")


def load_dataset(path: Path | str) -> LoadedBenchmarkDataset:
    """Load and cross-validate a benchmark directory and its prediction sets."""

    root = _dataset_root(Path(path))
    manifest = _parse(
        BenchmarkManifest,
        _read_json(root, "manifest.json"),
        "manifest.json",
    )
    ground_truth = _parse(
        GroundTruthDataset,
        _read_json(root, manifest.ground_truth_uri),
        manifest.ground_truth_uri,
    )
    if ground_truth.dataset_version != manifest.dataset_version:
        raise DatasetLoadError("manifest and ground-truth dataset versions do not match")
    if ground_truth.schema_version != manifest.schema_version:
        raise DatasetLoadError("manifest and ground-truth schema versions do not match")
    predictions = {
        name: _parse(PredictionDataset, _read_json(root, uri), uri)
        for name, uri in sorted(manifest.prediction_uris.items())
    }
    _validate_loaded_documents(manifest, ground_truth, predictions)
    quality_gates = None
    if manifest.quality_gates_uri:
        from .gates import QualityGateError, load_quality_gate_config

        try:
            quality_gates = load_quality_gate_config(
                _resolve_reference(root, manifest.quality_gates_uri)
            )
        except QualityGateError as exc:
            raise DatasetLoadError("invalid dataset quality-gate configuration") from exc
    return LoadedBenchmarkDataset(
        root=root,
        manifest=manifest,
        ground_truth=ground_truth,
        predictions=predictions,
        quality_gates=quality_gates,
    )
