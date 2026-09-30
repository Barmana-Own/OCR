"""Explicit unavailable backend; never returns fabricated OCR text."""

from __future__ import annotations

from ocr_platform.errors import BackendUnavailableError

from ..models import OcrRegion, OcrResult


class UnavailableOcrBackend:
    name = "unavailable"
    model = "none"
    model_version = "none"
    confidence_scale = "none"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        raise BackendUnavailableError(self.reason)
