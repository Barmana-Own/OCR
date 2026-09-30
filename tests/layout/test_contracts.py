import pytest

from ocr_platform.domain import BlockType, CoordinateSpace, TextType
from ocr_platform.errors import InvalidDocumentError
from ocr_platform.layout import (
    LayoutLine,
    LayoutRegion,
    RegionRouteHint,
    map_provider_label,
    normalize_layout_region,
)


def test_provider_labels_map_to_stable_taxonomy_and_route_hints() -> None:
    title = map_provider_label("heading")
    handwriting = map_provider_label("handwritten_text", confidence=0.42)
    unknown = map_provider_label("vendor_future_class")

    assert title.block_type is BlockType.TITLE
    assert title.route_hint is RegionRouteHint.PRINTED_TEXT
    assert handwriting.block_type is BlockType.HANDWRITING
    assert handwriting.route_hint is RegionRouteHint.HANDWRITING
    assert handwriting.needs_review is True
    assert unknown.block_type is BlockType.UNKNOWN
    assert unknown.route_hint is RegionRouteHint.UNKNOWN
    assert unknown.needs_review is True


def test_normalization_clips_geometry_and_preserves_provider_polygon() -> None:
    provider_polygon = ((-5.0, 5.0), (105.0, 5.0), (105.0, 45.0), (-5.0, 45.0))
    region = LayoutRegion(
        bbox=(-5.0, 5.0, 105.0, 45.0),
        block_type=BlockType.PARAGRAPH,
        confidence=0.9,
        reading_order=4,
        polygon=provider_polygon,
        provider_label="paragraph",
        route_hint=RegionRouteHint.PRINTED_TEXT,
        text_type=TextType.PRINTED,
        lines=(
            LayoutLine(
                bbox=(-2.0, 10.0, 104.0, 20.0),
                confidence=0.8,
                text_type=TextType.PRINTED,
            ),
        ),
    )

    normalized = normalize_layout_region(
        region,
        page_width=100,
        page_height=50,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
    )

    assert normalized.bbox == (0.0, 5.0, 100.0, 45.0)
    assert normalized.polygon == ((0.0, 5.0), (100.0, 5.0), (100.0, 45.0), (0.0, 45.0))
    assert normalized.provider_polygon == provider_polygon
    assert normalized.coordinate_space is CoordinateSpace.RENDERED_PIXEL
    assert normalized.lines[0].bbox == (0.0, 10.0, 100.0, 20.0)


def test_normalization_derives_internal_polygon_from_provider_only_geometry() -> None:
    provider_polygon = ((-5.0, 5.0), (105.0, 5.0), (105.0, 45.0), (-5.0, 45.0))
    normalized = normalize_layout_region(
        LayoutRegion(
            bbox=(0.0, 5.0, 100.0, 45.0),
            block_type=BlockType.PARAGRAPH,
            confidence=0.9,
            reading_order=0,
            provider_polygon=provider_polygon,
        ),
        page_width=100,
        page_height=50,
    )

    assert normalized.polygon == ((0.0, 5.0), (100.0, 5.0), (100.0, 45.0), (0.0, 45.0))
    assert normalized.provider_polygon == provider_polygon


def test_normalization_rejects_impossible_geometry() -> None:
    with pytest.raises(InvalidDocumentError):
        normalize_layout_region(
            LayoutRegion(
                bbox=(50.0, 10.0, 20.0, 30.0),
                block_type=BlockType.PARAGRAPH,
                confidence=0.8,
                reading_order=0,
            ),
            page_width=100,
            page_height=100,
        )

    with pytest.raises(InvalidDocumentError):
        normalize_layout_region(
            LayoutRegion(
                bbox=(0.0, 0.0, 20.0, 20.0),
                block_type=BlockType.PARAGRAPH,
                confidence=0.8,
                reading_order=0,
                polygon=((0.0, 0.0), (10.0, 10.0)),
            ),
            page_width=100,
            page_height=100,
        )


def test_layout_region_keeps_legacy_positional_contract() -> None:
    region = LayoutRegion((1.0, 2.0, 30.0, 40.0), BlockType.PRINTED_TEXT, 0.8, 3)

    assert region.bbox == (1.0, 2.0, 30.0, 40.0)
    assert region.reading_order == 3
    assert region.coordinate_space is CoordinateSpace.RENDERED_PIXEL
