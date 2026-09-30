import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ocr_platform.config import Settings
from ocr_platform.errors import InvalidDocumentError
from ocr_platform.imaging import PreprocessingService
from ocr_platform.storage import LocalArtifactStore


def _png(width: int = 100, height: int = 80) -> bytes:
    image = Image.new("RGB", (width, height), (242, 242, 242))
    ImageDraw.Draw(image).rectangle((12, 20, 38, 42), fill=(20, 20, 20))
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def test_preprocessing_service_persists_each_step_and_maps_to_page(tmp_path: Path) -> None:
    source_bytes = _png()
    source_checksum = hashlib.sha256(source_bytes).hexdigest()
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    store = LocalArtifactStore(settings.storage_root)
    store.put_bytes(
        "doc-phase4",
        "pages/page_0001/original_render_300dpi.png",
        source_bytes,
    )
    service = PreprocessingService(settings, artifact_store=store)

    result = service.preprocess(
        "doc-phase4",
        1,
        source_bytes,
        input_artifact_uri="artifact://doc-phase4/pages/page_0001/original_render_300dpi.png",
        input_artifact_checksum=source_checksum,
        profile_name="tiny_text",
        crop_bbox=(10, 20, 30, 40),
        region_scale=2,
        dpi=600,
        page_reference_size=(200, 160),
    )

    assert len(result.transformations) == 5
    assert result.final_artifact.region_scale == 2
    assert result.final_artifact.dpi == 600
    assert result.manifest_uri.endswith("tiny_text-2x-manifest.json")
    assert result.mapping_to_source.map_bbox_to_page((0, 0, 20, 20)) == (
        20.0,
        40.0,
        40.0,
        60.0,
    )
    for transformation in result.transformations:
        artifact_name = transformation.output_artifact.uri.split("/", 3)[-1]
        assert store.exists("doc-phase4", artifact_name)
        assert transformation.input_artifact.uri
        assert transformation.output_artifact.checksum_sha256
    manifest_name = result.manifest_uri.split("/", 3)[-1]
    manifest = json.loads(store.read_bytes("doc-phase4", manifest_name))
    assert manifest["input_artifact"]["checksum_sha256"] == source_checksum
    assert len(manifest["transformations"]) == len(result.transformations)

    # The input bytes remain unchanged and a repeated deterministic run reuses
    # the immutable outputs rather than overwriting them.
    assert source_bytes == store.read_bytes(
        "doc-phase4", "pages/page_0001/original_render_300dpi.png"
    )
    repeated = service.preprocess(
        "doc-phase4",
        1,
        source_bytes,
        input_artifact_uri=result.input_artifact.uri,
        input_artifact_checksum=source_checksum,
        profile_name="tiny_text",
        crop_bbox=(10, 20, 30, 40),
        region_scale=2,
        dpi=600,
        page_reference_size=(200, 160),
    )
    assert repeated.final_artifact.checksum_sha256 == result.final_artifact.checksum_sha256
    assert repeated.manifest_uri == result.manifest_uri


def test_preprocessing_service_rejects_incorrect_input_checksum(tmp_path: Path) -> None:
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")

    with pytest.raises(InvalidDocumentError, match="checksum"):
        PreprocessingService(settings).preprocess(
            "doc-checksum",
            1,
            _png(),
            input_artifact_checksum="0" * 64,
        )
