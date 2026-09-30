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
    available = False

    def __init__(self, reason: str = "no handwriting backend configured") -> None:
        self.reason = reason

    @property
    def unavailable_reason(self) -> str:
        return self.reason

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
    model_id: str | None = None,
    processor_id: str | None = None,
    revision: str | None = None,
    model_path: str | None = None,
    device: str = "auto",
    local_files_only: bool = True,
    trust_remote_code: bool = False,
    max_generation_length: int = 256,
    cache_dir: str | None = None,
    language: str = "und",
    script: str = "Unknown",
    max_image_pixels: int = 12_000_000,
    timeout_seconds: int = 120,
) -> HandwritingBackend:
    """Build a configured HTR adapter or an explicit unavailable capability."""

    normalized = name.strip().lower()
    if normalized in {"", "unavailable", "none"}:
        return UnavailableHandwritingBackend("handwriting recognition backend is not configured")
    if normalized in {"transformers", "transformers_htr", "transformers-htr", "trocr", "htr"}:
        from .transformers import TransformersHandwritingBackend

        return TransformersHandwritingBackend(
            model_id=model_id,
            processor_id=processor_id,
            revision=revision,
            model_path=model_path,
            device=device,
            local_files_only=local_files_only,
            trust_remote_code=trust_remote_code,
            max_generation_length=max_generation_length,
            cache_dir=cache_dir,
            language=language,
            script=script,
            max_image_pixels=max_image_pixels,
            timeout_seconds=timeout_seconds,
        )
    return UnavailableHandwritingBackend(
        f"handwriting backend '{name}' is not available in this runtime"
    )
