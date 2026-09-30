from ocr_platform.domain import BlockType, CoordinateSpace, TextType
from ocr_platform.ocr.models import OcrRegion
from ocr_platform.ocr.routing import RegionRoute, RegionRouter


def _region(
    *,
    block_type: BlockType = BlockType.PRINTED_TEXT,
    text_type: TextType = TextType.UNKNOWN,
    route_hint: str | None = None,
) -> OcrRegion:
    return OcrRegion(
        region_id="phase6-region",
        bbox=(0.0, 0.0, 100.0, 80.0),
        block_type=block_type,
        text_type=text_type,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        source_uri="artifact://doc/page-1.png",
        layout_route_hint=route_hint,
    )


def test_region_router_sends_printed_text_to_printed_ocr_only() -> None:
    decision = RegionRouter().route(_region(block_type=BlockType.PARAGRAPH))

    assert decision.routes == (RegionRoute.PRINTED,)
    assert decision.reason == "printed_text"


def test_region_router_sends_handwriting_to_htr_without_printed_fallback() -> None:
    decision = RegionRouter().route(
        _region(block_type=BlockType.HANDWRITING, text_type=TextType.HANDWRITTEN)
    )

    assert decision.routes == (RegionRoute.HANDWRITING,)


def test_region_router_preserves_tables_as_structured_route() -> None:
    decision = RegionRouter().route(_region(block_type=BlockType.TABLE, route_hint="table"))

    assert decision.routes == (RegionRoute.TABLE,)


def test_region_router_runs_both_capabilities_for_mixed_forms() -> None:
    decision = RegionRouter().route(
        _region(block_type=BlockType.FORM, text_type=TextType.MIXED, route_hint="form")
    )

    assert decision.routes == (RegionRoute.PRINTED, RegionRoute.HANDWRITING)
    assert decision.requires_handwriting is True

