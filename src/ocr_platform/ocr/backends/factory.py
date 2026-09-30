"""Configuration-backed construction of printed OCR adapters."""

from __future__ import annotations

from ocr_platform.config import Settings
from ocr_platform.ocr.models import OcrBackend

from .paddle import PaddleOcrBackend, resolve_paddle_languages
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
        elif name in {"paddle", "paddleocr"}:
            configured_languages = settings.paddle_languages or settings.ocr_languages
            for paddle_language in resolve_paddle_languages(configured_languages):
                backends.append(
                    PaddleOcrBackend(
                        language=paddle_language.provider,
                        requested_language=paddle_language.requested,
                        language_note=paddle_language.capability_note,
                        device=settings.device,
                        model_path=str(settings.model_path),
                        cache_path=str(settings.cache_path),
                        model_load_mode=settings.model_load_mode,
                        allow_model_downloads=settings.paddle_allow_model_downloads,
                        timeout_seconds=settings.ocr_backend_timeout_seconds,
                        show_log=settings.paddle_show_log,
                    )
                )
        else:
            backends.append(
                UnavailableOcrBackend(
                    f"OCR backend '{configured_name}' is not available in this runtime"
                )
            )
    return tuple(backends)
