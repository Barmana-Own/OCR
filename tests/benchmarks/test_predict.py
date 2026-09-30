from __future__ import annotations

from pathlib import Path

from PIL import Image

from ocr_platform.benchmarks.models import BenchmarkCategory
from ocr_platform.benchmarks.predict import document_to_prediction
from ocr_platform.config import Settings
from ocr_platform.domain import VerificationStatus
from ocr_platform.pipeline import DocumentPipeline
from tests.integration.test_pipeline import DeterministicBackend


def test_document_to_prediction_preserves_line_provenance_fields(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (400, 200), "white").save(source, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    document = DocumentPipeline(settings, backends=(DeterministicBackend(),)).process_path(
        source,
        filename=source.name,
        declared_content_type="image/png",
    )
    prediction = document_to_prediction(document, category=BenchmarkCategory.CLEAN_PERSIAN)
    line = prediction.pages[0].lines[0]
    assert line.raw_text == "شماره قرارداد ١٢٣٤٥"
    assert line.backend == "test-backend"
    assert line.configuration_hash == settings.configuration_hash
    assert line.verification_status is VerificationStatus.ACCEPTED
