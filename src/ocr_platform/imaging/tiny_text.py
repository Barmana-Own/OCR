"""Conservative tiny-text detection and escalation decisions."""

from __future__ import annotations

from dataclasses import dataclass

from ocr_platform.config.settings import (
    DEFAULT_DEFAULT_DPI,
    DEFAULT_HIGH_QUALITY_DPI,
    DEFAULT_REGION_SCALE_CANDIDATES,
    DEFAULT_TINY_TEXT_DPI,
)
from ocr_platform.errors import InvalidDocumentError


@dataclass(frozen=True, slots=True)
class TinyTextDecision:
    is_tiny: bool
    reasons: tuple[str, ...]
    recommended_dpi: int
    region_scales: tuple[int, ...]
    requires_verification: bool
    super_resolution_used: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "is_tiny": self.is_tiny,
            "reasons": list(self.reasons),
            "recommended_dpi": self.recommended_dpi,
            "region_scales": list(self.region_scales),
            "requires_verification": self.requires_verification,
            "super_resolution_used": self.super_resolution_used,
        }


class TinyTextPlanner:
    """Turn visual/first-pass hints into an explicit, bounded escalation plan."""

    def __init__(self, *, pixel_height_threshold: float = 12.0, max_region_scale: int = 4) -> None:
        if pixel_height_threshold <= 0:
            raise InvalidDocumentError("tiny-text pixel threshold must be positive")
        if max_region_scale < 2:
            raise InvalidDocumentError("tiny-text region scale must support at least 2x")
        self.pixel_height_threshold = pixel_height_threshold
        self.max_region_scale = max_region_scale

    def detect(
        self,
        *,
        estimated_line_height_px: float | None = None,
        detector_box_height_px: float | None = None,
        first_pass_failed: bool = False,
        text_dense_region: bool = False,
        current_dpi: int = DEFAULT_DEFAULT_DPI,
        high_quality_dpi: int = DEFAULT_HIGH_QUALITY_DPI,
        tiny_text_dpi: int = DEFAULT_TINY_TEXT_DPI,
        region_scales: tuple[int, ...] = DEFAULT_REGION_SCALE_CANDIDATES,
    ) -> TinyTextDecision:
        if current_dpi <= 0 or high_quality_dpi <= 0 or tiny_text_dpi <= 0:
            raise InvalidDocumentError("tiny-text DPI values must be positive")
        normalized_scales: set[int] = set()
        for scale in region_scales:
            try:
                normalized = int(scale)
            except (TypeError, ValueError) as exc:
                raise InvalidDocumentError("tiny-text region scales must be integers") from exc
            if 2 <= normalized <= self.max_region_scale:
                normalized_scales.add(normalized)
        candidate_scales = tuple(sorted(normalized_scales))
        if not candidate_scales:
            raise InvalidDocumentError("tiny-text escalation requires a valid region scale")
        reasons: list[str] = []
        if (
            estimated_line_height_px is not None
            and estimated_line_height_px < self.pixel_height_threshold
        ):
            reasons.append("estimated_line_height_below_threshold")
        if (
            detector_box_height_px is not None
            and detector_box_height_px < self.pixel_height_threshold
        ):
            reasons.append("detector_box_below_threshold")
        if first_pass_failed and text_dense_region:
            reasons.append("dense_region_first_pass_failed")
        is_tiny = bool(reasons)
        recommended_dpi = (
            tiny_text_dpi
            if is_tiny and current_dpi < tiny_text_dpi
            else high_quality_dpi
            if is_tiny and current_dpi < high_quality_dpi
            else current_dpi
        )
        return TinyTextDecision(
            is_tiny=is_tiny,
            reasons=tuple(reasons),
            recommended_dpi=recommended_dpi,
            region_scales=candidate_scales if is_tiny else (),
            requires_verification=is_tiny,
        )
