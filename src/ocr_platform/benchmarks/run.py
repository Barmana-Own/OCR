"""Command-line entrypoint for stored OCR benchmark evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ocr_platform.config import Settings
from ocr_platform.workers import ProcessingMode

from .comparison import compare_metrics
from .dataset import DatasetLoadError, LoadedBenchmarkDataset, load_dataset
from .gates import QualityGateError, load_quality_gate_config
from .predict import build_prediction_dataset
from .reporting import load_report, write_json_report, write_markdown_report
from .runner import run_benchmark


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate versioned OCR benchmark ground truth and stored candidates."
    )
    parser.add_argument("--dataset", type=Path, required=True, help="Benchmark dataset directory.")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ProcessingMode],
        default=ProcessingMode.BALANCED.value,
        help="Processing policy recorded in the report; --run-pipeline invokes OCR.",
    )
    parser.add_argument(
        "--predictions",
        "--prediction-set",
        dest="prediction_set",
        default="current",
        help="Prediction set name from manifest.json.",
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON report path.")
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Markdown report path; defaults to the JSON path with .md suffix.",
    )
    parser.add_argument("--quality-gates", type=Path, default=None, help="Optional gate JSON file.")
    parser.add_argument(
        "--baseline", type=Path, default=None, help="Optional baseline JSON report."
    )
    parser.add_argument(
        "--comparison-tolerance",
        type=float,
        default=0.0,
        help="Allowed absolute metric regression before a baseline comparison fails.",
    )
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    parser.add_argument("--variant", default=None, help="Human-readable backend/DPI/profile label.")
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Return exit code 2 when a configured gate or baseline comparison fails.",
    )
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="Run the configured OCR pipeline against the ground-truth source files.",
    )
    parser.add_argument(
        "--sources-root",
        type=Path,
        default=None,
        help="Root directory for relative source_uri values in ground truth.",
    )
    parser.add_argument(
        "--prediction-output",
        type=Path,
        default=None,
        help="Optional path for the generated real prediction dataset.",
    )
    parser.add_argument(
        "--require-external-ground-truth",
        action="store_true",
        help="Reject synthetic/fixture ground truth before evaluation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        if args.require_external_ground_truth:
            _require_external_ground_truth(dataset)
        gates = load_quality_gate_config(args.quality_gates) if args.quality_gates else None
        if args.run_pipeline:
            prediction_dataset = build_prediction_dataset(
                dataset.ground_truth,
                settings=Settings.from_env(),
                mode=args.mode,
                source_root=args.sources_root,
            )
            prediction_uri = args.prediction_output or args.output.with_name(
                f"{args.output.stem}-{args.prediction_set}-predictions.json"
            )
            prediction_uri.parent.mkdir(parents=True, exist_ok=True)
            prediction_uri.write_text(
                json.dumps(
                    prediction_dataset.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            dataset = LoadedBenchmarkDataset(
                root=dataset.root,
                manifest=dataset.manifest,
                ground_truth=dataset.ground_truth,
                predictions={
                    **dataset.predictions,
                    args.prediction_set: prediction_dataset,
                },
                quality_gates=dataset.quality_gates,
            )
        report = run_benchmark(
            dataset,
            mode=args.mode,
            prediction_set=args.prediction_set,
            quality_gates=gates,
            iou_threshold=args.iou_threshold,
            variant=args.variant,
        )
        if args.baseline:
            baseline = load_report(args.baseline)
            if baseline.dataset_version != report.dataset_version:
                raise ValueError("baseline and current dataset versions do not match")
            report = report.model_copy(
                update={
                    "comparison": compare_metrics(
                        report.metrics,
                        baseline.metrics,
                        tolerance=args.comparison_tolerance,
                        baseline_report=str(args.baseline),
                    )
                }
            )
        markdown_path = args.markdown_output or args.output.with_suffix(".md")
        write_json_report(report, args.output)
        write_markdown_report(report, markdown_path)
        if args.fail_on_gate and (
            not report.quality_gates.passed
            or (report.comparison is not None and report.comparison.has_regressions)
        ):
            return 2
        return 0
    except (DatasetLoadError, QualityGateError, ValueError, OSError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2


def _require_external_ground_truth(dataset) -> None:
    source = dataset.manifest.ground_truth_source.strip().lower()
    if source in {"synthetic", "fixture", "generated"}:
        raise ValueError(
            "external ground truth is required; manifest marks this dataset as synthetic"
        )
    if all(item.source_uri.startswith("synthetic:") for item in dataset.ground_truth.documents):
        raise ValueError("external ground truth is required; all sources are synthetic URIs")


if __name__ == "__main__":
    raise SystemExit(main())
