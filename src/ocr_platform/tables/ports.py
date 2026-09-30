"""Provider-neutral table extraction ports and structured evidence records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ocr_platform.domain import ExtractionMethod, PolygonPoint, ReviewFlag
from ocr_platform.errors import BackendUnavailableError
from ocr_platform.ocr.models import OcrRegion


@dataclass(frozen=True)
class TableCell:
    """Provider-neutral zero-based table-cell evidence.

    ``row`` and ``column`` are zero-based addresses.  ``bbox`` and ``polygon``
    use the top-left-origin pixel coordinate system of the image passed to the
    backend; the pipeline maps them back to the canonical page coordinates.
    """

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
    """Structured table evidence returned by a table adapter.

    Cell geometry is local to the OCR region until the pipeline applies its
    recorded crop/scale mapping.  Empty or malformed provider output is not a
    successful extraction; callers must validate ``cells`` before assembly.
    ``review_flags`` records structural validation concerns without changing
    the provider's raw warning text.
    """

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
    backend_family: str = "unknown"
    review_flags: tuple[ReviewFlag, ...] = ()


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


def build_table_backend(
    name: str,
    *,
    language: str = "en",
    device: str = "auto",
    model_path: str | None = None,
) -> TableExtractionBackend:
    """Build only real configured adapters; unsupported names fail closed."""

    normalized = name.strip().lower()
    if normalized in {"", "unavailable", "none"}:
        return UnavailableTableBackend("table extraction backend is not configured")
    if normalized in {
        "pp_structure",
        "ppstructure",
        "pp-structure",
        "paddle",
        "paddle_table",
        "paddle-table",
        "paddle_structure",
        "paddle-structure",
    }:
        from .paddle import PaddleStructureTableBackend

        return PaddleStructureTableBackend(
            language=language,
            device=device,
            model_path=model_path,
        )
    return UnavailableTableBackend(f"table backend '{name}' is not available in this runtime")


TableBackend = TableExtractionBackend

