from io import BytesIO

from PIL import Image

from ocr_platform.domain import PolygonPoint
from ocr_platform.imaging import map_bbox_to_page, map_polygon_to_page, prepare_image


def _png_bytes(width: int = 100, height: int = 80) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_region_scale_is_bounded_and_geometry_maps_to_page() -> None:
    prepared = prepare_image(
        _png_bytes(),
        region_bbox=(10, 20, 30, 40),
        page_width=100,
        page_height=80,
        variant="region-scale-2",
        max_crop_pixels=10_000,
        max_region_scale=4,
    )
    assert (prepared.width, prepared.height) == (40, 40)
    assert (prepared.offset_x, prepared.offset_y, prepared.scale) == (10, 20, 2)
    assert map_bbox_to_page((4, 6, 20, 30), prepared) == (12.0, 23.0, 20.0, 35.0)
    polygon = map_polygon_to_page((PolygonPoint(x=4, y=6),), prepared)
    assert polygon == (PolygonPoint(x=12, y=23),)
