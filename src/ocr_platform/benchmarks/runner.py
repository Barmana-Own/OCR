"""Stored-candidate benchmark execution with provenance metadata."""

from __future__ import annotations

import platform
from datetime import UTC, datetime

from ocr_platform.config import Settings
from ocr_platform.utils.hashes import stable_hash
from ocr_platform.workers import ProcessingMode, ProcessingModePolicy

from .dataset import LoadedBenchmarkDataset
from .gates import evaluate_quality_gates
from .metrics import evaluate_dataset
from .models import BenchmarkReport, QualityGateConfig


def _model_versions(dataset: LoadedBenchmarkDataset, prediction_set: str) -> list[str]:
    values: set[str] = set()
    for document in dataset.predictions[prediction_set].documents:
        for page in document.pages:
            for line in page.lines:
                if line.model and line.model_version:
                    values.add(f"{line.model}@{line.model_version}")
                elif line.backend and line.model_version:
                    values.add(f"{line.backend}@{line.model_version}")
            for cell in page.table_cells:
                if cell.backend:
                    values.add(cell.backend)
    return sorted(values)


def _hardware() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine() or "unknown",
        "processor": platform.processor() or "unknown",
    }


def run_benchmark(
    dataset: LoadedBenchmarkDataset,
    *,
    mode: ProcessingMode | str = ProcessingMode.BALANCED,
    prediction_set: str = "current",
    quality_gates: QualityGateConfig | None = None,
    iou_threshold: float = 0.5,
    variant: str | None = None,
    settings: Settings | None = None,
    generated_at: datetime | None = None,
) -> BenchmarkReport:
    """Evaluate one stored prediction set; no OCR provider is invoked here."""

    if prediction_set not in dataset.predictions:
        raise ValueError(f"prediction set does not exist: {prediction_set}")
    selected_mode = ProcessingMode(mode)
    base_settings = settings or Settings.from_env()
    effective_settings = ProcessingModePolicy.for_mode(base_settings, selected_mode).settings
    metrics = evaluate_dataset(
        dataset.ground_truth,
        dataset.predictions[prediction_set],
        iou_threshold=iou_threshold,
    )
    dataset_hash = stable_hash(
        {
            "manifest": dataset.manifest.model_dump(mode="json"),
            "ground_truth": dataset.ground_truth.model_dump(mode="json"),
        }
    )
    selected_gates = quality_gates if quality_gates is not None else dataset.quality_gates
    return BenchmarkReport(
        schema_version=dataset.manifest.schema_version,
        dataset_version=dataset.manifest.dataset_version,
        dataset_hash=dataset_hash,
        prediction_set=prediction_set,
        variant=variant or prediction_set,
        mode=selected_mode.value,
        generated_at=generated_at or datetime.now(UTC),
        configuration_hash=effective_settings.configuration_hash,
        model_versions=_model_versions(dataset, prediction_set),
        hardware=_hardware(),
        metrics=metrics,
        quality_gates=evaluate_quality_gates(metrics, selected_gates),
    )
