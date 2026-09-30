"""Configuration-backed construction of printed OCR adapters."""

from __future__ import annotations

from ocr_platform.config import Settings
from ocr_platform.ocr.models import OcrBackend

from .tesseract import TesseractBackend
from .unavailable import UnavailableOcrBackend


def build_ocr_backends(settings: Settings) -> tuple[OcrBackend, ...]:
    """Build configured real adapters and fail closed for unsupported names."""

    backends: list[OcrBackend] = []
    language = "+".join(settings.ocr_languages)
    for configured_name in settings.enabled_ocr_backends:
        name = configured_name.strip().lower()
        if name == "tesseract":
            backends.append(
                TesseractBackend(
                    language=language,
                    timeout_seconds=settings.ocr_backend_timeout_seconds,
                )
            )
        else:
            backends.append(
                UnavailableOcrBackend(
                    f"OCR backend '{configured_name}' is not available in this runtime"
                )
            )
    return tuple(backends)
