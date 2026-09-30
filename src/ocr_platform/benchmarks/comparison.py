"""Directional comparison of benchmark reports and metric sets."""

from __future__ import annotations

from .models import BenchmarkComparison, BenchmarkMetrics, CategoryMetrics, MetricComparison

_LOWER_IS_BETTER = {"page_cer", "page_wer", "cer", "wer"}
_METRIC_NAMES = (
    "page_cer",
    "page_wer",
    "cer",
    "wer",
    "exact_line_accuracy",
    "line_detection_precision",
    "line_detection_recall",
    "reading_order_accuracy",
    "table_cell_accuracy",
    "accepted_automatically_rate",
    "verification_rate",
    "human_review_rate",
    "backend_disagreement_rate",
    "tiny_text.recovery_improvement",
)


def _categories(metrics: BenchmarkMetrics) -> dict[str, CategoryMetrics]:
    values = {item.category: item for item in metrics.categories}
    if metrics.overall is not None:
        values[metrics.overall.category] = metrics.overall
    return values


def _value(category: CategoryMetrics, metric: str) -> float | None:
    target: object = category
    for part in metric.split("."):
        target = getattr(target, part)
    return float(target) if target is not None else None


def compare_metrics(
    current: BenchmarkMetrics,
    baseline: BenchmarkMetrics,
    *,
    tolerance: float = 0.0,
    baseline_report: str | None = None,
) -> BenchmarkComparison:
    """Compare common category/metric pairs with direction-aware regressions."""

    if tolerance < 0:
        raise ValueError("comparison tolerance cannot be negative")
    current_categories = _categories(current)
    baseline_categories = _categories(baseline)
    comparisons: list[MetricComparison] = []
    for category in sorted(set(current_categories) & set(baseline_categories)):
        current_category = current_categories[category]
        baseline_category = baseline_categories[category]
        for metric in _METRIC_NAMES:
            current_value = _value(current_category, metric)
            baseline_value = _value(baseline_category, metric)
            if current_value is None or baseline_value is None:
                continue
            delta = current_value - baseline_value
            regression = delta > tolerance if metric in _LOWER_IS_BETTER else delta < -tolerance
            comparisons.append(
                MetricComparison(
                    category=category,
                    metric=metric,
                    baseline=baseline_value,
                    current=current_value,
                    delta=delta,
                    regression=regression,
                )
            )
    comparisons.sort(key=lambda item: (item.category, item.metric))
    return BenchmarkComparison(
        baseline_report=baseline_report,
        tolerance=tolerance,
        has_regressions=any(item.regression for item in comparisons),
        metrics=comparisons,
    )
