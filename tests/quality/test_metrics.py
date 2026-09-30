import pytest

from ocr_platform.quality import (
    exact_match_accuracy,
    line_detection_precision_recall,
    reading_order_accuracy,
    review_rate,
    tiny_text_recovery_rate,
)


def test_quality_metric_hooks_cover_geometry_order_and_review_rates() -> None:
    precision, recall = line_detection_precision_recall(
        [(0, 0, 10, 10), (40, 40, 50, 50)],
        [(0, 0, 10, 10)],
    )
    assert precision == 0.5
    assert recall == 1.0
    assert reading_order_accuracy(["a", "b"], ["a", "b"]) == 1.0
    assert exact_match_accuracy(["a", "x"], ["a", "b"]) == 0.5
    assert review_rate(1, 4) == 0.25
    assert tiny_text_recovery_rate(2, 4) == 0.5


def test_quality_metric_hooks_reject_invalid_rates() -> None:
    with pytest.raises(ValueError):
        review_rate(2, 1)
    with pytest.raises(ValueError):
        tiny_text_recovery_rate(3, 2)
