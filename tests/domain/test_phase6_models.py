from ocr_platform.domain import (
    BlockResult,
    BlockType,
    BoundingBox,
    CoordinateSpace,
    ExtractionMetadata,
    ExtractionMethod,
    PageResult,
    Provenance,
    TableCellResult,
    TextType,
)
from ocr_platform.tables import TableCell, TableResult


def _provenance() -> Provenance:
    return Provenance(
        document_id="doc-phase6",
        page_number=1,
        source_uri="artifact://doc-phase6/source.png",
        crop_uri="artifact://doc-phase6/page-0001/cells/cell-0-0.png",
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
    )


def _extraction() -> ExtractionMetadata:
    return ExtractionMetadata(
        method=ExtractionMethod.TABLE_EXTRACTION,
        backend="table-test",
        model="table-model",
        model_version="1",
        dpi=300,
        preprocess_variant="source-render",
        confidence_scale="test-0-1",
        runtime_metadata={"device": "cpu"},
        warnings=["cell candidate retained"],
    )


def test_table_result_preserves_cells_and_provider_metadata() -> None:
    result = TableResult(
        backend="table-test",
        model="table-model",
        model_version="1",
        confidence_scale="test-0-1",
        cells=(
            TableCell(
                row=0,
                column=0,
                text="شماره ١٢٣",
                bbox=(2.0, 3.0, 80.0, 24.0),
                confidence=0.94,
                language="fa",
                script="Arabic",
            ),
        ),
        runtime_metadata=(("device", "cpu"),),
        warnings=("table cell alternatives retained",),
    )

    assert result.cells[0].text == "شماره ١٢٣"
    assert result.runtime_metadata == (("device", "cpu"),)
    assert result.warnings == ("table cell alternatives retained",)


def test_canonical_table_cell_is_serializable_and_page_validated() -> None:
    cell = TableCellResult(
        id="cell-0-0",
        row=0,
        column=0,
        raw_text="شماره ١٢٣ / ABC",
        normalized_text="شماره ۱۲۳ / ABC",
        bbox=BoundingBox(x0=10, y0=20, x1=90, y1=44),
        confidence=0.94,
        language="fa+en",
        script="Arabic+Latin",
        reading_order=0,
        text_type=TextType.MIXED,
        source=_provenance(),
        extraction=_extraction(),
    )
    block = BlockResult(
        id="block-table",
        block_type=BlockType.TABLE,
        bbox=BoundingBox(x0=0, y0=0, x1=200, y1=100),
        reading_order=0,
        source=_provenance(),
        table_cells=[cell],
    )
    page = PageResult(
        page_number=1,
        width=200,
        height=100,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        page_type="image",
        source_uri="artifact://doc-phase6/source.png",
        rendered_width=200,
        rendered_height=100,
        blocks=[block],
    )

    payload = page.model_dump(mode="json")
    assert payload["blocks"][0]["table_cells"][0]["raw_text"] == "شماره ١٢٣ / ABC"
    assert payload["blocks"][0]["table_cells"][0]["normalized_text"] == "شماره ۱۲۳ / ABC"
    assert payload["blocks"][0]["table_cells"][0]["row"] == 0

