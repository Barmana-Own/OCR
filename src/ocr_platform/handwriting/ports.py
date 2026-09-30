"""Handwriting recognition port."""

from __future__ import annotations

from typing import Protocol

from ocr_platform.ocr.models import OcrRegion, OcrResult


class HandwritingBackend(Protocol):
    name: str
    model: str
    model_version: str
    confidence_scale: str

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult: ...
