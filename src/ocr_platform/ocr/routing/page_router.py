"""Deterministic page/region routing heuristics.

Model-backed layout routing can replace these heuristics through the same
region contract. The heuristic path never claims handwriting/table detection
without evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ocr_platform.domain import BlockType, TextType
from ocr_platform.ingestion.models import NativeTextLine, PageInput
from ocr_platform.layout import LayoutRegion
from ocr_platform.ocr.models import BackendTextLine, OcrRegion


@dataclass(frozen=True)
class RegionDecision:
    requires_ocr: bool
    reason: str
    regions: tuple[OcrRegion, ...] = ()


class PageRouter:
    def __init__(self, *, tiny_line_height_points: float = 7.0) -> None:
        self.tiny_line_height_points = tiny_line_height_points

    def route(
        self,
        page: PageInput,
        *,
        tiny_text_hint: bool = False,
        layout_regions: Sequence[LayoutRegion] = (),
    ) -> RegionDecision:
        if page.native_text_reliable:
            if page.image_regions:
                regions = tuple(
                    OcrRegion(
                        region_id=f"page-{page.page_number}-image-{index}",
                        bbox=bbox,
                        block_type=BlockType.IMAGE,
                        text_type=TextType.UNKNOWN,
                        coordinate_space=page.coordinate_space,
                        source_uri=page.source_uri,
                    )
                    for index, bbox in enumerate(page.image_regions)
                )
                return RegionDecision(True, "native_text_with_image_regions", regions)
            return RegionDecision(False, "reliable_native_text")
        if layout_regions:
            regions = tuple(self._from_layout(page, region) for region in layout_regions)
            if regions:
                return RegionDecision(True, "layout_detected", regions)
        tiny = tiny_text_hint or self._native_lines_are_tiny(page.native_lines)
        block_type = BlockType.TINY_TEXT if tiny else BlockType.PRINTED_TEXT
        region = OcrRegion(
            region_id=f"page-{page.page_number}-region-0",
            bbox=(0.0, 0.0, page.width, page.height),
            block_type=block_type,
            text_type=TextType.UNKNOWN,
            coordinate_space=page.coordinate_space,
            source_uri=page.source_uri,
            tiny_text=tiny,
        )
        return RegionDecision(True, page.native_text_reason or "ocr_required", (region,))

    @staticmethod
    def _from_layout(page: PageInput, region: LayoutRegion) -> OcrRegion:
        return OcrRegion(
            region_id=f"page-{page.page_number}-layout-{region.reading_order}",
            bbox=region.bbox,
            block_type=region.block_type,
            text_type=region.text_type,
            coordinate_space=region.coordinate_space,
            source_uri=page.source_uri,
            tiny_text=region.tiny_text,
            reading_order=region.reading_order,
            layout_confidence=region.confidence,
            layout_route_hint=region.route_hint.value,
            layout_provider_label=region.provider_label,
            layout_line_bboxes=tuple(line.bbox for line in region.lines),
        )

    def _native_lines_are_tiny(self, lines: tuple[NativeTextLine, ...]) -> bool:
        heights = [line.bbox[3] - line.bbox[1] for line in lines if line.bbox[3] > line.bbox[1]]
        return bool(heights) and min(heights) < self.tiny_line_height_points


def sort_reading_order(
    lines: list[BackendTextLine],
    *,
    direction: str = "ltr",
    y_tolerance: float = 8.0,
) -> list[BackendTextLine]:
    """Sort by spatial rows without reversing characters or Unicode strings."""

    if not lines:
        return []
    rows: list[list[BackendTextLine]] = []
    row_centers: list[float] = []
    for line in sorted(lines, key=lambda item: (item.bbox[1], item.bbox[0])):
        center = (line.bbox[1] + line.bbox[3]) / 2
        selected = None
        for index, row_center in enumerate(row_centers):
            if abs(center - row_center) <= y_tolerance:
                selected = index
                break
        if selected is None:
            rows.append([line])
            row_centers.append(center)
        else:
            rows[selected].append(line)
            row_centers[selected] = sum(
                (item.bbox[1] + item.bbox[3]) / 2 for item in rows[selected]
            ) / len(rows[selected])
    ordered: list[BackendTextLine] = []
    for row in sorted(zip(row_centers, rows, strict=True), key=lambda pair: pair[0]):
        _, members = row
        members.sort(key=lambda item: item.bbox[0], reverse=direction.lower() == "rtl")
        ordered.extend(members)
    return ordered
