from ocr_platform.domain import ExtractionMethod, TextType
from ocr_platform.ocr.models import BackendTextLine, OcrResult


def test_ocr_result_retains_provider_runtime_evidence_without_normalizing_text() -> None:
    result = OcrResult(
        backend="test-backend",
        model="test-model",
        model_version="2026.09",
        method=ExtractionMethod.OCR,
        confidence_scale="test-0-1",
        dpi=300.0,
        region_scale=1.0,
        preprocess_variant="source-render",
        lines=(
            BackendTextLine(
                raw_text="شماره قرارداد ١٢٣٤٥ / ABC",
                bbox=(1.0, 2.0, 100.0, 20.0),
                confidence=0.91,
                language="fa+en",
                script="Arabic+Latin",
                text_type=TextType.PRINTED,
            ),
        ),
        runtime_metadata=(
            ("device", "cpu"),
            ("engine_version", "test-runtime-1"),
        ),
        warnings=("provider emitted an uncalibrated confidence",),
    )

    assert result.lines[0].raw_text == "شماره قرارداد ١٢٣٤٥ / ABC"
    assert result.runtime_metadata == (("device", "cpu"), ("engine_version", "test-runtime-1"))
    assert result.warnings == ("provider emitted an uncalibrated confidence",)

