from .factory import build_ocr_backends
from .paddle import PaddleLanguage, PaddleOcrBackend, resolve_paddle_languages
from .tesseract import TesseractBackend
from .unavailable import UnavailableOcrBackend

__all__ = [
    "PaddleOcrBackend",
    "PaddleLanguage",
    "resolve_paddle_languages",
    "TesseractBackend",
    "UnavailableOcrBackend",
    "build_ocr_backends",
]
