import pytest

from ocr_platform.errors import InvalidDocumentError
from ocr_platform.imaging import RenderPolicy, bounded_render_dimensions


def test_tiny_text_policy_is_bounded() -> None:
    policy = RenderPolicy()
    assert policy.dpi_for(tiny_text=True) == 600
    assert policy.validate_scale(4) == 4
    with pytest.raises(InvalidDocumentError):
        policy.validate_scale(5)


def test_render_dimensions_reject_large_pages() -> None:
    with pytest.raises(InvalidDocumentError, match="pixel"):
        bounded_render_dimensions(10000, 10000, 600, 1_000_000)
