import json
from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.domain import ExtractionMethod, TextType, VerificationStatus
from ocr_platform.ocr.models import BackendTextLine, OcrRegion, OcrResult
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.storage import LocalArtifactStore


class DisagreeingBackend:
    name = "review-backend"
    model = "review-test"
    model_version = "1"
    confidence_scale = "review-0-1"

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        text = "شماره ۱۲۳" if preprocess_variant == "source-render" else "شماره ۱۲۴"
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
                    raw_text=text,
                    bbox=(10.0, 10.0, 80.0, 28.0),
                    confidence=0.40 if preprocess_variant == "source-render" else 0.96,
                    language="fa",
                    script="Arabic",
                    text_type=TextType.PRINTED,
                ),
            ),
        )


def test_review_artifact_contains_source_bbox_candidates_and_history(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (100, 60), "white").save(source_path, format="PNG")
    original = source_path.read_bytes()
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        max_retries=1,
        verification_max_candidates=3,
    )
    document = DocumentPipeline(settings, backends=(DisagreeingBackend(),)).process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )

    line = document.pages[0].blocks[0].lines[0]
    assert line.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert line.review_artifact_uri is not None
    assert source_path.read_bytes() == original

    store = LocalArtifactStore(settings.storage_root)
    artifact_name = line.review_artifact_uri.removeprefix(f"artifact://{document.id}/")
    payload = json.loads(store.read_bytes(document.id, artifact_name))
    assert payload["source_page_uri"] == line.source.source_uri
    assert payload["bbox"] == line.bbox.as_list()
    assert payload["line_crop_uri"] == line.source.crop_uri
    assert len(payload["candidates"]) == 2
    assert len(payload["verification_history"]) == 2
    assert payload["reason_codes"]
    highlighted_name = payload["highlighted_page_uri"].removeprefix(
        f"artifact://{document.id}/"
    )
    assert store.exists(document.id, highlighted_name)
