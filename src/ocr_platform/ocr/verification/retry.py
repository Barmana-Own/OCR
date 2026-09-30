"""Finite, deterministic retry plans for OCR region recognition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ocr_platform.config.settings import (
    DEFAULT_HIGH_QUALITY_DPI,
    DEFAULT_REGION_SCALE_CANDIDATES,
    DEFAULT_TINY_TEXT_DPI,
)


class RetryStage(StrEnum):
    FIRST_PASS = "first_pass"
    ALTERNATE_PREPROCESSING = "alternate_preprocessing"
    HIGHER_RESOLUTION = "higher_resolution"
    ALTERNATE_SCALE = "alternate_scale"
    ALTERNATE_BACKEND = "alternate_backend"


@dataclass(frozen=True, slots=True)
class RetryAttempt:
    attempt_number: int
    stage: RetryStage
    backend_index: int
    preprocess_variant: str
    dpi: int | None
    region_scale: int


@dataclass(frozen=True, slots=True)
class RetryPlan:
    """Build an ordered plan with a hard upper bound on backend calls."""

    max_attempts: int = 6
    alternate_preprocessing_variants: tuple[str, ...] = ("grayscale", "contrast")
    region_scales: tuple[int, ...] = DEFAULT_REGION_SCALE_CANDIDATES
    high_quality_dpi: int = DEFAULT_HIGH_QUALITY_DPI
    tiny_text_dpi: int = DEFAULT_TINY_TEXT_DPI

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if any(not variant for variant in self.alternate_preprocessing_variants):
            raise ValueError("retry preprocessing variants must not be empty")
        if any(scale < 2 for scale in self.region_scales):
            raise ValueError("retry region scales must be at least 2")
        if self.high_quality_dpi <= 0 or self.tiny_text_dpi < self.high_quality_dpi:
            raise ValueError("retry DPI configuration is invalid")

    def build(self, *, tiny_text: bool, backend_count: int) -> tuple[RetryAttempt, ...]:
        if backend_count < 1:
            return ()
        dpi = self.tiny_text_dpi if tiny_text else self.high_quality_dpi
        candidates: list[RetryAttempt] = [
            RetryAttempt(0, RetryStage.FIRST_PASS, 0, "source-render", None, 1)
        ]
        candidates.extend(
            RetryAttempt(
                0,
                RetryStage.ALTERNATE_PREPROCESSING,
                0,
                variant,
                None,
                1,
            )
            for variant in self.alternate_preprocessing_variants
        )
        candidates.append(RetryAttempt(0, RetryStage.HIGHER_RESOLUTION, 0, "source-render", dpi, 1))
        scale_candidates = tuple(self.region_scales)
        if scale_candidates:
            candidates.append(
                RetryAttempt(
                    0,
                    RetryStage.ALTERNATE_SCALE,
                    0,
                    f"region-scale-{scale_candidates[0]}",
                    None,
                    scale_candidates[0],
                )
            )
        candidates.extend(
            RetryAttempt(0, RetryStage.ALTERNATE_BACKEND, backend_index, "source-render", None, 1)
            for backend_index in range(1, backend_count)
        )
        candidates.extend(
            RetryAttempt(0, RetryStage.ALTERNATE_SCALE, 0, f"region-scale-{scale}", None, scale)
            for scale in scale_candidates[1:]
        )
        return tuple(
            RetryAttempt(
                attempt_number=index + 1,
                stage=attempt.stage,
                backend_index=attempt.backend_index,
                preprocess_variant=attempt.preprocess_variant,
                dpi=attempt.dpi,
                region_scale=attempt.region_scale,
            )
            for index, attempt in enumerate(candidates[: self.max_attempts])
        )


__all__ = ["RetryAttempt", "RetryPlan", "RetryStage"]
