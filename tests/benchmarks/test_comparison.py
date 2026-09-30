from __future__ import annotations

from ocr_platform.benchmarks.comparison import compare_metrics
from ocr_platform.benchmarks.dataset import load_dataset
from ocr_platform.benchmarks.metrics import evaluate_dataset


def test_comparison_reports_directional_regression_by_category() -> None:
    loaded = load_dataset("benchmarks/data")
    baseline = evaluate_dataset(loaded.ground_truth, loaded.predictions["current"])
    current = baseline.model_copy(deep=True)
    current.categories[0] = current.categories[0].model_copy(
        update={"exact_line_accuracy": 0.25}
    )

    comparison = compare_metrics(current, baseline)
    regression = next(
        item
        for item in comparison.metrics
        if item.category == "clean_english" and item.metric == "exact_line_accuracy"
    )

    assert regression.delta < 0
    assert regression.regression is True
    assert comparison.has_regressions is True
