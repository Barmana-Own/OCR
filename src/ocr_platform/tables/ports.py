"""Provider-neutral table extraction ports and structured evidence records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ocr_platform.domain import ExtractionMethod, PolygonPoint
from ocr_platform.errors import BackendUnavailableError
from ocr_platform.ocr.models import OcrRegion


@dataclass(frozen=True)
class TableCell:
    row: int
    column: int
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    raw_text: str | None = None
    normalized_text: str | None = None
    language: str = "und"
    script: str = "Unknown"
    polygon: tuple[PolygonPoint, ...] | None = None
    candidates: tuple[TableCellCandidate, ...] = ()


@dataclass(frozen=True)
class TableCellCandidate:
    """One raw alternative retained for table-cell verification."""

    raw_text: str
    confidence: float | None
    reason: str = "alternate"


@dataclass(frozen=True)
class TableResult:
    """Structured table evidence returned by a table adapter."""

    backend: str
    model: str
    model_version: str
    confidence_scale: str
    cells: tuple[TableCell, ...] = ()
    method: ExtractionMethod = ExtractionMethod.TABLE_EXTRACTION
    dpi: float | None = None
    region_scale: float = 1.0
    preprocess_variant: str = "source-render"
    runtime_metadata: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()


class TableExtractionBackend(Protocol):
    name: str
    model: str
    model_version: str

    def extract(
        self, image_bytes: bytes, *, region: OcrRegion
    ) -> TableResult | tuple[TableCell, ...]: ...


class UnavailableTableBackend:
    """Explicit table capability boundary; never flattens or fabricates cells."""

    name = "unavailable"
    model = "none"
    model_version = "none"
    confidence_scale = "none"

    def __init__(self, reason: str = "no table backend configured") -> None:
        self.reason = reason

    def extract(
        self, image_bytes: bytes, *, region: OcrRegion
    ) -> TableResult | tuple[TableCell, ...]:
        raise BackendUnavailableError(self.reason)


def build_table_backend(name: str) -> TableExtractionBackend:
    """Build only real configured adapters; unsupported names fail closed."""

    normalized = name.strip().lower()
    if normalized in {"", "unavailable", "none"}:
        return UnavailableTableBackend("table extraction backend is not configured")
    return UnavailableTableBackend(f"table backend '{name}' is not available in this runtime")


TableBackend = TableExtractionBackend

