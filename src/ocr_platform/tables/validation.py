"""Deterministic validation for provider-produced table cells.

Table providers are external trust boundaries.  This module accepts only
geometry and addresses that can be represented safely in the local table
coordinate system.  Invalid cells are dropped rather than clipped or
repaired; the returned warnings and review flags make the partial result
auditable and allow the pipeline to fall back to printed OCR when no usable
structure remains.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ocr_platform.domain import ReviewFlag

from .ports import TableCell

MAX_TABLE_INDEX = 100_000
MAX_EMPTY_CELL_RATIO = 0.75
_DUPLICATE_OVERLAP_RATIO = 0.90


@dataclass(frozen=True, slots=True)
class TableValidationResult:
    """Validated provider cells and the evidence needed to interpret them."""

    cells: tuple[TableCell, ...]
    warnings: tuple[str, ...]
    review_flags: tuple[ReviewFlag, ...]
    usable: bool


def validate_table_cells(
    cells: Sequence[TableCell],
    *,
    region_bbox: tuple[float, float, float, float],
) -> TableValidationResult:
    """Validate cells in the local coordinate system of a table crop.

    ``region_bbox`` is used only for its width and height.  Provider cell
    coordinates are expected to start at ``(0, 0)`` in the OCR crop, even when
    the crop itself originated from a non-origin page region.
    """

    warnings: list[str] = []
    flags: list[ReviewFlag] = []
    region_size = _region_size(region_bbox)
    if region_size is None:
        return TableValidationResult(
            cells=(),
            warnings=("invalid_region_geometry: table region bounds are invalid",),
            review_flags=(ReviewFlag.INVALID_GEOMETRY, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN),
            usable=False,
        )
    width, height = region_size

    accepted: list[tuple[int, TableCell, tuple[float, float, float, float]]] = []
    addresses: dict[tuple[int, int], int] = {}
    for index, cell in enumerate(cells):
        address = _cell_address(cell)
        if address is None:
            warnings.append(f"invalid_address: cell {index} has an invalid row or column")
            _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
            continue
        row, column = address
        bbox = _cell_bbox(cell, width=width, height=height)
        if bbox is None:
            warnings.append(f"invalid_geometry: cell {index} is outside table region bounds")
            _add_flag(flags, ReviewFlag.INVALID_GEOMETRY)
            _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
            continue
        if not _valid_polygon(cell.polygon, width=width, height=height):
            warnings.append(f"invalid_geometry: cell {index} polygon is invalid")
            _add_flag(flags, ReviewFlag.INVALID_GEOMETRY)
            _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
            continue
        if not isinstance(cell.text, str) or (
            cell.raw_text is not None and not isinstance(cell.raw_text, str)
        ):
            warnings.append(f"invalid_text: cell {index} text is not a string")
            _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
            continue
        if not _valid_confidence(cell.confidence):
            warnings.append(f"invalid_confidence: cell {index} confidence is outside 0..1")
            _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
            continue
        if address in addresses:
            warnings.append(
                f"duplicate_address: cell {index} duplicates cell {addresses[address]} "
                f"at row {row}, column {column}"
            )
            _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
            continue
        overlap_index = _overlapping_duplicate_index(
            bbox,
            (
                (existing_index, existing_cell, existing_bbox)
                for existing_index, existing_cell, existing_bbox in accepted
            ),
        )
        if overlap_index is not None:
            warnings.append(
                f"overlapping_duplicate: cell {index} overlaps cell {overlap_index} "
                "with near-identical geometry"
            )
            _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
            continue
        addresses[address] = index
        accepted.append((index, cell, bbox))

    accepted.sort(key=lambda item: (item[1].row, item[1].column, item[2][1], item[2][0], item[0]))
    validated_cells = tuple(item[1] for item in accepted)
    non_empty_count = sum(1 for cell in validated_cells if _cell_text(cell).strip())
    empty_count = len(validated_cells) - non_empty_count
    usable = bool(validated_cells) and non_empty_count > 0

    if not validated_cells:
        warnings.append("empty_result: table backend returned no usable cells")
        _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
    elif empty_count / len(validated_cells) > MAX_EMPTY_CELL_RATIO:
        warnings.append(
            "excessive_empty_cells: table backend returned too many empty cell values"
        )
        _add_flag(flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
        usable = False

    return TableValidationResult(
        cells=validated_cells,
        warnings=tuple(warnings),
        review_flags=tuple(flags),
        usable=usable,
    )


def _region_size(
    region_bbox: tuple[float, float, float, float],
) -> tuple[float, float] | None:
    try:
        x0, y0, x1, y1 = (float(value) for value in region_bbox)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x1 - x0, y1 - y0


def _cell_address(cell: TableCell) -> tuple[int, int] | None:
    row = cell.row
    column = cell.column
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_TABLE_INDEX
        for value in (row, column)
    ):
        return None
    return row, column


def _cell_bbox(
    cell: TableCell,
    *,
    width: float,
    height: float,
) -> tuple[float, float, float, float] | None:
    try:
        values = tuple(float(value) for value in cell.bbox)
    except (TypeError, ValueError):
        return None
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        return None
    x0, y0, x1, y1 = values
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0 or x1 > width or y1 > height:
        return None
    return values


def _valid_polygon(
    polygon: Sequence[object] | None,
    *,
    width: float,
    height: float,
) -> bool:
    if polygon is None:
        return True
    if len(polygon) < 3:
        return False
    for point in polygon:
        try:
            x = float(point.x)
            y = float(point.y)
        except (AttributeError, TypeError, ValueError):
            return False
        if not math.isfinite(x) or not math.isfinite(y) or x < 0 or y < 0:
            return False
        if x > width or y > height:
            return False
    return True


def _cell_text(cell: TableCell) -> str:
    return cell.raw_text if cell.raw_text is not None else cell.text


def _valid_confidence(confidence: object) -> bool:
    if confidence is None or isinstance(confidence, bool):
        return confidence is None
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and 0 <= value <= 1


def _overlapping_duplicate_index(
    bbox: tuple[float, float, float, float],
    existing: Iterable[tuple[int, TableCell, tuple[float, float, float, float]]],
) -> int | None:
    for existing_index, _existing_cell, existing_bbox in existing:
        if _overlap_ratio(bbox, existing_bbox) >= _DUPLICATE_OVERLAP_RATIO:
            return existing_index
    return None


def _overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    intersection_width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    intersection_height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    intersection = intersection_width * intersection_height
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    smallest_area = min(first_area, second_area)
    return intersection / smallest_area if smallest_area > 0 else 0.0


def _add_flag(flags: list[ReviewFlag], flag: ReviewFlag) -> None:
    if flag not in flags:
        flags.append(flag)


__all__ = ["TableValidationResult", "validate_table_cells"]
