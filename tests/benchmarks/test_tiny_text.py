from __future__ import annotations

from ocr_platform.benchmarks.dataset import load_dataset
from ocr_platform.benchmarks.tiny_text import evaluate_tiny_text


def test_tiny_text_evaluation_reports_each_escalation_stage() -> None:
    loaded = load_dataset("benchmarks/data")
    reference = next(
        document
        for document in loaded.ground_truth.documents
        if document.category.value == "tiny_text"
    )
    prediction = next(
        document
        for document in loaded.predictions["current"].documents
        if document.category.value == "tiny_text"
    )

    result = evaluate_tiny_text(reference, prediction)

    assert result.count == 1
    assert result.first_pass_cer > result.high_dpi_cer
    assert result.high_dpi_cer == result.verified_final_cer
    assert result.recovery_improvement == result.first_pass_cer - result.verified_final_cer
