"""Stable ingestion adapter contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import PageInput, RenderedPage


class PdfExtractor(Protocol):
    """Provider-neutral PDF page inspection contract."""

    backend_name: str

    def extract(
        self,
        source_path: Path,
        *,
        document_id: str,
        source_uri: str,
    ) -> tuple[PageInput, ...]: ...


class PageRenderer(Protocol):
    """Provider-neutral bounded page rendering contract."""

    backend_name: str

    def render_page(
        self,
        source_path: Path,
        *,
        page_number: int,
        dpi: int,
    ) -> RenderedPage: ...
