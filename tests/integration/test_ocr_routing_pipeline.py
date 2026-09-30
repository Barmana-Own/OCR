from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.dataset import DatasetExporter, DatasetExportPolicy
from ocr_platform.domain import (
    BlockType,
    CoordinateSpace,
    ExtractionMethod,
    ReviewFlag,
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


class UnicodeHandwritingBackend(HandwritingBackend):
    name = "unicode-handwriting-test"

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
                    raw_text="شماره ١٢٣ ABC@example.com",
                    bbox=(5.0, 5.0, 110.0, 25.0),
                    confidence=0.96,
                    language="fa+en",
                    script="Arabic+Latin",
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


class EmptyTableBackend(TableBackend):
    name = "empty-table-test"

    def extract(self, image_bytes: bytes, *, region: OcrRegion) -> TableResult:
        return TableResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            confidence_scale=self.confidence_scale,
        )


class FailingTableBackend(TableBackend):
    name = "failing-table-test"

    def extract(self, image_bytes: bytes, *, region: OcrRegion) -> TableResult:
        raise ProcessingError("table provider timed out", retryable=True)


class MalformedTableBackend(TableBackend):
    name = "malformed-table-test"

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
                    text="valid",
                    bbox=(5.0, 5.0, 80.0, 25.0),
                    confidence=0.95,
                ),
                TableCell(
                    row=0,
                    column=1,
                    text="outside",
                    bbox=(80.0, 5.0, 400.0, 25.0),
                    confidence=0.90,
                ),
            ),
        )


class ScaledTableBackend(TableBackend):
    name = "scaled-table-test"

    def __init__(self) -> None:
        self.received_region: OcrRegion | None = None

    def extract(self, image_bytes: bytes, *, region: OcrRegion) -> TableResult:
        self.received_region = region
        return TableResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            confidence_scale=self.confidence_scale,
            cells=(
                TableCell(
                    row=0,
                    column=0,
                    text="scaled",
                    bbox=(20.0, 20.0, 100.0, 60.0),
                    confidence=0.95,
                ),
            ),
        )


class FailingPrintedBackend(PrintedBackend):
    name = "failing-printed-test"

    def recognize(self, *args, **kwargs) -> OcrResult:
        raise ProcessingError("test backend timed out", retryable=True)


class FailingHandwritingBackend(HandwritingBackend):
    name = "failing-handwriting-test"

    def recognize(self, *args, **kwargs) -> OcrResult:
        raise ProcessingError("test HTR backend failed", retryable=True)


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


def test_handwriting_region_can_use_explicit_printed_fallback_with_review(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "handwriting-fallback.png"
    Image.new("RGB", (120, 80), "white").save(source_path, format="PNG")
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        max_retries=0,
        handwriting_fallback_to_printed=True,
    )
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
        filename="handwriting-fallback.png",
        declared_content_type="image/png",
    )

    block = document.pages[0].blocks[0]
    assert block.lines[0].raw_text == "شماره ABC123"
    assert block.lines[0].extraction.method == ExtractionMethod.OCR
    assert block.lines[0].needs_review is True
    assert ReviewFlag.CAPABILITY_UNAVAILABLE in block.uncertainty_flags
    assert "printed_ocr_fallback_for_handwriting" in block.lines[0].extraction.warnings
    assert any("fallback" in warning for warning in document.warnings)


def test_htr_backend_failure_uses_explicit_fallback_and_review(tmp_path: Path) -> None:
    source_path = tmp_path / "handwriting-failure-fallback.png"
    Image.new("RGB", (120, 80), "white").save(source_path, format="PNG")
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        max_retries=0,
        handwriting_fallback_to_printed=True,
    )
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        handwriting_backends=(FailingHandwritingBackend(),),
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
        filename="handwriting-failure-fallback.png",
        declared_content_type="image/png",
    )

    block = document.pages[0].blocks[0]
    assert block.lines[0].raw_text == "شماره ABC123"
    assert block.lines[0].needs_review is True
    assert ReviewFlag.CAPABILITY_UNAVAILABLE in block.uncertainty_flags
    assert any("test HTR backend failed" in warning for warning in document.warnings)


def test_htr_unicode_raw_text_and_normalized_export_are_separate(tmp_path: Path) -> None:
    source_path = tmp_path / "unicode-handwriting.png"
    Image.new("RGB", (120, 80), "white").save(source_path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        handwriting_backends=(UnicodeHandwritingBackend(),),
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
        filename="unicode-handwriting.png",
        declared_content_type="image/png",
    )

    line = document.pages[0].blocks[0].lines[0]
    assert line.raw_text == "شماره ١٢٣ ABC@example.com"
    assert line.normalized_text == "شماره ۱۲۳ ABC@example.com"

    exported = DatasetExporter(DocumentPipeline(settings, backends=()).store).export(
        document,
        tmp_path / "exports",
        policy=DatasetExportPolicy.ALL_WITH_STATUS,
    )
    canonical = (exported.root / "document.json").read_text(encoding="utf-8")
    text_export = (exported.root / "document.txt").read_text(encoding="utf-8")
    assert "شماره ١٢٣ ABC@example.com" in canonical
    assert "شماره ۱۲۳ ABC@example.com" in canonical
    assert "شماره ١٢٣ ABC@example.com" in text_export


