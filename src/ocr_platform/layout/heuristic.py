"""Bounded Pillow-only layout detection for environments without model weights."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from math import isfinite, sqrt

from PIL import Image, ImageOps

from ocr_platform.domain import BlockType, TextType
from ocr_platform.errors import ImageDecodeError, InvalidDocumentError

from .ports import LayoutLine, LayoutRegion, RegionRouteHint


@dataclass(frozen=True, slots=True)
class HeuristicLayoutConfig:
    max_pixels: int = 4_000_000
    minimum_dark_row_ratio: float = 0.006
    row_gap_pixels: int = 3
    column_gap_ratio: float = 0.08
    tiny_line_height_pixels: float = 8.0
    minimum_line_width_pixels: int = 3


class HeuristicLayoutBackend:
    """Conservative text-structure detector based on projection profiles.

    This is a real, dependency-light production fallback. It detects visual
    line/column structure only; it does not invent text, handwriting labels,
    table cells, or formula semantics that cannot be supported by pixels.
    """

    name = "heuristic-projection"
    model = "pillow-projection"
    model_version = "1"

    def __init__(self, config: HeuristicLayoutConfig | None = None) -> None:
        self.config = config or HeuristicLayoutConfig()
        if self.config.max_pixels <= 0:
            raise InvalidDocumentError("layout max_pixels must be positive")
        if not 0 < self.config.minimum_dark_row_ratio <= 1:
            raise InvalidDocumentError("layout dark-row ratio must be between zero and one")
        if self.config.row_gap_pixels < 0 or self.config.minimum_line_width_pixels <= 0:
            raise InvalidDocumentError("layout pixel thresholds must be valid")

    def detect(
        self, image_bytes: bytes, *, page_width: float, page_height: float
    ) -> tuple[LayoutRegion, ...]:
        if (
            not isfinite(page_width)
            or not isfinite(page_height)
            or page_width <= 0
            or page_height <= 0
        ):
            raise InvalidDocumentError("layout page dimensions must be finite and positive")
        image = self._decode(image_bytes)
        sample, scale_x, scale_y = self._bounded_sample(image)
        pixels = sample.load()
        width, height = sample.size
        threshold = self._dark_threshold(sample)
        row_counts = [
            sum(1 for x in range(width) if pixels[x, y] < threshold) for y in range(height)
        ]
        row_threshold = max(2, int(width * self.config.minimum_dark_row_ratio))
        row_runs = _active_runs(row_counts, threshold=row_threshold, gap=self.config.row_gap_pixels)
        line_boxes = self._line_boxes(
            pixels,
            width,
            row_runs,
            threshold=threshold,
            page_width=page_width,
            page_height=page_height,
            scale_x=scale_x,
            scale_y=scale_y,
        )
        if not line_boxes:
            return ()

        table_bbox = self._table_bbox(row_counts, pixels, width, height, threshold)
        table_region: LayoutRegion | None = None
        if table_bbox is not None:
            table_region = LayoutRegion(
                bbox=self._scale_bbox(table_bbox, scale_x, scale_y),
                block_type=BlockType.TABLE,
                confidence=0.72,
                reading_order=0,
                provider_label="table_grid",
                route_hint=RegionRouteHint.TABLE,
                text_type=TextType.UNKNOWN,
                needs_review=True,
                uncertainty_flags=("table_cells_not_detected",),
                metadata=(("detector", "projection"),),
            )
            line_boxes = [
                item
                for item in line_boxes
                if not _bbox_inside(item[0], self._scale_bbox(table_bbox, scale_x, scale_y))
            ]

        regions = list(self._group_lines(line_boxes, page_width, page_height))
        if table_region is not None:
            regions.append(table_region)
        return tuple(regions)

    @staticmethod
    def _decode(image_bytes: bytes) -> Image.Image:
        try:
            with Image.open(BytesIO(image_bytes)) as opened:
                opened.load()
                return ImageOps.exif_transpose(opened).convert("L")
        except Exception as exc:
            raise ImageDecodeError("layout image could not be decoded") from exc

    def _bounded_sample(self, image: Image.Image) -> tuple[Image.Image, float, float]:
        width, height = image.size
        pixel_count = width * height
        if pixel_count <= 0 or pixel_count > 50_000_000:
            raise InvalidDocumentError("layout image exceeds the safe source pixel limit")
        if pixel_count <= self.config.max_pixels:
            return image, 1.0, 1.0
        factor = sqrt(self.config.max_pixels / pixel_count)
        sample_width = max(1, int(width * factor))
        sample_height = max(1, int(height * factor))
        sample = image.resize((sample_width, sample_height), Image.Resampling.BOX)
        return sample, width / sample_width, height / sample_height

    @staticmethod
    def _dark_threshold(image: Image.Image) -> int:
        histogram = image.histogram()
        total = sum(histogram)
        mean = sum(index * count for index, count in enumerate(histogram)) / max(1, total)
        variance = sum(
            ((index - mean) ** 2) * count for index, count in enumerate(histogram)
        ) / max(1, total)
        contrast = sqrt(max(0.0, variance))
        return max(40, min(220, int(mean - max(10.0, contrast * 0.25))))

    def _line_boxes(
        self,
        pixels,
        width: int,
        row_runs: Iterable[tuple[int, int]],
        *,
        threshold: int,
        page_width: float,
        page_height: float,
        scale_x: float,
        scale_y: float,
    ) -> list[tuple[tuple[float, float, float, float], LayoutLine]]:
        values: list[tuple[tuple[float, float, float, float], LayoutLine]] = []
        for y0, y1 in row_runs:
            column_counts = [
                sum(1 for y in range(y0, y1) if pixels[x, y] < threshold) for x in range(width)
            ]
            column_threshold = max(1, int((y1 - y0) * 0.25))
            runs = _active_runs(
                column_counts,
                threshold=column_threshold,
                gap=max(1, int(width * 0.01)),
            )
            for x0, x1 in runs:
                if x1 - x0 < self.config.minimum_line_width_pixels:
                    continue
                bbox = self._scale_bbox((x0, y0, x1, y1), scale_x, scale_y)
                bbox = (
                    max(0.0, min(page_width, bbox[0])),
                    max(0.0, min(page_height, bbox[1])),
                    max(0.0, min(page_width, bbox[2])),
                    max(0.0, min(page_height, bbox[3])),
                )
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                line = LayoutLine(
                    bbox=bbox,
                    confidence=0.60,
                    text_type=TextType.UNKNOWN,
                    tiny_text=(bbox[3] - bbox[1]) <= self.config.tiny_line_height_pixels,
                    needs_review=True,
                    uncertainty_flags=("text_type_unresolved",),
                )
                values.append((bbox, line))
        return values

    def _group_lines(
        self,
        line_boxes: list[tuple[tuple[float, float, float, float], LayoutLine]],
        page_width: float,
        page_height: float,
    ) -> tuple[LayoutRegion, ...]:
        columns = _column_groups(
            [bbox for bbox, _ in line_boxes],
            page_width=page_width,
            gap_ratio=self.config.column_gap_ratio,
        )
        grouped: list[tuple[int, list[LayoutLine]]] = [(index, []) for index in range(len(columns))]
        for bbox, line in line_boxes:
            center_x = (bbox[0] + bbox[2]) / 2
            column_index = min(
                range(len(columns)),
                key=lambda index: abs(center_x - (columns[index][0] + columns[index][1]) / 2),
            )
            grouped[column_index][1].append(line)

        median_height = _median(line.bbox[3] - line.bbox[1] for _, line in line_boxes)
        regions: list[LayoutRegion] = []
        for column_index, lines in grouped:
            lines.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
            for paragraph in _line_paragraphs(lines):
                bbox = _union_bbox(line.bbox for line in paragraph)
                block_type = _classify_band(
                    bbox,
                    len(paragraph),
                    page_width=page_width,
                    page_height=page_height,
                    median_height=median_height,
                )
                if len(columns) > 1 and block_type not in {
                    BlockType.HEADER,
                    BlockType.FOOTER,
                    BlockType.PAGE_NUMBER,
                    BlockType.TITLE,
                }:
                    block_type = BlockType.MULTI_COLUMN
                tiny = any(line.tiny_text for line in paragraph)
                if tiny:
                    block_type = BlockType.TINY_TEXT
                regions.append(
                    LayoutRegion(
                        bbox=bbox,
                        block_type=block_type,
                        confidence=0.62,
                        reading_order=0,
                        provider_label="text_region",
                        route_hint=RegionRouteHint.TINY_TEXT if tiny else RegionRouteHint.UNKNOWN,
                        text_type=TextType.UNKNOWN,
                        tiny_text=tiny,
                        lines=tuple(
                            _with_reading_order(line, index)
                            for index, line in enumerate(paragraph)
                        ),
                        needs_review=True,
                        uncertainty_flags=("text_type_unresolved",),
                        metadata=(
                            ("detector", "projection"),
                            ("column_index", str(column_index)),
                        ),
                    )
                )
        return tuple(regions)

    @staticmethod
    def _scale_bbox(
        bbox: tuple[float, float, float, float], scale_x: float, scale_y: float
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bbox
        return (x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)

    @staticmethod
    def _table_bbox(row_counts, pixels, width: int, height: int, threshold: int):
        full_rows = [index for index, count in enumerate(row_counts) if count >= width * 0.55]
        full_row_set = set(full_rows)
        column_counts = [
            sum(1 for y in range(height) if pixels[x, y] < threshold) for x in range(width)
        ]
        full_columns = [
            index for index, count in enumerate(column_counts) if count >= height * 0.55
        ]
        full_column_set = set(full_columns)
        if len(
            _active_runs(
                [1 if index in full_row_set else 0 for index in range(height)],
                threshold=1,
                gap=1,
            )
        ) < 2:
            return None
        if len(
            _active_runs(
                [1 if index in full_column_set else 0 for index in range(width)],
                threshold=1,
                gap=1,
            )
        ) < 2:
            return None
        return (min(full_columns), min(full_rows), max(full_columns) + 1, max(full_rows) + 1)


def _active_runs(values: list[int], *, threshold: int, gap: int) -> list[tuple[int, int]]:
    indices = [index for index, value in enumerate(values) if value >= threshold]
    if not indices:
        return []
    runs: list[tuple[int, int]] = []
    start = previous = indices[0]
    for index in indices[1:]:
        if index - previous > gap + 1:
            runs.append((start, previous + 1))
            start = index
        previous = index
    runs.append((start, previous + 1))
    return runs


def _column_groups(
    boxes: list[tuple[float, float, float, float]], *, page_width: float, gap_ratio: float
) -> list[tuple[float, float]]:
    if not boxes:
        return [(0.0, page_width)]
    gap = max(8.0, page_width * gap_ratio)
    ordered = sorted(boxes, key=lambda item: (item[0], item[2]))
    groups: list[list[float]] = [[ordered[0][0], ordered[0][2]]]
    for x0, _, x1, _ in ordered[1:]:
        current = groups[-1]
        if x0 - current[1] > gap:
            groups.append([x0, x1])
        else:
            current[1] = max(current[1], x1)
    return [(values[0], values[1]) for values in groups]


def _line_paragraphs(lines: list[LayoutLine]) -> list[list[LayoutLine]]:
    if not lines:
        return []
    paragraphs: list[list[LayoutLine]] = []
    current = [lines[0]]
    for line in lines[1:]:
        previous = current[-1]
        height = max(previous.bbox[3] - previous.bbox[1], line.bbox[3] - line.bbox[1])
        if line.bbox[1] - previous.bbox[3] <= max(12.0, height * 2.5):
            current.append(line)
        else:
            paragraphs.append(current)
            current = [line]
    paragraphs.append(current)
    return paragraphs


def _classify_band(
    bbox: tuple[float, float, float, float],
    line_count: int,
    *,
    page_width: float,
    page_height: float,
    median_height: float,
) -> BlockType:
    x0, y0, x1, y1 = bbox
    width = x1 - x0
    height = y1 - y0
    if y0 <= page_height * 0.12:
        if (
            line_count == 1
            and page_width * 0.30 <= width <= page_width * 0.80
            and height > median_height * 1.4
        ):
            return BlockType.TITLE
        return BlockType.HEADER
    if y1 >= page_height * 0.86:
        if (
            line_count == 1
            and width <= page_width * 0.25
            and abs((x0 + x1) / 2 - page_width / 2) <= page_width * 0.12
        ):
            return BlockType.PAGE_NUMBER
        return BlockType.FOOTER
    return BlockType.PARAGRAPH if line_count > 1 else BlockType.TEXT_LINE_GROUP


def _bbox_inside(
    bbox: tuple[float, float, float, float], container: tuple[float, float, float, float]
) -> bool:
    return (
        bbox[0] >= container[0]
        and bbox[1] >= container[1]
        and bbox[2] <= container[2]
        and bbox[3] <= container[3]
    )


def _union_bbox(
    boxes: Iterable[tuple[float, float, float, float]]
) -> tuple[float, float, float, float]:
    values = tuple(boxes)
    if not values:
        raise InvalidDocumentError("cannot create a layout region without lines")
    return (
        min(item[0] for item in values),
        min(item[1] for item in values),
        max(item[2] for item in values),
        max(item[3] for item in values),
    )


def _median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 1.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _with_reading_order(line: LayoutLine, reading_order: int) -> LayoutLine:
    return LayoutLine(
        bbox=line.bbox,
        confidence=line.confidence,
        polygon=line.polygon,
        provider_polygon=line.provider_polygon,
        text_type=line.text_type,
        tiny_text=line.tiny_text,
        reading_order=reading_order,
        provider_label=line.provider_label,
        needs_review=line.needs_review,
        uncertainty_flags=line.uncertainty_flags,
    )
