from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.domain import (
    BlockType,
    CoordinateSpace,
    ExtractionMethod,
    TextType,
)
from ocr_platform.errors import ProcessingError
from ocr_platform.layout import LayoutLine, LayoutRegion, LayoutResult, RegionRouteHint
from ocr_platform.ocr.models import BackendTextLine, OcrRegion, OcrResult
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.tables import TableCell, TableResult


class FixedLayoutService:
    def __init__(self, regions: tuple[LayoutRegion, ...]) -> None:
        self.regions = regions

    def analyze(self, image_bytes: bytes, **kwargs) -> LayoutResult:
        return LayoutResult(
            backend="test-layout",
            model="fixed",
            model_version="1",
            page_width=kwargs["page_width"],
            page_height=kwargs["page_height"],
            coordinate_space=CoordinateSpace.RENDERED_PIXEL,
            regions=self.regions,
        )


class PrintedBackend:
    name = "printed-test"
    model = "printed-model"
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
                    raw_text="شماره ABC123",
                    bbox=(4.0, 4.0, 120.0, 24.0),
                    confidence=0.97,
                    language="fa+en",
                    script="Arabic+Latin",
                    text_type=TextType.PRINTED,
                ),
            ),
            runtime_metadata=(("device", "test"),),
        )


class HandwritingBackend:
    name = "handwriting-test"
    model = "htr-model"
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
            method=ExtractionMethod.HANDWRITING_RECOGNITION,
            confidence_scale=self.confidence_scale,
            dpi=float(dpi),
            region_scale=float(region_scale),
            preprocess_variant=preprocess_variant,
            lines=(
                BackendTextLine(
                    raw_text="دستخط تست",
                    bbox=(5.0, 5.0, 90.0, 25.0),
                    confidence=0.96,
                    language="fa",
                    script="Arabic",
                    text_type=TextType.HANDWRITTEN,
                ),
            ),
        )


class TableBackend:
    name = "table-test"
    model = "table-model"
    model_version = "1"
    confidence_scale = "test-0-1"

    def extract(self, image_bytes: bytes, *, region: OcrRegion) -> TableResult:
        return TableResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            confidence_scale=self.confidence_scale,
            cells=(
                TableCell(
                    row=0,
                    column=0,
                    text="نام",
                    bbox=(5.0, 5.0, 80.0, 25.0),
                    confidence=0.95,
                    language="fa",
                    script="Arabic",
                ),
                TableCell(
                    row=0,
                    column=1,
                    text="Alice",
                    bbox=(85.0, 5.0, 160.0, 25.0),
                    confidence=0.96,
                    language="en",
                    script="Latin",
                ),
            ),
            runtime_metadata=(("device", "test"),),
        )


class FailingPrintedBackend(PrintedBackend):
    name = "failing-printed-test"

    def recognize(self, *args, **kwargs) -> OcrResult:
        raise ProcessingError("test backend timed out", retryable=True)


def _layout_regions() -> tuple[LayoutRegion, ...]:
    return (
        LayoutRegion(
            bbox=(0.0, 0.0, 150.0, 70.0),
            block_type=BlockType.PRINTED_TEXT,
            confidence=0.99,
            reading_order=0,
            route_hint=RegionRouteHint.PRINTED_TEXT,
            text_type=TextType.PRINTED,
            lines=(LayoutLine((0.0, 0.0, 150.0, 70.0)),),
        ),
        LayoutRegion(
            bbox=(150.0, 0.0, 300.0, 70.0),
            block_type=BlockType.HANDWRITING,
            confidence=0.91,
            reading_order=1,
            route_hint=RegionRouteHint.HANDWRITING,
            text_type=TextType.HANDWRITTEN,
            lines=(LayoutLine((150.0, 0.0, 300.0, 70.0), text_type=TextType.HANDWRITTEN),),
        ),
        LayoutRegion(
            bbox=(0.0, 80.0, 300.0, 180.0),
            block_type=BlockType.TABLE,
            confidence=0.93,
            reading_order=2,
            route_hint=RegionRouteHint.TABLE,
        ),
    )


def test_mixed_document_uses_route_specific_adapters_and_preserves_structure(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "mixed.png"
    Image.new("RGB", (300, 180), "white").save(source_path, format="PNG")
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        max_retries=0,
    )
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        handwriting_backends=(HandwritingBackend(),),
        table_backend=TableBackend(),
        layout_service=FixedLayoutService(_layout_regions()),
    ).process_path(source_path, filename="mixed.png", declared_content_type="image/png")

    assert [block.block_type for block in document.pages[0].blocks] == [
        BlockType.PRINTED_TEXT,
        BlockType.HANDWRITING,
        BlockType.TABLE,
    ]
    printed, handwriting, table = document.pages[0].blocks
    assert printed.lines[0].raw_text == "شماره ABC123"
    assert printed.lines[0].candidates
    assert handwriting.lines[0].raw_text == "دستخط تست"
    assert handwriting.lines[0].extraction.method == ExtractionMethod.HANDWRITING_RECOGNITION
    assert [cell.raw_text for cell in table.table_cells] == ["نام", "Alice"]
    assert table.lines == []
    assert table.table_cells[0].row == 0
    assert table.table_cells[1].column == 1
    assert document.pages[0].blocks[0].source.crop_uri


def test_handwriting_region_does_not_fall_back_to_printed_ocr(tmp_path: Path) -> None:
    source_path = tmp_path / "handwriting.png"
    Image.new("RGB", (120, 80), "white").save(source_path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        layout_service=FixedLayoutService(
            (
                LayoutRegion(
                    bbox=(0.0, 0.0, 120.0, 80.0),
                    block_type=BlockType.HANDWRITING,
                    confidence=0.9,
                    reading_order=0,
                    route_hint=RegionRouteHint.HANDWRITING,
                    text_type=TextType.HANDWRITTEN,
                ),
            )
        ),
    ).process_path(
        source_path,
        filename="handwriting.png",
        declared_content_type="image/png",
    )

    block = document.pages[0].blocks[0]
    assert block.lines == []
    assert block.needs_review is True
    assert any("handwriting" in warning for warning in document.warnings)
    assert all(line.extraction.method != ExtractionMethod.OCR for line in block.lines)


def test_printed_backend_failure_is_preserved_as_review_warning(tmp_path: Path) -> None:
    source_path = tmp_path / "failure.png"
    Image.new("RGB", (120, 80), "white").save(source_path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(FailingPrintedBackend(),),
        layout_service=FixedLayoutService(
            (
                LayoutRegion(
                    bbox=(0.0, 0.0, 120.0, 80.0),
                    block_type=BlockType.PRINTED_TEXT,
                    confidence=0.9,
                    reading_order=0,
                    route_hint=RegionRouteHint.PRINTED_TEXT,
                    text_type=TextType.PRINTED,
                ),
            )
        ),
    ).process_path(source_path, filename="failure.png", declared_content_type="image/png")

    assert document.pages[0].blocks[0].lines == []
    assert document.pages[0].blocks[0].needs_review is True
    assert any("test backend timed out" in warning for warning in document.warnings)

