"""Provider-neutral layout adapter contracts and result records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from ocr_platform.domain import BlockType, CoordinateSpace, TextType

LayoutPoint = tuple[float, float]
LayoutBBox = tuple[float, float, float, float]


class RegionRouteHint(StrEnum):
    """Conservative next-stage routing hint for a detected region."""

    PRINTED_TEXT = "printed_text"
    HANDWRITING = "handwriting"
    TABLE = "table"
    FORM = "form"
    FORMULA = "formula"
    IMAGE = "image"
    TINY_TEXT = "tiny_text"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LayoutRegion:
    """Raw or normalized provider-neutral region.

    The first four fields intentionally retain the Phase 1/2 positional
    constructor. Provider-native geometry is kept separately when clipping or
    normalization changes the usable geometry.
    """

    bbox: LayoutBBox
    block_type: BlockType
    confidence: float | None
    reading_order: int
    polygon: tuple[LayoutPoint, ...] | None = None
    provider_polygon: tuple[LayoutPoint, ...] | None = None
    provider_label: str | None = None
    route_hint: RegionRouteHint = RegionRouteHint.UNKNOWN
    text_type: TextType = TextType.UNKNOWN
    tiny_text: bool = False
    coordinate_space: CoordinateSpace = CoordinateSpace.RENDERED_PIXEL
    lines: tuple[LayoutLine, ...] = ()
    needs_review: bool = False
    uncertainty_flags: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LayoutLine:
    """Line-level geometry emitted by a layout backend before OCR text exists."""

    bbox: LayoutBBox
    confidence: float | None = None
    polygon: tuple[LayoutPoint, ...] | None = None
    provider_polygon: tuple[LayoutPoint, ...] | None = None
    text_type: TextType = TextType.UNKNOWN
    tiny_text: bool = False
    reading_order: int = 0
    provider_label: str | None = None
    needs_review: bool = False
    uncertainty_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class LayoutWarning:
    code: str
    message: str
    region_id: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class LayoutResult:
    """Ordered page-level layout evidence and backend provenance."""

    backend: str
    model: str
    model_version: str
    page_width: float
    page_height: float
    coordinate_space: CoordinateSpace
    regions: tuple[LayoutRegion, ...] = ()
    reading_direction: str = "ltr"
    column_count: int = 1
    warnings: tuple[LayoutWarning, ...] = ()
    provider_metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class LayoutBackend(Protocol):
    """Adapter boundary for a real layout detector."""

    name: str
    model: str
    model_version: str

    def detect(
        self, image_bytes: bytes, *, page_width: float, page_height: float
    ) -> tuple[LayoutRegion, ...]: ...


class UnavailableLayoutBackend:
    name = "unavailable"
    model = "none"
    model_version = "none"

    def __init__(self, reason: str = "no layout backend configured") -> None:
        self.reason = reason

    def detect(
        self, image_bytes: bytes, *, page_width: float, page_height: float
    ) -> tuple[LayoutRegion, ...]:
        from ocr_platform.errors import BackendUnavailableError

        raise BackendUnavailableError(self.reason)
