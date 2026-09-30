from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.domain import BlockType, ExtractionMethod, TextType
from ocr_platform.ingestion.models import NativeTextLine
from ocr_platform.layout import LayoutAnalysisService, LayoutRegion, RegionRouteHint
from ocr_platform.ocr.models import BackendTextLine, OcrRegion, OcrResult
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.tables import TableCell, TableResult


class FakeLayoutBackend:
    name = "test-layout"
    model = "deterministic-layout"
    model_version = "1"

    def detect(self, image_bytes: bytes, *, page_width: float, page_height: float):
        return (
            LayoutRegion(
                bbox=(10.0, 10.0, page_width / 2 - 10.0, page_height / 2),
                block_type=BlockType.TITLE,
                confidence=0.95,
                reading_order=0,
                route_hint=RegionRouteHint.PRINTED_TEXT,
                text_type=TextType.PRINTED,
            ),
            LayoutRegion(
                bbox=(
                    page_width / 2 + 10.0,
                    page_height / 2,
                    page_width - 10.0,
                    page_height - 10.0,
                ),
                block_type=BlockType.TABLE,
                confidence=0.88,
                reading_order=1,
                route_hint=RegionRouteHint.TABLE,
            ),
        )


class CapturingBackend:
    name = "test-ocr"
    model = "deterministic"
    model_version = "1"
    confidence_scale = "test-0-1"

    def __init__(self) -> None:
        self.regions: list[OcrRegion] = []

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        self.regions.append(region)
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
                    raw_text="layout handoff",
                    bbox=(5.0, 5.0, 40.0, 20.0),
                    confidence=0.98,
                    language="en",
                    script="Latin",
                    text_type=TextType.PRINTED,
                ),
            ),
        )


class CapturingTableBackend:
    name = "test-table"
    model = "deterministic-table"
    model_version = "1"
    confidence_scale = "test-0-1"

    def __init__(self) -> None:
        self.regions: list[OcrRegion] = []

    def extract(self, image_bytes: bytes, *, region: OcrRegion) -> TableResult:
        self.regions.append(region)
        return TableResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            confidence_scale=self.confidence_scale,
            cells=(TableCell(0, 0, "table", (1.0, 1.0, 30.0, 16.0), 0.98),),
        )


def test_layout_regions_are_handed_to_ocr_before_backend_calls(tmp_path: Path) -> None:
    source_path = tmp_path / "layout.png"
    Image.new("RGB", (200, 120), "white").save(source_path, format="PNG")
    backend = CapturingBackend()
    table_backend = CapturingTableBackend()
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    document = DocumentPipeline(
        settings,
        backends=(backend,),
        table_backend=table_backend,
        layout_service=LayoutAnalysisService(FakeLayoutBackend()),
    ).process_path(
        source_path,
        filename="layout.png",
        declared_content_type="image/png",
    )

    assert [region.block_type for region in backend.regions] == [BlockType.TITLE]
    assert [region.reading_order for region in backend.regions] == [0]
    assert [region.block_type for region in table_backend.regions] == [BlockType.TABLE]
    assert [region.reading_order for region in table_backend.regions] == [1]
    assert [block.block_type for block in document.pages[0].blocks] == [
        BlockType.TITLE,
        BlockType.TABLE,
    ]


def test_layout_service_reconciles_native_lines_before_canonical_blocks() -> None:
    service = LayoutAnalysisService(FakeLayoutBackend())

    result = service.analyze_native(
        (
            NativeTextLine(
                text="Title",
                bbox=(20.0, 20.0, 180.0, 40.0),
                block_index=0,
                line_index=0,
            ),
        ),
        page_width=200,
        page_height=120,
    )

    assert result.backend == "native-layout"
    assert result.regions[0].block_type in {BlockType.TITLE, BlockType.HEADER}
    assert result.regions[0].lines[0].bbox == (20.0, 20.0, 180.0, 40.0)


def test_native_persian_two_column_layout_orders_columns_rtl_without_reversal() -> None:
    service = LayoutAnalysisService(FakeLayoutBackend())
    result = service.analyze_native(
        (
            NativeTextLine("قرارداد", (70.0, 160.0, 320.0, 180.0), 0, 0),
            NativeTextLine("شماره", (480.0, 160.0, 730.0, 180.0), 1, 0),
            NativeTextLine("اول", (70.0, 220.0, 320.0, 240.0), 2, 0),
            NativeTextLine("دوم", (480.0, 220.0, 730.0, 240.0), 3, 0),
        ),
        page_width=800,
        page_height=600,
    )

    assert result.reading_direction == "rtl"
    assert [region.bbox[0] for region in result.regions] == [480.0, 480.0, 70.0, 70.0]


def test_native_english_two_column_layout_orders_columns_ltr() -> None:
    service = LayoutAnalysisService(FakeLayoutBackend())
    result = service.analyze_native(
        (
            NativeTextLine("Contract", (70.0, 160.0, 320.0, 180.0), 0, 0),
            NativeTextLine("Number", (480.0, 160.0, 730.0, 180.0), 1, 0),
            NativeTextLine("First", (70.0, 220.0, 320.0, 240.0), 2, 0),
            NativeTextLine("Second", (480.0, 220.0, 730.0, 240.0), 3, 0),
        ),
        page_width=800,
        page_height=600,
    )

    assert result.reading_direction == "ltr"
    assert [region.bbox[0] for region in result.regions] == [70.0, 70.0, 480.0, 480.0]
