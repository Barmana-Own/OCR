"""Typed OCR adapter contracts and backend-specific result records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ocr_platform.domain import (
    BlockType,
    CoordinateSpace,
    ExtractionMethod,
    PolygonPoint,
    TextType,
)


@dataclass(frozen=True)
class OcrRegion:
    region_id: str
    bbox: tuple[float, float, float, float]
    block_type: BlockType
    text_type: TextType
    coordinate_space: CoordinateSpace
    source_uri: str
    tiny_text: bool = False
    language_hint: str | None = None
    reading_order: int = 0
    layout_confidence: float | None = None
    layout_route_hint: str | None = None
    layout_provider_label: str | None = None
    layout_line_bboxes: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class BackendWord:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    reading_order: int
    polygon: tuple[PolygonPoint, ...] | None = None


@dataclass(frozen=True)
class BackendTextLine:
    raw_text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    language: str
    script: str
    text_type: TextType
    polygon: tuple[PolygonPoint, ...] | None = None
    words: tuple[BackendWord, ...] = ()


@dataclass(frozen=True)
class OcrResult:
    backend: str
    model: str
    model_version: str
    method: ExtractionMethod
    confidence_scale: str
    dpi: float | None
    region_scale: float
    preprocess_variant: str
    lines: tuple[BackendTextLine, ...]
    runtime_metadata: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    backend_family: str = "unknown"


class OcrBackend(Protocol):
    name: str
    model: str
    model_version: str
    confidence_scale: str

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult: ...
