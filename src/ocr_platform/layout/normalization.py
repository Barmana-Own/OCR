"""Validation and clipping of provider layout geometry."""

from __future__ import annotations

import math
from collections.abc import Iterable

from ocr_platform.domain import CoordinateSpace
from ocr_platform.errors import InvalidDocumentError

from .ports import LayoutBBox, LayoutLine, LayoutPoint, LayoutRegion


def normalize_layout_region(
    region: LayoutRegion,
    *,
    page_width: float,
    page_height: float,
    coordinate_space: CoordinateSpace | None = None,
) -> LayoutRegion:
    """Clip valid provider geometry and reject impossible geometry."""

    _validate_page_dimensions(page_width, page_height)
    clipped_bbox = _clip_bbox(region.bbox, page_width, page_height)
    raw_polygon = region.provider_polygon or region.polygon
    normalized_polygon = _normalize_polygon(
        region.polygon or region.provider_polygon,
        page_width,
        page_height,
    )
    if normalized_polygon is not None:
        clipped_bbox = _bounds(normalized_polygon)
    normalized_lines = tuple(
        _normalize_line(line, page_width, page_height) for line in region.lines
    )
    confidence = _validate_confidence(region.confidence)
    return LayoutRegion(
        bbox=clipped_bbox,
        block_type=region.block_type,
        confidence=confidence,
        reading_order=region.reading_order,
        polygon=normalized_polygon,
        provider_polygon=raw_polygon,
        provider_label=region.provider_label,
        route_hint=region.route_hint,
        text_type=region.text_type,
        tiny_text=region.tiny_text,
        coordinate_space=coordinate_space or region.coordinate_space,
        lines=normalized_lines,
        needs_review=region.needs_review,
        uncertainty_flags=region.uncertainty_flags,
        metadata=region.metadata,
    )


def normalize_layout_regions(
    regions: Iterable[LayoutRegion],
    *,
    page_width: float,
    page_height: float,
    coordinate_space: CoordinateSpace | None = None,
) -> tuple[LayoutRegion, ...]:
    return tuple(
        normalize_layout_region(
            region,
            page_width=page_width,
            page_height=page_height,
            coordinate_space=coordinate_space,
        )
        for region in regions
    )


def _normalize_line(line: LayoutLine, page_width: float, page_height: float) -> LayoutLine:
    bbox = _clip_bbox(line.bbox, page_width, page_height)
    raw_polygon = line.provider_polygon or line.polygon
    polygon = _normalize_polygon(
        line.polygon or line.provider_polygon,
        page_width,
        page_height,
    )
    if polygon is not None:
        bbox = _bounds(polygon)
    return LayoutLine(
        bbox=bbox,
        confidence=_validate_confidence(line.confidence),
        polygon=polygon,
        provider_polygon=raw_polygon,
        text_type=line.text_type,
        tiny_text=line.tiny_text,
        reading_order=line.reading_order,
        provider_label=line.provider_label,
        needs_review=line.needs_review,
        uncertainty_flags=line.uncertainty_flags,
    )


def _validate_page_dimensions(width: float, height: float) -> None:
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise InvalidDocumentError("layout page dimensions must be finite and positive")


def _validate_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value < 0 or value > 1:
        raise InvalidDocumentError("layout confidence must be between zero and one")
    return float(value)


def _clip_bbox(bbox: LayoutBBox, page_width: float, page_height: float) -> LayoutBBox:
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
        raise InvalidDocumentError("layout bbox must contain four finite coordinates")
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        raise InvalidDocumentError("layout bbox must have positive area")
    clipped = (
        max(0.0, min(page_width, float(x0))),
        max(0.0, min(page_height, float(y0))),
        max(0.0, min(page_width, float(x1))),
        max(0.0, min(page_height, float(y1))),
    )
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise InvalidDocumentError("layout bbox has no visible page area")
    return clipped


def _normalize_polygon(
    polygon: tuple[LayoutPoint, ...] | None, page_width: float, page_height: float
) -> tuple[LayoutPoint, ...] | None:
    if polygon is None:
        return None
    if len(polygon) < 3:
        raise InvalidDocumentError("layout polygon must contain at least three points")
    clipped: list[LayoutPoint] = []
    for x, y in polygon:
        if not math.isfinite(x) or not math.isfinite(y):
            raise InvalidDocumentError("layout polygon coordinates must be finite")
        clipped.append(
            (
                max(0.0, min(page_width, float(x))),
                max(0.0, min(page_height, float(y))),
            )
        )
    if abs(_signed_area(clipped)) < 1e-6:
        raise InvalidDocumentError("layout polygon must enclose a non-zero area")
    return tuple(clipped)


def _signed_area(points: Iterable[LayoutPoint]) -> float:
    values = tuple(points)
    return 0.5 * sum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(values, values[1:] + values[:1], strict=True)
    )


def _bounds(points: Iterable[LayoutPoint]) -> LayoutBBox:
    values = tuple(points)
    if not values:
        raise InvalidDocumentError("layout geometry has no points")
    return (
        min(point[0] for point in values),
        min(point[1] for point in values),
        max(point[0] for point in values),
        max(point[1] for point in values),
    )
