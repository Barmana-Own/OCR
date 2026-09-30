from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from ocr_platform.domain import BlockType, CoordinateSpace, TextType
from ocr_platform.errors import BackendUnavailableError
from ocr_platform.handwriting import (
    TransformersHandwritingBackend,
    UnavailableHandwritingBackend,
    build_handwriting_backend,
)
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


def test_transformers_factory_is_configurable_without_loading_model() -> None:
    backend = build_handwriting_backend(
        "transformers",
        model_id="org/validated-htr",
        processor_id="org/validated-processor",
        revision="revision-1",
        device="cpu",
        local_files_only=True,
        max_generation_length=73,
        timeout_seconds=11,
    )

    assert isinstance(backend, TransformersHandwritingBackend)
    assert backend.model == "org/validated-htr"
    assert backend.model_version == "revision-1"
    assert backend.max_generation_length == 73
    assert backend.timeout_seconds == 11


def test_transformers_htr_maps_mocked_generation_with_uncalibrated_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeBatch(dict[str, object]):
        def to(self, device: str) -> FakeBatch:
            self["device"] = device
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, source: str, **kwargs: object) -> FakeProcessor:
            calls.append((f"processor:{source}", kwargs))
            return cls()

        def __call__(self, *, images: object, return_tensors: str) -> FakeBatch:
            assert images is not None
            assert return_tensors == "pt"
            return FakeBatch(pixel_values=object())

        def batch_decode(self, generated: object, *, skip_special_tokens: bool) -> list[str]:
            assert generated == [[1, 2, 3]]
            assert skip_special_tokens is True
            return ["شماره ١٢٣ ABC"]

    class FakeModel:
        config = SimpleNamespace(_commit_hash="loaded-revision")

        @classmethod
        def from_pretrained(cls, source: str, **kwargs: object) -> FakeModel:
            calls.append((f"model:{source}", kwargs))
            return cls()

        def __init__(self) -> None:
            self.device = "cpu"

        def to(self, device: str) -> FakeModel:
            self.device = device
            return self

        def eval(self) -> FakeModel:
            return self

        def generate(self, **kwargs: object) -> list[list[int]]:
            assert kwargs["max_new_tokens"] == 73
            assert kwargs["max_time"] == 11.0
            return [[1, 2, 3]]

    class FakeTorch:
        class cuda:
            @staticmethod
            def is_available() -> bool:
                return False

        @staticmethod
        def inference_mode() -> object:
            return nullcontext()

    def fake_import(module_name: str) -> object:
        if module_name == "torch":
            return FakeTorch
        if module_name == "transformers":
            return SimpleNamespace(
                AutoProcessor=FakeProcessor,
                VisionEncoderDecoderModel=FakeModel,
                __version__="4.test",
            )
        raise ImportError(module_name)

    monkeypatch.setattr(
        "ocr_platform.handwriting.transformers.importlib.import_module", fake_import
    )
    backend = TransformersHandwritingBackend(
        model_id="org/validated-htr",
        processor_id="org/validated-processor",
        revision="revision-1",
        device="cpu",
        local_files_only=True,
        trust_remote_code=False,
        cache_dir="var/cache",
        max_generation_length=73,
        timeout_seconds=11,
    )
    result = backend.recognize(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82",
        region=_region(BlockType.HANDWRITING),
        dpi=450,
        region_scale=2,
        preprocess_variant="region-scale-2",
    )

    assert result.model == "org/validated-htr"
    assert result.model_version == "loaded-revision"
    assert result.lines[0].raw_text == "شماره ١٢٣ ABC"
    assert result.lines[0].confidence is None
    assert result.lines[0].language == "und"
    assert result.lines[0].script == "Unknown"
    assert result.lines[0].bbox == (0.0, 0.0, 200.0, 100.0)
    assert "confidence_unavailable" in result.warnings
    assert dict(result.runtime_metadata)["max_generation_length"] == "73"
    assert dict(result.runtime_metadata)["preprocess_variant"] == "region-scale-2"
    assert calls[0][0] == "processor:org/validated-processor"
    assert calls[1][0] == "model:org/validated-htr"
    assert all(call[1]["local_files_only"] is True for call in calls)
    assert all(call[1]["trust_remote_code"] is False for call in calls)


def test_transformers_htr_model_runtime_is_optional_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = TransformersHandwritingBackend(model_id="org/validated-htr", device="cpu")

    def missing_import(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(
        "ocr_platform.handwriting.transformers.importlib.import_module", missing_import
    )

    with pytest.raises(BackendUnavailableError, match="optional 'htr' extra"):
        backend.recognize(
            b"image",
            region=_region(BlockType.HANDWRITING),
            dpi=300,
            region_scale=1,
            preprocess_variant="source-render",
        )


def test_unavailable_factory_exposes_capability_reason() -> None:
    backend = build_handwriting_backend("none")

    assert isinstance(backend, UnavailableHandwritingBackend)
    assert backend.available is False
    assert backend.unavailable_reason == backend.reason


@pytest.mark.model
def test_transformers_htr_real_model_smoke_is_explicitly_opt_in() -> None:
    if os.getenv("OCR_RUN_MODEL_TESTS") != "1":
        pytest.skip("set OCR_RUN_MODEL_TESTS=1 to run optional model tests")
    model_id = os.getenv("OCR_HANDWRITING_MODEL_ID")
    if not model_id:
        pytest.skip("OCR_HANDWRITING_MODEL_ID is required for the model smoke test")
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (32, 32), "white").save(image, format="PNG")
    backend = TransformersHandwritingBackend(
        model_id=model_id,
        processor_id=os.getenv("OCR_HANDWRITING_PROCESSOR_ID") or None,
        revision=os.getenv("OCR_HANDWRITING_REVISION") or None,
        device="cpu",
        local_files_only=True,
    )
    result = backend.recognize(
        image.getvalue(),
        region=_region(BlockType.HANDWRITING),
        dpi=300,
        region_scale=1,
        preprocess_variant="source-render",
    )

    assert result.method.value == "handwriting_recognition"
    assert result.model == model_id
    assert result.confidence_scale == "uncalibrated_none"
