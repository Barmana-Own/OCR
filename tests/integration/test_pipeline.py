from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.domain import ExtractionMethod, TextType
from ocr_platform.ocr.models import BackendTextLine, OcrRegion, OcrResult
from ocr_platform.pipeline import DocumentPipeline


class DeterministicBackend:
    name = "test-backend"
    model = "deterministic-test"
    model_version = "1"
    confidence_scale = "test-0-1"

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        return OcrResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            method=ExtractionMethod.OCR,
            confidence_scale=self.confidence_scale,
            dpi=float(dpi),
            region_scale=float(region_scale),
            preprocess_variant=preprocess_variant,
            lines=(
                BackendTextLine(
                    raw_text="شماره قرارداد ١٢٣٤٥",
                    bbox=(10.0, 10.0, 300.0, 40.0),
                    confidence=0.98,
                    language="fa",
                    script="Arabic",
                    text_type=TextType.PRINTED,
                ),
            ),
        )


def test_image_processing_preserves_provenance_and_normalization(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (400, 200), "white").save(source_path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    document = DocumentPipeline(settings, backends=(DeterministicBackend(),)).process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )
    line = document.pages[0].blocks[0].lines[0]
    assert document.source.checksum_sha256
    assert document.pages[0].rendered_uri
    assert line.raw_text == "شماره قرارداد ١٢٣٤٥"
    assert line.normalized_text == "شماره قرارداد ۱۲۳۴۵"
    assert line.source.document_id == document.id
    assert line.source.page_number == 1
    assert line.extraction.backend == "test-backend"
    assert line.verification_history


def test_missing_backend_is_explicit_and_requires_review(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (100, 100), "white").save(source_path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    document = DocumentPipeline(settings, backends=()).process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )
    assert document.status.value == "human_review_required"
    assert document.pages[0].blocks[0].uncertainty_flags
    assert any("no OCR backend" in warning for warning in document.warnings)
