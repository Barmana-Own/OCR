"""Configurable, non-destructive benchmark quality gates."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .models import (
    BenchmarkMetrics,
    CategoryMetrics,
    QualityGateConfig,
    QualityGateEvaluation,
    QualityGateResult,
)


class QualityGateError(ValueError):
    """Raised when a gate configuration cannot be loaded or evaluated."""


MAX_QUALITY_GATE_BYTES = 1 * 1024 * 1024


def load_quality_gate_config(path: Path | str) -> QualityGateConfig:
    """Load a JSON gate configuration without changing source data."""

    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise QualityGateError(f"quality-gate file does not exist: {path}")
    if candidate.stat().st_size > MAX_QUALITY_GATE_BYTES:
        raise QualityGateError("quality-gate file exceeds the configured size limit")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        return QualityGateConfig.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise QualityGateError(f"invalid quality-gate file: {path}") from exc


def _category_metrics(metrics: BenchmarkMetrics, category: str) -> CategoryMetrics | None:
    if category == "overall":
        return metrics.overall
    return next((item for item in metrics.categories if item.category == category), None)


def _metric_value(category: CategoryMetrics, metric: str) -> float | None:
    target: object = category
    for part in metric.split("."):
        if not hasattr(target, part):
            raise QualityGateError(f"unknown benchmark metric: {metric}")
        target = getattr(target, part)
    if target is None:
        return None
    if not isinstance(target, (int, float)) or isinstance(target, bool):
        raise QualityGateError(f"benchmark metric is not numeric: {metric}")
    return float(target)


def evaluate_quality_gates(
    metrics: BenchmarkMetrics,
    config: QualityGateConfig | None = None,
) -> QualityGateEvaluation:
    """Evaluate configured thresholds and return evidence instead of mutating metrics."""

    if config is None:
        return QualityGateEvaluation(passed=True)
    results: list[QualityGateResult] = []
    for rule in sorted(config.gates, key=lambda item: (item.category, item.name)):
        category = _category_metrics(metrics, rule.category)
        if category is None:
            results.append(
                QualityGateResult(
                    name=rule.name,
                    metric=rule.metric,
                    category=rule.category,
                    actual=None,
                    minimum=rule.minimum,
                    maximum=rule.maximum,
                    passed=False,
                    reason="category metrics are missing",
                )
            )
            continue
        actual = _metric_value(category, rule.metric)
        passed = (
            actual is not None
            and (rule.minimum is None or actual >= rule.minimum)
            and (rule.maximum is None or actual <= rule.maximum)
        )
        if actual is None:
            reason = "metric is unavailable for this category"
        elif rule.minimum is not None:
            reason = f"{actual:.6g} >= minimum {rule.minimum:.6g}" if passed else (
                f"{actual:.6g} < minimum {rule.minimum:.6g}"
            )
        else:
            reason = f"{actual:.6g} <= maximum {rule.maximum:.6g}" if passed else (
                f"{actual:.6g} > maximum {rule.maximum:.6g}"
            )
        results.append(
            QualityGateResult(
                name=rule.name,
                metric=rule.metric,
                category=rule.category,
                actual=actual,
                minimum=rule.minimum,
                maximum=rule.maximum,
                passed=passed,
                reason=reason,
            )
        )
    return QualityGateEvaluation(passed=all(item.passed for item in results), results=results)
