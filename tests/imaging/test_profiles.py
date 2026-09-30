from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from ocr_platform.errors import InvalidDocumentError
from ocr_platform.imaging import (
    PreprocessingOperation,
    apply_operation,
    builtin_profiles,
    get_profile,
)


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def test_builtin_profiles_are_named_deterministic_and_provider_neutral() -> None:
    first = {name: profile.as_dict() for name, profile in builtin_profiles().items()}
    second = {name: profile.as_dict() for name, profile in builtin_profiles().items()}

    assert first == second
    assert set(first) == {
        "clean_print",
        "mobile_photo",
        "low_contrast",
        "tiny_text",
        "handwriting",
        "binary_scan",
    }
    assert get_profile("tiny_text").steps[0].operation is PreprocessingOperation.GRAYSCALE
    with pytest.raises(InvalidDocumentError):
        get_profile("tiny_text", enabled=("clean_print",))


def test_deskew_is_bounded_and_keeps_geometry_mapping() -> None:
    image = Image.new("RGB", (120, 80), "white")
    ImageDraw.Draw(image).line((10, 50, 110, 42), fill="black", width=2)
    original = _png(image)

    result = apply_operation(
        image,
        PreprocessingOperation.DESKEW,
        parameters={"angle_degrees": 4, "max_angle": 8},
    )

    assert result.image.size == image.size
    assert _png(result.image) != original
    assert result.mapping.map_point_to_source((60, 40))[0] == pytest.approx(60, abs=2)
    assert not result.warnings


def test_crop_scale_and_threshold_operations_do_not_mutate_input() -> None:
    image = Image.new("RGB", (100, 80), (230, 230, 230))
    ImageDraw.Draw(image).rectangle((20, 30, 40, 45), fill=(10, 10, 10))
    original = _png(image)

    cropped = apply_operation(
        image,
        PreprocessingOperation.CROP,
        parameters={"bbox": [10, 20, 50, 60]},
    )
    scaled = apply_operation(
        cropped.image,
        PreprocessingOperation.SCALE,
        parameters={"scale": 3},
    )
    thresholded = apply_operation(
        scaled.image,
        PreprocessingOperation.ADAPTIVE_THRESHOLD,
        parameters={"block_size": 5, "offset": 4},
    )

    assert cropped.image.size == (40, 40)
    assert scaled.image.size == (120, 120)
    assert thresholded.image.size == (120, 120)
    assert _png(image) == original
    assert scaled.mapping.map_bbox_to_source((0, 0, 30, 30)) == (0.0, 0.0, 10.0, 10.0)
    assert cropped.mapping.map_bbox_to_source((0, 0, 10, 10)) == (10.0, 20.0, 20.0, 30.0)


def test_geometry_and_output_limits_fail_closed() -> None:
    image = Image.new("RGB", (20, 20), "white")

    with pytest.raises(InvalidDocumentError):
        apply_operation(
            image,
            PreprocessingOperation.CROP,
            parameters={"bbox": [12, 12, 4, 4]},
        )
    with pytest.raises(InvalidDocumentError):
        apply_operation(
            image,
            PreprocessingOperation.SCALE,
            parameters={"scale": 4},
            max_output_pixels=100,
        )
