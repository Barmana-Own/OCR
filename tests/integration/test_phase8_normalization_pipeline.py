from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.normalization import DigitPolicy, NormalizationConfig
from ocr_platform.pipeline import DocumentPipeline
from tests.integration.test_pipeline import DeterministicBackend


def test_pipeline_uses_configured_normalization_without_mutating_raw_text(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (300, 150), "white").save(source_path, format="PNG")
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        normalization=NormalizationConfig(digit_policy=DigitPolicy.ASCII),
    )

    document = DocumentPipeline(settings, backends=(DeterministicBackend(),)).process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )
    line = document.pages[0].blocks[0].lines[0]

    assert line.raw_text == "شماره قرارداد ١٢٣٤٥"
    assert line.normalized_text == "شماره قرارداد 12345"
    assert document.normalization_policy == settings.normalization.to_payload()
