"""Tiny-text stage metrics that show whether escalation improved evidence."""

from __future__ import annotations

from collections.abc import Iterable

from ocr_platform.quality.metrics import cer

from .models import (
    GroundTruthDocument,
    PredictionDocument,
    PredictionLine,
    TinyTextMetrics,
    TinyTextStage,
)


def _text(value: str, normalized: str | None) -> str:
    return normalized if normalized is not None else value


def _lines_by_id(document: GroundTruthDocument | PredictionDocument) -> dict[str, object]:
    return {
        line.id: line
        for page in document.pages
        for line in page.lines
    }


def _stage_texts(line: PredictionLine) -> dict[TinyTextStage, str]:
    return {
        stage.stage: _text(stage.raw_text, stage.normalized_text)
        for stage in line.tiny_text_stages
    }


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def evaluate_tiny_text(
    reference: GroundTruthDocument,
    prediction: PredictionDocument,
) -> TinyTextMetrics:
    """Compare every reference tiny-text line at all recorded retry stages."""

    predictions = _lines_by_id(prediction)
    stage_values: dict[TinyTextStage, list[float]] = {stage: [] for stage in TinyTextStage}
    count = 0
    for reference_line in (
        line
        for page in reference.pages
        for line in page.lines
        if line.tiny_text
    ):
        count += 1
        candidate = predictions.get(reference_line.id)
        if not isinstance(candidate, PredictionLine):
            continue
        expected = _text(reference_line.raw_text, reference_line.normalized_text)
        for stage, actual in _stage_texts(candidate).items():
            stage_values[stage].append(cer(expected, actual))

    first_pass_cer = _mean(stage_values[TinyTextStage.FIRST_PASS])
    high_dpi_cer = _mean(stage_values[TinyTextStage.HIGH_DPI])
    crop_upscaled_cer = _mean(stage_values[TinyTextStage.CROP_UPSCALED])
    verified_final_cer = _mean(stage_values[TinyTextStage.VERIFIED_FINAL])
    improvement = (
        first_pass_cer - verified_final_cer
        if first_pass_cer is not None and verified_final_cer is not None
        else None
    )
    return TinyTextMetrics(
        count=count,
        first_pass_cer=first_pass_cer,
        high_dpi_cer=high_dpi_cer,
        crop_upscaled_cer=crop_upscaled_cer,
        verified_final_cer=verified_final_cer,
        recovery_improvement=improvement,
    )
