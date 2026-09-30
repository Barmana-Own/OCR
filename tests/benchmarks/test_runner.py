from __future__ import annotations

import json
from pathlib import Path

from ocr_platform.benchmarks.dataset import load_dataset
from ocr_platform.benchmarks.gates import evaluate_quality_gates
from ocr_platform.benchmarks.models import QualityGateConfig, QualityGateRule
from ocr_platform.benchmarks.reporting import write_json_report, write_markdown_report
from ocr_platform.benchmarks.runner import run_benchmark


def test_runner_records_provenance_metrics_models_and_gate_results(tmp_path: Path) -> None:
    loaded = load_dataset("benchmarks/data")
    gates = QualityGateConfig(
        gates=[
            QualityGateRule(
                name="overall-line-detection",
                metric="line_detection_recall",
                category="overall",
                minimum=1.0,
            )
        ]
    )

    report = run_benchmark(loaded, mode="accurate", quality_gates=gates)

    assert report.dataset_version == "synthetic-phase10-1.0.0"
    assert report.mode == "accurate"
    assert len(report.metrics.categories) == 13
    assert "fixture@1" in report.model_versions
    assert report.quality_gates.passed is True
    assert report.configuration_hash
    assert report.hardware["python"]

    json_path = tmp_path / "result.json"
    markdown_path = tmp_path / "result.md"
    write_json_report(report, json_path)
    write_markdown_report(report, markdown_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["metrics"]["categories"][0]["category"] == "clean_english"
    assert "Category metrics" in markdown
    assert "tiny_text" in markdown


def test_quality_gate_failure_is_explicit_and_non_destructive() -> None:
    loaded = load_dataset("benchmarks/data")
    gates = QualityGateConfig(
        gates=[
            QualityGateRule(
                name="impossible",
                metric="exact_line_accuracy",
                category="overall",
                minimum=1.1,
            )
        ]
    )
    report = run_benchmark(loaded, quality_gates=gates)

    assert report.quality_gates.passed is False
    assert report.quality_gates.results[0].actual <= 1.0
    assert evaluate_quality_gates(report.metrics, gates).passed is False
