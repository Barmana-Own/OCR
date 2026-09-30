"""Backward-compatible import facade for the PaddleOCR adapter."""

from .paddle_adapter import PaddleLanguage, PaddleOcrBackend, resolve_paddle_languages

__all__ = ["PaddleLanguage", "PaddleOcrBackend", "resolve_paddle_languages"]
