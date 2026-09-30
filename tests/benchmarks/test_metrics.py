from __future__ import annotations

from ocr_platform.benchmarks.dataset import load_dataset
from ocr_platform.benchmarks.metrics import evaluate_category, evaluate_dataset
from ocr_platform.benchmarks.models import BenchmarkCategory
from ocr_platform.domain import BoundingBox


def test_category_metrics_are_separate_and_include_review_disagreement_and_tiny_text() -> None:
    loaded = load_dataset("benchmarks/data")
    ground_truth = loaded.ground_truth
    predictions = loaded.predictions["current"]

    tiny = evaluate_category(
        [
            document
            for document in ground_truth.documents
            if document.category == BenchmarkCategory.TINY_TEXT
        ],
        [
            document
            for document in predictions.documents
            if document.category == BenchmarkCategory.TINY_TEXT
        ],
    )
    handwritten = evaluate_category(
        [
            document
            for document in ground_truth.documents
            if document.category == BenchmarkCategory.HANDWRITTEN_PERSIAN
        ],
        [
            document
            for document in predictions.documents
            if document.category == BenchmarkCategory.HANDWRITTEN_PERSIAN
        ],
    )

    assert tiny.category == BenchmarkCategory.TINY_TEXT.value
    assert tiny.cer == 0.0
    assert tiny.backend_disagreement_rate == 1.0
    assert tiny.tiny_text.count == 1
    assert tiny.tiny_text.recovery_improvement > 0.0
    assert handwritten.human_review_rate == 1.0


def test_dataset_metrics_preserve_category_breakdown_and_macro_overall() -> None:
    loaded = load_dataset("benchmarks/data")

    report = evaluate_dataset(loaded.ground_truth, loaded.predictions["current"])

    assert len(report.categories) == 13
    assert {item.category for item in report.categories} == {
        document.category.value for document in loaded.ground_truth.documents
    }
    assert report.overall is not None
    assert report.overall.category == "overall"
    assert report.overall.document_count == 13


def test_line_detection_and_normalized_text_are_evaluated_independently() -> None:
    loaded = load_dataset("benchmarks/data")
    reference = loaded.ground_truth.documents[2].model_copy(deep=True)
    prediction = loaded.predictions["current"].documents[2].model_copy(deep=True)
    line = prediction.pages[0].lines[0]
    prediction.pages[0].lines[0] = line.model_copy(
        update={
            "raw_text": "شماره قرارداد ١٢٣٤٥ / ABC-42",
            "normalized_text": "شماره قرارداد ۱۲۳۴۵ / ABC-42",
            "bbox": BoundingBox(x0=500, y0=500, x1=600, y1=550),
        }
    )

    metrics = evaluate_category([reference], [prediction])

    assert metrics.cer == 0.0
    assert metrics.line_detection_precision == 0.0
    assert metrics.line_detection_recall == 0.0
