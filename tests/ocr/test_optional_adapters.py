from __future__ import annotations

import pytest

from ocr_platform.domain import BlockType, CoordinateSpace, TextType
from ocr_platform.errors import BackendUnavailableError
from ocr_platform.handwriting import TransformersHandwritingBackend
from ocr_platform.ocr.backends import PaddleOcrBackend
from ocr_platform.ocr.models import OcrRegion
from ocr_platform.tables import PaddleStructureTableBackend


def _region(block_type: BlockType = BlockType.PRINTED_TEXT) -> OcrRegion:
    return OcrRegion(
        region_id="adapter-region",
        bbox=(0.0, 0.0, 200.0, 100.0),
        block_type=block_type,
        text_type=TextType.PRINTED,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        source_uri="artifact://doc/page.png",
    )


def test_paddle_adapter_maps_2x_nested_records_without_model_import() -> None:
    backend = PaddleOcrBackend(language="fas+eng")

    class FakeEngine:
        def ocr(self, _image: bytes, cls: bool):
            assert cls is True
            return [
                [
                    [[[0, 0], [40, 0], [40, 20], [0, 20]], ("شماره", 0.97)],
                    [[[50, 0], [90, 0], [90, 20], [50, 20]], ("ABC", 0.96)],
                ]
            ]

    backend._engine = FakeEngine()
    result = backend.recognize(
        b"image",
        region=_region(),
        dpi=300,
        region_scale=1,
        preprocess_variant="source-render",
    )
    assert result.backend_family == "paddleocr"
    assert result.lines[0].raw_text == "شماره ABC"
    assert result.lines[0].confidence == pytest.approx(0.965)
    assert result.lines[0].words[0].text == "شماره"


def test_pp_structure_adapter_preserves_cells_and_warnings() -> None:
    backend = PaddleStructureTableBackend(language="fa")
    backend._engine = lambda _image: [
        {
            "type": "table",
            "res": {
                "cell_bbox": [[[0, 0], [80, 0], [80, 20], [0, 20]]],
                "rec_res": [["نام", 0.91]],
                "row_indices": [0],
                "column_indices": [0],
            },
        }
    ]
    result = backend.extract(b"image", region=_region(BlockType.TABLE))
    assert result.backend_family == "paddleocr-structure"
    assert result.cells[0].text == "نام"
    assert result.cells[0].row == 0
    assert result.cells[0].column == 0


def test_pp_structure_adapter_supports_predict_input_api() -> None:
    backend = PaddleStructureTableBackend(language="fa")

    class FakePipeline:
        def predict(self, *, input: bytes):
            assert input == b"image"
            return [
                {
                    "type": "table",
                    "res": {
                        "cell_bbox": [[0, 0, 80, 20]],
                        "rec_res": [["مبلغ", 0.88]],
                    },
                }
            ]

    backend._engine = FakePipeline()
    result = backend.extract(b"image", region=_region(BlockType.TABLE))
    assert result.cells[0].raw_text == "مبلغ"
    assert result.cells[0].confidence == pytest.approx(0.88)


def test_optional_htr_without_model_fails_closed() -> None:
    backend = TransformersHandwritingBackend(model_path=None)
    with pytest.raises(BackendUnavailableError, match="model path"):
        backend.recognize(
            b"image",
            region=_region(BlockType.HANDWRITING),
            dpi=300,
            region_scale=1,
            preprocess_variant="source-render",
        )
