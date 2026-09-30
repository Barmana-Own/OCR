from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.domain import ExtractionMethod, TextType, VerificationStatus
from ocr_platform.ocr.models import BackendTextLine, BackendWord, OcrRegion, OcrResult
from ocr_platform.pipeline import DocumentPipeline


class LowConfidenceRetryBackend:
    name = "retry-backend"
    model = "retry-test"
    model_version = "1"
    confidence_scale = "test-0-1"

    def __init__(self) -> None:
        self.variants: list[str] = []

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        self.variants.append(preprocess_variant)
        confident = preprocess_variant == "grayscale"
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
                    raw_text="شماره ۱۲۳",
                    bbox=(40.0, 20.0, 80.0, 36.0) if confident else (2.0, 3.0, 10.0, 9.0),
                    confidence=0.97 if confident else 0.25,
                    language="fa",
                    script="Arabic",
                    text_type=TextType.PRINTED,
                    words=(
                        BackendWord(
                            text="شماره",
                            bbox=(40.0, 20.0, 55.0, 36.0),
                            confidence=0.97 if confident else 0.25,
                            reading_order=0,
                        ),
                    ),
                ),
            ),
        )


def test_low_confidence_output_retries_and_preserves_selected_attempt(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (100, 60), "white").save(source_path, format="PNG")
    backend = LowConfidenceRetryBackend()
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        max_retries=1,
    )
    document = DocumentPipeline(settings, backends=(backend,)).process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )
    line = document.pages[0].blocks[0].lines[0]
    assert backend.variants == ["source-render", "grayscale"]
    assert line.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert line.needs_review is True
    assert line.extraction.preprocess_variant == "grayscale"
    assert line.language == "fa"
    assert line.script == "Arabic"
    assert line.bbox.model_dump() == {"x0": 40.0, "y0": 20.0, "x1": 80.0, "y1": 36.0}
    assert line.words[0].normalized_text == "شماره"
    assert len(line.verification_history) == 2
