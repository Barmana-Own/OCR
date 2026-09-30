"""Bounded render and region-scaling policy."""

from __future__ import annotations

from dataclasses import dataclass

from ocr_platform.config.settings import (
    DEFAULT_DEFAULT_DPI,
    DEFAULT_HIGH_QUALITY_DPI,
    DEFAULT_MAX_CROP_PIXELS,
    DEFAULT_MAX_REGION_SCALE,
    DEFAULT_MAX_RENDER_PIXELS,
    DEFAULT_TINY_TEXT_DPI,
)
from ocr_platform.errors import InvalidDocumentError


@dataclass(frozen=True)
class RenderPolicy:
    default_dpi: int = DEFAULT_DEFAULT_DPI
    high_quality_dpi: int = DEFAULT_HIGH_QUALITY_DPI
    tiny_text_dpi: int = DEFAULT_TINY_TEXT_DPI
    max_render_pixels: int = DEFAULT_MAX_RENDER_PIXELS
    max_crop_pixels: int = DEFAULT_MAX_CROP_PIXELS
    max_region_scale: int = DEFAULT_MAX_REGION_SCALE

    def dpi_for(self, *, high_quality: bool = False, tiny_text: bool = False) -> int:
        dpi = self.default_dpi
        if high_quality:
            dpi = self.high_quality_dpi
        if tiny_text:
            dpi = self.tiny_text_dpi
        if dpi <= 0:
            raise InvalidDocumentError("render DPI must be positive")
        return dpi

    def validate_scale(self, scale: int) -> int:
        if not 1 <= scale <= self.max_region_scale:
            raise InvalidDocumentError("region scale exceeds configured limit")
        return scale


def bounded_render_dimensions(
    width: float, height: float, dpi: int, max_pixels: int
) -> tuple[int, int]:
    if width <= 0 or height <= 0 or dpi <= 0 or max_pixels <= 0:
        raise InvalidDocumentError("render dimensions must be positive")
    scale = dpi / 72.0
    render_width = max(1, int(round(width * scale)))
    render_height = max(1, int(round(height * scale)))
    if render_width * render_height > max_pixels:
        raise InvalidDocumentError("render exceeds configured pixel limit")
    return render_width, render_height
