from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from ocr_platform.imaging import CoordinateMapping, ImageQualityAnalyzer


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def test_quality_analyzer_returns_bounded_deterministic_signals() -> None:
    image = Image.new("RGB", (160, 100), (242, 242, 242))
    draw = ImageDraw.Draw(image)
    for y in range(20, 81, 12):
        draw.line((15, y, 145, y), fill=(20, 20, 20), width=2)

    analyzer = ImageQualityAnalyzer()
    first = analyzer.analyze(_png(image))
    second = analyzer.analyze(_png(image))

    assert first == second
    assert (first.width, first.height, first.pixel_count) == (160, 100, 16_000)
    assert 0 <= first.brightness <= 255
    assert first.contrast >= 0
    assert first.sharpness >= 0
    assert first.blur_score is not None
    assert first.background_variation is not None
    assert first.estimated_text_scale is not None
    assert first.perspective_distortion_score is not None


def test_quality_analyzer_flags_low_contrast_and_tiny_text() -> None:
    image = Image.new("L", (240, 120), 220)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 50, 200, 52), fill=200)

    metrics = ImageQualityAnalyzer().analyze(_png(image))

    assert metrics.contrast < 10
    assert "low_contrast" in metrics.quality_flags
    assert "tiny_text_suspected" in metrics.quality_flags


def test_quality_analyzer_estimates_synthetic_skew_as_a_hint() -> None:
    image = Image.new("L", (240, 120), 255)
    draw = ImageDraw.Draw(image)
    for y in range(25, 100, 15):
        draw.line((20, y, 220, y), fill=0, width=2)
    rotated = image.rotate(4, expand=False, fillcolor=255)

    metrics = ImageQualityAnalyzer().analyze(_png(rotated))

    assert metrics.skew_angle_degrees == pytest.approx(-4.0, abs=0.75)


def test_coordinate_mapping_maps_crops_scales_and_page_coordinates() -> None:
    mapping = CoordinateMapping.for_source(
        source_width=100,
        source_height=80,
        output_width=40,
        output_height=40,
        output_to_source=(0.5, 0, 10, 0, 0.5, 20, 0, 0, 1),
        page_reference_size=(200, 160),
    )

    assert mapping.map_bbox_to_source((4, 6, 20, 30)) == (12.0, 23.0, 20.0, 35.0)
    assert mapping.map_bbox_to_page((4, 6, 20, 30)) == (24.0, 46.0, 40.0, 70.0)
    assert mapping.as_dict()["output_to_source"] == [0.5, 0, 10, 0, 0.5, 20, 0, 0, 1]
