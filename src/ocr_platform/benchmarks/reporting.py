"""Deterministic JSON and readable Markdown benchmark report writers."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .models import BenchmarkReport

MAX_REPORT_BYTES = 50 * 1024 * 1024


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json_report(report: BenchmarkReport, path: Path | str) -> Path:
    destination = Path(path)
    _ensure_parent(destination)
    payload = report.model_dump(mode="json", exclude_none=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def write_markdown_report(report: BenchmarkReport, path: Path | str) -> Path:
    destination = Path(path)
    _ensure_parent(destination)
    gate_status = "PASS" if report.quality_gates.passed else "FAIL"
    lines = [
        "# Benchmark summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Dataset version | `{report.dataset_version}` |",
        f"| Prediction set | `{report.prediction_set}` |",
        f"| Mode | `{report.mode}` |",
        f"| Configuration hash | `{report.configuration_hash}` |",
        f"| Generated at | `{report.generated_at.isoformat()}` |",
        f"| Quality gates | `{gate_status}` |",
        "",
        "## Category metrics",
        "",
        "| Category | CER | WER | Exact lines | Line precision | Line recall | Order | Tables | "
        "Auto accepted | Verification | Human review | Disagreement | Tiny recovery |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: |",
    ]
    for metric in [*report.metrics.categories, report.metrics.overall]:
        if metric is None:
            continue
        lines.append(
            "| {category} | {cer:.4f} | {wer:.4f} | {exact:.4f} | {precision:.4f} | "
            "{recall:.4f} | {order:.4f} | {table:.4f} | {auto:.4f} | {verification:.4f} | "
            "{review:.4f} | {disagreement:.4f} | {tiny} |".format(
                category=metric.category,
                cer=metric.cer,
                wer=metric.wer,
                exact=metric.exact_line_accuracy,
                precision=metric.line_detection_precision,
                recall=metric.line_detection_recall,
                order=metric.reading_order_accuracy,
                table=metric.table_cell_accuracy,
                auto=metric.accepted_automatically_rate,
                verification=metric.verification_rate,
                review=metric.human_review_rate,
                disagreement=metric.backend_disagreement_rate,
                tiny=(
                    f"{metric.tiny_text.recovery_improvement:.4f}"
                    if metric.tiny_text.recovery_improvement is not None
                    else "n/a"
                ),
            )
        )
    lines.extend(["", "## Model and hardware provenance", ""])
    lines.extend(f"- `{item}`" for item in report.model_versions)
    for name, value in sorted(report.hardware.items()):
        lines.append(f"- {name}: `{value}`")
    if report.comparison is not None:
        lines.extend(
            [
                "",
                "## Baseline comparison",
                "",
                f"Regression detected: `{'YES' if report.comparison.has_regressions else 'NO'}`",
            ]
        )
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def load_report(path: Path | str) -> BenchmarkReport:
    candidate = Path(path)
    try:
        if candidate.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError("benchmark report exceeds the configured size limit")
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        return BenchmarkReport.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid benchmark report: {path}") from exc
