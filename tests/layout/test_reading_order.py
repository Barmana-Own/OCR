from ocr_platform.domain import BlockType, TextType
from ocr_platform.layout import (
    LayoutLine,
    LayoutRegion,
    RegionRouteHint,
    detect_reading_direction,
    order_layout_regions,
)


def _region(
    bbox: tuple[float, float, float, float],
    block_type: BlockType,
    *,
    reading_order: int = 0,
    text_type: TextType = TextType.UNKNOWN,
    lines: tuple[LayoutLine, ...] = (),
) -> LayoutRegion:
    return LayoutRegion(
        bbox=bbox,
        block_type=block_type,
        confidence=0.9,
        reading_order=reading_order,
        route_hint=(
            RegionRouteHint.TABLE
            if block_type is BlockType.TABLE
            else RegionRouteHint.UNKNOWN
        ),
        text_type=text_type,
        lines=lines,
    )


def test_rtl_columns_are_ordered_spatially_without_reversing_text() -> None:
    regions = (
        _region((70, 100, 320, 150), BlockType.MULTI_COLUMN),
        _region((480, 100, 730, 150), BlockType.MULTI_COLUMN),
        _region((70, 180, 320, 230), BlockType.MULTI_COLUMN),
        _region((480, 180, 730, 230), BlockType.MULTI_COLUMN),
    )

    ordered = order_layout_regions(regions, page_width=800, page_height=600, direction="rtl")

    assert [region.bbox[0] for region in ordered] == [480, 480, 70, 70]
    assert [region.reading_order for region in ordered] == [0, 1, 2, 3]


def test_headers_tables_and_footers_have_document_order_and_atomic_tables() -> None:
    regions = (
        _region((0, 570, 800, 590), BlockType.FOOTER),
        _region((0, 10, 800, 35), BlockType.HEADER),
        _region((60, 100, 740, 180), BlockType.PARAGRAPH),
        _region((80, 220, 720, 350), BlockType.TABLE),
        _region((60, 390, 740, 500), BlockType.PARAGRAPH),
    )

    ordered = order_layout_regions(regions, page_width=800, page_height=600)

    assert [region.block_type for region in ordered] == [
        BlockType.HEADER,
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
        BlockType.FOOTER,
    ]
    assert ordered[2].reading_order == 2


def test_mixed_direction_detection_and_line_order_preserve_geometry() -> None:
    line_region = _region(
        (100, 100, 700, 180),
        BlockType.PARAGRAPH,
        lines=(
            LayoutLine((450, 100, 700, 120), text_type=TextType.MIXED),
            LayoutLine((100, 130, 350, 150), text_type=TextType.MIXED),
        ),
    )

    ordered = order_layout_regions(
        (line_region,), page_width=800, page_height=600, direction="rtl"
    )

    assert detect_reading_direction(("شماره Ref", "قرارداد")) == "mixed"
    assert [line.bbox[0] for line in ordered[0].lines] == [450, 100]
    assert ordered[0].lines[0].reading_order == 0


def test_ambiguous_regions_remain_flagged_and_deterministic() -> None:
    ambiguous = LayoutRegion(
        bbox=(200, 200, 400, 300),
        block_type=BlockType.UNKNOWN,
        confidence=0.9,
        reading_order=0,
        needs_review=True,
        uncertainty_flags=("unknown_provider_class",),
    )

    ordered = order_layout_regions((ambiguous,), page_width=800, page_height=600)

    assert ordered[0].needs_review is True
    assert ordered[0].uncertainty_flags == ("unknown_provider_class",)
