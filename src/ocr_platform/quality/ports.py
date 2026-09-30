"""Quality evaluation port for reference-backed OCR assessment."""

from __future__ import annotations

from typing import Protocol

from ocr_platform.domain import DocumentResult, QualityAssessment


class QualityEvaluator(Protocol):
    """Provider-neutral aggregation contract for OCR quality evidence."""

    name: str
    version: str

    def evaluate(
        self,
        document: DocumentResult,
        *,
        reference: DocumentResult | None = None,
    ) -> QualityAssessment: ...