def test_table_backend_unavailable_preserves_text_with_review_flags(tmp_path: Path) -> None:
    source_path = tmp_path / "table.png"
    Image.new("RGB", (300, 180), "white").save(source_path, format="PNG")
    table_region = LayoutRegion(
        bbox=(0.0, 0.0, 300.0, 180.0),
        block_type=BlockType.TABLE,
        confidence=0.95,
        reading_order=0,
        route_hint=RegionRouteHint.TABLE,
        text_type=TextType.PRINTED,
    )
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        layout_service=FixedLayoutService((table_region,)),
    ).process_path(source_path, filename="table.png", declared_content_type="image/png")

    block = document.pages[0].blocks[0]
    assert block.block_type is BlockType.TABLE
    assert block.lines[0].raw_text == "شماره ABC123"
    assert block.needs_review is True
    assert ReviewFlag.TABLE_STRUCTURE_UNCERTAIN in block.uncertainty_flags
    assert any("preserving text OCR" in warning for warning in document.warnings)


def test_empty_table_result_falls_back_to_printed_ocr(tmp_path: Path) -> None:
    source_path = tmp_path / "empty-table.png"
    Image.new("RGB", (300, 180), "white").save(source_path, format="PNG")
    table_region = LayoutRegion(
        bbox=(0.0, 0.0, 300.0, 180.0),
        block_type=BlockType.TABLE,
        confidence=0.95,
        reading_order=0,
        route_hint=RegionRouteHint.TABLE,
        text_type=TextType.PRINTED,
    )
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        table_backend=EmptyTableBackend(),
        layout_service=FixedLayoutService((table_region,)),
    ).process_path(source_path, filename="empty-table.png", declared_content_type="image/png")

    block = document.pages[0].blocks[0]
    assert block.table_cells == []
    assert block.lines[0].raw_text == "شماره ABC123"
    assert block.needs_review is True
    assert ReviewFlag.TABLE_STRUCTURE_UNCERTAIN in block.uncertainty_flags
    assert any("empty_result" in warning for warning in document.warnings)


def test_failed_table_backend_falls_back_to_printed_ocr(tmp_path: Path) -> None:
    source_path = tmp_path / "failed-table.png"
    Image.new("RGB", (300, 180), "white").save(source_path, format="PNG")
    table_region = LayoutRegion(
        bbox=(0.0, 0.0, 300.0, 180.0),
        block_type=BlockType.TABLE,
        confidence=0.95,
        reading_order=0,
        route_hint=RegionRouteHint.TABLE,
        text_type=TextType.PRINTED,
    )
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        table_backend=FailingTableBackend(),
        layout_service=FixedLayoutService((table_region,)),
    ).process_path(source_path, filename="failed-table.png", declared_content_type="image/png")

    block = document.pages[0].blocks[0]
    assert block.lines[0].raw_text == "شماره ABC123"
    assert ReviewFlag.BACKEND_FAILURE in block.uncertainty_flags
    assert ReviewFlag.TABLE_STRUCTURE_UNCERTAIN in block.uncertainty_flags
    assert any("table provider timed out" in warning for warning in document.warnings)


def test_malformed_table_cells_are_rejected_and_flagged_without_corrupting_valid_cells(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "malformed-table.png"
    Image.new("RGB", (300, 180), "white").save(source_path, format="PNG")
    table_region = LayoutRegion(
        bbox=(0.0, 0.0, 300.0, 180.0),
        block_type=BlockType.TABLE,
        confidence=0.95,
        reading_order=0,
        route_hint=RegionRouteHint.TABLE,
        text_type=TextType.PRINTED,
    )
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        table_backend=MalformedTableBackend(),
        layout_service=FixedLayoutService((table_region,)),
    ).process_path(
        source_path,
        filename="malformed-table.png",
        declared_content_type="image/png",
    )

    block = document.pages[0].blocks[0]
    assert [cell.raw_text for cell in block.table_cells] == ["valid"]
    assert block.lines == []
    assert block.needs_review is True
    assert ReviewFlag.INVALID_GEOMETRY in block.uncertainty_flags
    assert ReviewFlag.TABLE_STRUCTURE_UNCERTAIN in block.uncertainty_flags
    assert any("outside table region" in warning for warning in document.warnings)


def test_tiny_table_region_uses_bounded_scale_and_maps_cells_to_page_coordinates(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "scaled-table.png"
    Image.new("RGB", (300, 180), "white").save(source_path, format="PNG")
    table_region = LayoutRegion(
        bbox=(50.0, 20.0, 250.0, 120.0),
        block_type=BlockType.TABLE,
        confidence=0.95,
        reading_order=0,
        route_hint=RegionRouteHint.TABLE,
        text_type=TextType.PRINTED,
        tiny_text=True,
    )
    table_backend = ScaledTableBackend()
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=0)
    document = DocumentPipeline(
        settings,
        backends=(PrintedBackend(),),
        table_backend=table_backend,
        layout_service=FixedLayoutService((table_region,)),
    ).process_path(
        source_path,
        filename="scaled-table.png",
        declared_content_type="image/png",
    )

    cell = document.pages[0].blocks[0].table_cells[0]
    assert table_backend.received_region is not None
    assert table_backend.received_region.bbox == (0.0, 0.0, 400.0, 200.0)
    assert cell.bbox.as_list() == [60.0, 30.0, 100.0, 50.0]
    assert cell.extraction.region_scale == 2
    assert cell.extraction.preprocess_variant == "region-scale-2"


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

