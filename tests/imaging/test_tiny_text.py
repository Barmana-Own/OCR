from io import BytesIO
from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.imaging import PreprocessingService, TinyTextPlanner


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def test_tiny_text_planner_requires_visual_or_first_pass_evidence() -> None:
    planner = TinyTextPlanner(pixel_height_threshold=12, max_region_scale=4)

    ordinary = planner.detect(
        estimated_line_height_px=18,
        first_pass_failed=True,
        text_dense_region=False,
    )
    tiny = planner.detect(
        estimated_line_height_px=5,
        current_dpi=300,
        high_quality_dpi=450,
        tiny_text_dpi=600,
        region_scales=(2, 3, 4),
    )

    assert not ordinary.is_tiny
    assert tiny.is_tiny
    assert tiny.recommended_dpi == 600
    assert tiny.region_scales == (2, 3, 4)
    assert tiny.requires_verification
    assert not tiny.super_resolution_used


def test_tiny_text_recovery_creates_bounded_scaled_variants(tmp_path: Path) -> None:
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    service = PreprocessingService(settings)

    result = service.recover_tiny_text(
        "doc-tiny-phase4",
        1,
        _png(),
        region_bbox=(20, 20, 60, 50),
        input_artifact_uri="artifact://doc-tiny-phase4/pages/page_0001/original_render_300dpi.png",
        current_dpi=300,
        estimated_line_height_px=5,
        text_dense_region=True,
        page_reference_size=(120, 80),
    )

    assert result.decision.is_tiny
    assert len(result.variants) == 3
    assert [variant.region_scale for variant in result.variants] == [2, 3, 4]
    assert all(variant.dpi == 600 for variant in result.variants)
    assert all(variant.mapping_to_source.page_width == 120 for variant in result.variants)
