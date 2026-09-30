from __future__ import annotations

import os
from io import BytesIO

import pytest
from PIL import Image

from ocr_platform.domain import BlockType, CoordinateSpace, ReviewFlag, TextType
from ocr_platform.errors import BackendUnavailableError
from ocr_platform.ocr.models import OcrRegion
from ocr_platform.tables import (
    PaddleStructureTableBackend,
    TableCell,
    TableResult,
    build_table_backend,
    validate_table_cells,
)


def _region(width: float = 180.0, height: float = 80.0) -> OcrRegion:
    return OcrRegion(
        region_id="table-test",
        bbox=(0.0, 0.0, width, height),
        block_type=BlockType.TABLE,
        text_type=TextType.PRINTED,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        source_uri="artifact://doc/page.png",
    )


def _cell(
    row: int,
    column: int,
    text: str,
    bbox: tuple[float, float, float, float],
) -> TableCell:
    return TableCell(
        row=row,
        column=column,
        text=text,
        raw_text=text,
        bbox=bbox,
        confidence=0.94,
        language="fa+en" if any("\u0600" <= char <= "\u06ff" for char in text) else "en",
        script="Arabic+Latin" if any("\u0600" <= char <= "\u06ff" for char in text) else "Latin",
    )


def test_validate_table_cells_returns_deterministic_2x3_row_major_cells() -> None:
    cells = (
        _cell(1, 2, "F", (120.0, 40.0, 180.0, 80.0)),
        _cell(0, 1, "شماره", (60.0, 0.0, 120.0, 40.0)),
        _cell(1, 0, "D", (0.0, 40.0, 60.0, 80.0)),
        _cell(0, 2, "C", (120.0, 0.0, 180.0, 40.0)),
        _cell(0, 0, "A", (0.0, 0.0, 60.0, 40.0)),
        _cell(1, 1, "E", (60.0, 40.0, 120.0, 80.0)),
    )

    result = validate_table_cells(cells, region_bbox=(0.0, 0.0, 180.0, 80.0))

    assert result.usable is True
    assert [(cell.row, cell.column) for cell in result.cells] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (1, 0),
        (1, 1),
        (1, 2),
    ]
    assert result.cells[1].raw_text == "شماره"
    assert result.cells[1].language == "fa+en"


def test_validate_table_cells_rejects_malformed_provider_cells() -> None:
    valid = _cell(0, 0, "valid", (0.0, 0.0, 50.0, 30.0))
    malformed = (
        _cell(-1, 1, "negative row", (50.0, 0.0, 100.0, 30.0)),
        _cell(0, 1, "outside", (50.0, 0.0, 120.0, 30.0)),
        _cell(0, 1, "duplicate geometry", (0.0, 0.0, 50.0, 30.0)),
    )

    result = validate_table_cells((valid, *malformed), region_bbox=(0.0, 0.0, 100.0, 60.0))

    assert result.usable is True
    assert result.cells == (valid,)
    assert any(warning.startswith("invalid_address") for warning in result.warnings)
    assert any(warning.startswith("invalid_geometry") for warning in result.warnings)
    assert any(warning.startswith("overlapping_duplicate") for warning in result.warnings)
    assert ReviewFlag.INVALID_GEOMETRY in result.review_flags
    assert ReviewFlag.TABLE_STRUCTURE_UNCERTAIN in result.review_flags


def test_validate_table_cells_marks_empty_structure_unusable() -> None:
    result = validate_table_cells(
        (_cell(0, 0, "", (0.0, 0.0, 50.0, 30.0)),),
        region_bbox=(0.0, 0.0, 100.0, 60.0),
    )

    assert result.usable is False
    assert result.cells
    assert any(
        warning.startswith(("empty_result", "excessive_empty_cells"))
        for warning in result.warnings
    )
    assert ReviewFlag.TABLE_STRUCTURE_UNCERTAIN in result.review_flags


def test_validate_table_cells_marks_excessive_empty_values_unusable() -> None:
    cells = tuple(
        _cell(row, 0, "value" if row == 0 else "", (0.0, row * 10.0, 80.0, row * 10.0 + 8.0))
        for row in range(5)
    )

    result = validate_table_cells(cells, region_bbox=(0.0, 0.0, 100.0, 60.0))

    assert result.usable is False
    assert any(warning.startswith("excessive_empty_cells") for warning in result.warnings)


def test_paddle_structure_adapter_extracts_2x3_cells_and_preserves_scripts() -> None:
    backend = PaddleStructureTableBackend(language="fa")
    backend._engine = lambda _image: [
        {
            "type": "table",
            "res": {
                "cell_bbox": [
                    [0, 0, 60, 30],
                    [60, 0, 120, 30],
                    [120, 0, 180, 30],
                    [0, 30, 60, 60],
                    [60, 30, 120, 60],
                    [120, 30, 180, 60],
                ],
                "rec_res": [
                    ["نام", 0.91],
                    ["Alice", 0.92],
                    ["شماره ۱۲۳", 0.93],
                    ["D", 0.94],
                    ["E", 0.95],
                    ["F", 0.96],
                ],
            },
        }
    ]

    result = backend.extract(b"image", region=_region())

    assert isinstance(result, TableResult)
    assert [(cell.row, cell.column) for cell in result.cells] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (1, 0),
        (1, 1),
        (1, 2),
    ]
    assert result.cells[0].raw_text == "نام"
    assert result.cells[2].raw_text == "شماره ۱۲۳"
    assert result.backend_family == "paddleocr-structure"


def test_table_backend_alias_is_real_and_unknown_backend_fails_closed() -> None:
    assert isinstance(build_table_backend("paddle-table"), PaddleStructureTableBackend)
    unavailable = build_table_backend("provider-that-is-not-installed")

    with pytest.raises(BackendUnavailableError):
        unavailable.extract(b"image", region=_region())


def test_optional_table_runtime_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = PaddleStructureTableBackend(language="fa")

    def missing_import(_name: str):
        raise ImportError("paddleocr is absent")

    monkeypatch.setattr("ocr_platform.tables.paddle.importlib.import_module", missing_import)

    with pytest.raises(BackendUnavailableError, match="not installed"):
        backend.extract(b"image", region=_region())


@pytest.mark.model
def test_paddle_structure_model_smoke_uses_only_an_explicit_local_runtime() -> None:
    if os.getenv("OCR_RUN_MODEL_TESTS") != "1":
        pytest.skip("set OCR_RUN_MODEL_TESTS=1 to run optional model tests")
    model_path = os.getenv("OCR_TABLE_MODEL_PATH")
    if not model_path:
        pytest.skip("set OCR_TABLE_MODEL_PATH to an installed local table model")
    pytest.importorskip("paddleocr")
    buffer = BytesIO()
    Image.new("RGB", (180, 80), "white").save(buffer, format="PNG")
    backend = PaddleStructureTableBackend(language="fa", model_path=model_path, device="cpu")

    result = backend.extract(buffer.getvalue(), region=_region())

    assert isinstance(result, TableResult)
