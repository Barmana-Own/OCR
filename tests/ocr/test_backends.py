import subprocess

import pytest

from ocr_platform.domain import CoordinateSpace, ExtractionMethod, TextType
from ocr_platform.errors import BackendUnavailableError, ProcessingError
from ocr_platform.handwriting import UnavailableHandwritingBackend
from ocr_platform.ocr.backends import TesseractBackend
from ocr_platform.ocr.models import OcrRegion
from ocr_platform.tables import UnavailableTableBackend


def _region() -> OcrRegion:
    from ocr_platform.domain import BlockType

    return OcrRegion(
        region_id="phase6-region",
        bbox=(0.0, 0.0, 100.0, 80.0),
        block_type=BlockType.PRINTED_TEXT,
        text_type=TextType.PRINTED,
        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        source_uri="artifact://doc/page-1.png",
    )


def test_unavailable_handwriting_and_table_adapters_fail_closed() -> None:
    with pytest.raises(BackendUnavailableError):
        UnavailableHandwritingBackend().recognize(
            b"image",
            region=_region(),
            dpi=300,
            region_scale=1,
            preprocess_variant="source-render",
        )
    with pytest.raises(BackendUnavailableError):
        UnavailableTableBackend().extract(b"image", region=_region())


def test_tesseract_adapter_records_language_and_runtime_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t40\t12\t96.0\tشماره\n"
    )
    monkeypatch.setattr("ocr_platform.ocr.backends.tesseract.shutil.which", lambda _: "fake")

    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=tsv, stderr="")

    monkeypatch.setattr("ocr_platform.ocr.backends.tesseract.subprocess.run", run)
    backend = TesseractBackend(
        executable="tesseract",
        language="fas+eng",
        timeout_seconds=7,
    )
    result = backend.recognize(
        b"image",
        region=_region(),
        dpi=450,
        region_scale=2,
        preprocess_variant="region-scale-2",
    )

    assert result.method == ExtractionMethod.OCR
    assert result.lines[0].raw_text == "شماره"
    assert dict(result.runtime_metadata)["language"] == "fas+eng"
    assert dict(result.runtime_metadata)["timeout_seconds"] == "7"
    assert result.warnings == ()


def test_tesseract_timeout_is_a_retryable_backend_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ocr_platform.ocr.backends.tesseract.shutil.which", lambda _: "fake")

    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr("ocr_platform.ocr.backends.tesseract.subprocess.run", run)
    backend = TesseractBackend(timeout_seconds=1)

    with pytest.raises(ProcessingError) as error:
        backend.recognize(
            b"image",
            region=_region(),
            dpi=300,
            region_scale=1,
            preprocess_variant="source-render",
        )
    assert error.value.details.retryable is True
