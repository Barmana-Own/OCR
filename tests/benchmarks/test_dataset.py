from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocr_platform.benchmarks.dataset import DatasetLoadError, load_dataset
from ocr_platform.benchmarks.models import BenchmarkCategory

FIXTURE_ROOT = Path("benchmarks/data")


def test_versioned_synthetic_fixture_covers_all_required_categories() -> None:
    loaded = load_dataset(FIXTURE_ROOT)

    categories = {document.category for document in loaded.ground_truth.documents}

    assert loaded.manifest.dataset_version == "synthetic-phase10-1.0.0"
    assert loaded.quality_gates is not None
    assert len(categories) == len(BenchmarkCategory)
    assert len(loaded.predictions["current"].documents) == len(loaded.ground_truth.documents)


def test_loader_rejects_absolute_or_escaping_references(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset_version": "test-1.0.0",
                "ground_truth_uri": "../outside.json",
                "prediction_uris": {"current": "../outside.json"},
                "documents": [
                    {
                        "document_id": "doc-1",
                        "category": "clean_english",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetLoadError, match="dataset-relative"):
        load_dataset(root)


def test_loader_rejects_mismatched_prediction_document_ids(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    ground_truth = {
        "schema_version": "1.0.0",
        "dataset_version": "test-1.0.0",
        "documents": [
            {
                "document_id": "doc-1",
                "category": "clean_english",
                "source_uri": "synthetic://doc-1",
                "pages": [],
            }
        ],
    }
    predictions = {
        "schema_version": "1.0.0",
        "dataset_version": "test-1.0.0",
        "documents": [
            {
                "document_id": "doc-other",
                "category": "clean_english",
                "pages": [],
            }
        ],
    }
    (root / "ground_truth.json").write_text(json.dumps(ground_truth), encoding="utf-8")
    (root / "predictions.json").write_text(json.dumps(predictions), encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset_version": "test-1.0.0",
                "ground_truth_uri": "ground_truth.json",
                "prediction_uris": {"current": "predictions.json"},
                "documents": [
                    {
                        "document_id": "doc-1",
                        "category": "clean_english",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetLoadError, match="document IDs"):
        load_dataset(root)
