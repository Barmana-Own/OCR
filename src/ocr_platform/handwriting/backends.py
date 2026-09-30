"""Handwriting recognition adapters and explicit capability failures."""

from __future__ import annotations

from ocr_platform.errors import BackendUnavailableError
from ocr_platform.ocr.models import OcrRegion, OcrResult

from .ports import HandwritingBackend


class UnavailableHandwritingBackend:
    """Fail-closed HTR adapter used when no acceptable model is installed."""

    name = "unavailable"
    model = "none"
    model_version = "none"
    confidence_scale = "none"

    def __init__(self, reason: str = "no handwriting backend configured") -> None:
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


def build_handwriting_backend(
    name: str,
    *,
    model_path: str | None = None,
    device: str = "auto",
) -> HandwritingBackend:
    """Return an explicit unavailable adapter until a real HTR adapter is installed."""

    normalized = name.strip().lower()
    if normalized in {"", "unavailable", "none"}:
        return UnavailableHandwritingBackend("handwriting recognition backend is not configured")
    if normalized in {"transformers", "transformers_htr", "htr"}:
        from .transformers import TransformersHandwritingBackend

        return TransformersHandwritingBackend(model_path=model_path, device=device)
    return UnavailableHandwritingBackend(
        f"handwriting backend '{name}' is not available in this runtime"
    )
