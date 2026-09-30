from .factory import build_ocr_backends
from .paddle import PaddleOcrBackend
from .tesseract import TesseractBackend
from .unavailable import UnavailableOcrBackend

__all__ = [
    "PaddleOcrBackend",
    "TesseractBackend",
    "UnavailableOcrBackend",
    "build_ocr_backends",
]
