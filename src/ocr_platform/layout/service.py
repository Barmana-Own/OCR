"""Application service for normalized page layout evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from ocr_platform.domain import BlockType, CoordinateSpace, TextType
from ocr_platform.errors import InvalidDocumentError
from ocr_platform.ingestion.models import NativeTextLine

from .normalization import normalize_layout_region
from .ports import (
    LayoutBackend,
    LayoutLine,
    LayoutRegion,
    LayoutResult,
    LayoutWarning,
    RegionRouteHint,
)
from .reading_order import detect_reading_direction, estimate_column_count, order_layout_regions


@dataclass(frozen=True, slots=True)
class LayoutAnalysisService:
    backend: LayoutBackend
    max_regions: int = 512
    min_confidence: float = 0.35

    def __post_init__(self) -> None:
        if self.max_regions <= 0:
            raise InvalidDocumentError("layout max_regions must be positive")
        if not 0 <= self.min_confidence <= 1:
            raise InvalidDocumentError("layout min_confidence must be between zero and one")

    def analyze(
        self,
        image_bytes: bytes,
        *,
        page_width: float,
        page_height: float,
        coordinate_space: CoordinateSpace = CoordinateSpace.RENDERED_PIXEL,
        direction: str = "ltr",
    ) -> LayoutResult:
        raw_regions = self.backend.detect(
            image_bytes,
            page_width=page_width,
            page_height=page_height,
        )
        if len(raw_regions) > self.max_regions:
            raise InvalidDocumentError("layout backend returned too many regions")
        regions, warnings = self._normalize(
            raw_regions,
            page_width=page_width,
            page_height=page_height,
            coordinate_space=coordinate_space,
        )
        regions = tuple(self._apply_confidence_gate(region) for region in regions)
        ordered = order_layout_regions(
            regions,
            page_width=page_width,
            page_height=page_height,
            direction=direction,
        )
        return LayoutResult(
            backend=self.backend.name,
            model=self.backend.model,
            model_version=self.backend.model_version,
            page_width=page_width,
            page_height=page_height,
            coordinate_space=coordinate_space,
            regions=ordered,
            reading_direction=direction,
            column_count=estimate_column_count(ordered, page_width=page_width),
            warnings=warnings,
        )

    def analyze_native(
        self,
        native_lines: Sequence[NativeTextLine],
        *,
        page_width: float,
        page_height: float,
        coordinate_space: CoordinateSpace = CoordinateSpace.PDF_POINT,
    ) -> LayoutResult:
        grouped: dict[int, list[NativeTextLine]] = defaultdict(list)
        for line in native_lines:
            grouped[line.block_index].append(line)
        direction = detect_reading_direction(line.text for line in native_lines)
        raw_regions: list[LayoutRegion] = []
        for block_index, lines in sorted(grouped.items()):
            ordered_lines = sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))
            layout_lines = tuple(
                LayoutLine(
                    bbox=line.bbox,
                    text_type=TextType.PRINTED,
                    reading_order=index,
                    provider_label="pymupdf_native_line",
                )
                for index, line in enumerate(ordered_lines)
            )
            bbox = _union_bbox(line.bbox for line in layout_lines)
            block_type = _native_block_type(
                bbox,
                len(layout_lines),
                page_width=page_width,
                page_height=page_height,
                text=" ".join(line.text for line in ordered_lines),
            )
            raw_regions.append(
                LayoutRegion(
                    bbox=bbox,
                    block_type=block_type,
                    confidence=1.0,
                    reading_order=block_index,
                    route_hint=RegionRouteHint.PRINTED_TEXT,
                    text_type=TextType.PRINTED,
                    lines=layout_lines,
                    provider_label="pymupdf_native_block",
                )
            )
        regions, warnings = self._normalize(
            raw_regions,
            page_width=page_width,
            page_height=page_height,
            coordinate_space=coordinate_space,
        )
        ordered = order_layout_regions(
            regions,
            page_width=page_width,
            page_height=page_height,
            direction=direction,
        )
        return LayoutResult(
            backend="native-layout",
            model="pymupdf-lines",
            model_version="1",
            page_width=page_width,
            page_height=page_height,
            coordinate_space=coordinate_space,
            regions=ordered,
            reading_direction=direction,
            column_count=estimate_column_count(ordered, page_width=page_width),
            warnings=warnings,
        )

    def _apply_confidence_gate(self, region: LayoutRegion) -> LayoutRegion:
        if region.confidence is None or region.confidence >= self.min_confidence:
            return region
        return replace(
            region,
            needs_review=True,
            uncertainty_flags=tuple(
                dict.fromkeys((*region.uncertainty_flags, "low_layout_confidence"))
            ),
        )

    @staticmethod
    def _normalize(
        raw_regions: Sequence[LayoutRegion],
        *,
        page_width: float,
        page_height: float,
        coordinate_space: CoordinateSpace,
    ) -> tuple[tuple[LayoutRegion, ...], tuple[LayoutWarning, ...]]:
        accepted: list[LayoutRegion] = []
        warnings: list[LayoutWarning] = []
        for index, region in enumerate(raw_regions):
            try:
                accepted.append(
                    normalize_layout_region(
                        region,
                        page_width=page_width,
                        page_height=page_height,
                        coordinate_space=coordinate_space,
                    )
                )
            except InvalidDocumentError as exc:
                warnings.append(
                    LayoutWarning(
                        code="invalid_geometry",
                        message=str(exc),
                        region_id=region.provider_label or f"region-{index}",
                    )
                )
        return tuple(accepted), tuple(warnings)


def _native_block_type(
    bbox: tuple[float, float, float, float],
    line_count: int,
    *,
    page_width: float,
    page_height: float,
    text: str,
) -> BlockType:
    x0, y0, x1, y1 = bbox
    if y0 <= page_height * 0.20:
        return (
            BlockType.TITLE
            if line_count == 1 and (x1 - x0) < page_width * 0.8
            else BlockType.HEADER
        )
    if y1 >= page_height * 0.86:
        stripped = text.strip()
        if line_count == 1 and stripped.isdigit():
            return BlockType.PAGE_NUMBER
        return BlockType.FOOTER
    return BlockType.PARAGRAPH if line_count > 1 else BlockType.TEXT_LINE_GROUP


def _union_bbox(
    boxes: Iterable[tuple[float, float, float, float]]
) -> tuple[float, float, float, float]:
    values = tuple(boxes)
    if not values:
        raise InvalidDocumentError("native layout block has no lines")
    return (
        min(item[0] for item in values),
        min(item[1] for item in values),
        max(item[2] for item in values),
        max(item[3] for item in values),
    )
