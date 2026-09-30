"""Geometry-only reading-order reconstruction for layout regions and lines."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from ocr_platform.domain import BlockType

from .ports import LayoutLine, LayoutRegion

_RTL_RE = re.compile(r"[\u0590-\u08ff]")
_LTR_RE = re.compile(r"[A-Za-z]")


def detect_reading_direction(texts: Iterable[str]) -> str:
    rtl = sum(len(_RTL_RE.findall(text)) for text in texts)
    ltr = sum(len(_LTR_RE.findall(text)) for text in texts)
    if rtl and ltr:
        return "mixed"
    return "rtl" if rtl else "ltr"


def order_layout_regions(
    regions: Iterable[LayoutRegion],
    *,
    page_width: float,
    page_height: float,
    direction: str = "ltr",
) -> tuple[LayoutRegion, ...]:
    """Return stable block and line order without mutating text content."""

    values = tuple(regions)
    if not values:
        return ()
    rtl = direction.lower() == "rtl"
    leading = tuple(
        region
        for region in values
        if region.block_type in {BlockType.TITLE, BlockType.HEADER}
    )
    trailing = tuple(
        region
        for region in values
        if region.block_type in {BlockType.FOOTER, BlockType.PAGE_NUMBER}
    )
    sidebars = tuple(region for region in values if region.block_type is BlockType.SIDEBAR)
    excluded = set(leading) | set(trailing) | set(sidebars)
    body = tuple(region for region in values if region not in excluded)
    ordered = [*_sort_band(leading, rtl=rtl), *_sort_body(body, page_width, rtl=rtl)]
    ordered.extend(_sort_band(sidebars, rtl=rtl))
    ordered.extend(_sort_band(trailing, rtl=rtl))
    return tuple(
        replace(
            region,
            reading_order=index,
            lines=_order_lines(region.lines, rtl=rtl),
        )
        for index, region in enumerate(ordered)
    )


def estimate_column_count(regions: Iterable[LayoutRegion], *, page_width: float) -> int:
    body = tuple(
        region
        for region in regions
        if region.block_type
        not in {BlockType.TITLE, BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER}
    )
    return max(1, len(_column_groups(body, page_width=page_width)))


def _sort_band(regions: Iterable[LayoutRegion], *, rtl: bool) -> tuple[LayoutRegion, ...]:
    return tuple(
        sorted(
            regions,
            key=lambda region: (
                region.bbox[1],
                -region.bbox[2] if rtl else region.bbox[0],
                region.bbox[0],
            ),
        )
    )


def _sort_body(
    regions: Iterable[LayoutRegion], page_width: float, *, rtl: bool
) -> list[LayoutRegion]:
    columns = _column_groups(tuple(regions), page_width=page_width)
    if not columns:
        return []
    column_order = range(len(columns) - 1, -1, -1) if rtl else range(len(columns))
    ordered: list[LayoutRegion] = []
    for column_index in column_order:
        x0, x1 = columns[column_index]
        members = [
            region
            for region in regions
            if _center(region)[0] >= x0 - 1e-6 and _center(region)[0] <= x1 + 1e-6
        ]
        members.sort(
            key=lambda region: (
                region.bbox[1],
                -region.bbox[2] if rtl else region.bbox[0],
                region.bbox[0],
            )
        )
        ordered.extend(members)
    return ordered


def _column_groups(
    regions: tuple[LayoutRegion, ...], *, page_width: float
) -> list[tuple[float, float]]:
    if not regions:
        return []
    gap = max(8.0, page_width * 0.08)
    ordered = sorted(regions, key=lambda region: (region.bbox[0], region.bbox[2]))
    groups: list[list[float]] = [[ordered[0].bbox[0], ordered[0].bbox[2]]]
    for region in ordered[1:]:
        current = groups[-1]
        if region.bbox[0] - current[1] > gap:
            groups.append([region.bbox[0], region.bbox[2]])
        else:
            current[1] = max(current[1], region.bbox[2])
    return [(group[0], group[1]) for group in groups]


def _order_lines(lines: tuple[LayoutLine, ...], *, rtl: bool) -> tuple[LayoutLine, ...]:
    ordered = sorted(
        lines,
        key=lambda line: (
            line.bbox[1],
            -line.bbox[2] if rtl else line.bbox[0],
            line.bbox[0],
        ),
    )
    return tuple(replace(line, reading_order=index) for index, line in enumerate(ordered))


def _center(region: LayoutRegion) -> tuple[float, float]:
    return ((region.bbox[0] + region.bbox[2]) / 2, (region.bbox[1] + region.bbox[3]) / 2)
