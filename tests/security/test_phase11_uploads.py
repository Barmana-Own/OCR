from pathlib import Path

import pytest
from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.errors import InvalidDocumentError
from ocr_platform.ingestion import ImageReader


def test_giant_pixel_count_is_rejected_before_image_decode(tmp_path: Path) -> None:
    path = tmp_path / "large.png"
    Image.new("RGB", (20, 20), "white").save(path, format="PNG")

    with pytest.raises(InvalidDocumentError, match="pixel limit"):
        ImageReader(
            Settings(
                environment="test",
                max_render_pixels=100,
                max_page_width=100,
                max_page_height=100,
            )
        ).read(path, source_uri="artifact://doc-large/source/original.bin")
