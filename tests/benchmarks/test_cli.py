from __future__ import annotations

import json
from pathlib import Path

from ocr_platform.benchmarks.run import main


def test_benchmark_cli_writes_json_and_markdown_without_gpu(tmp_path: Path) -> None:
    output = tmp_path / "benchmark-results.json"
    markdown = tmp_path / "benchmark-results.md"

    exit_code = main(
        [
            "--dataset",
            "benchmarks/data",
            "--mode",
            "accurate",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "accurate"
    assert len(payload["metrics"]["categories"]) == 13
    assert "Benchmark summary" in markdown.read_text(encoding="utf-8")


def test_benchmark_cli_can_fail_non_destructively_on_gate_or_compare_failure(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    gate_config = tmp_path / "gates.json"
    gate_config.write_text(
        '{"schema_version":"1.0.0","gates":[{"name":"impossible","metric":"cer",'
        '"category":"overall","maximum":-1.0}]}',
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--dataset",
                "benchmarks/data",
                "--output",
                str(baseline),
            ]
        )
        == 0
    )

    exit_code = main(
        [
            "--dataset",
            "benchmarks/data",
            "--output",
            str(current),
            "--quality-gates",
            str(gate_config),
            "--baseline",
            str(baseline),
            "--fail-on-gate",
        ]
    )

    assert exit_code == 2
    payload = json.loads(current.read_text(encoding="utf-8"))
    assert payload["quality_gates"]["passed"] is False
    assert payload["comparison"]["has_regressions"] is False


def test_real_benchmark_mode_rejects_synthetic_ground_truth(tmp_path: Path) -> None:
    output = tmp_path / "real.json"
    assert (
        main(
            [
                "--dataset",
                "benchmarks/data",
                "--output",
                str(output),
                "--run-pipeline",
                "--require-external-ground-truth",
            ]
        )
        == 2
    )
    assert not output.exists()
