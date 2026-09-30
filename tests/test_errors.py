import pytest

from ocr_platform.errors import (
    CorruptPdfError,
    ImageDecodeError,
    InvalidGeometryError,
    OcrBackendFailure,
    PageRenderError,
    PasswordProtectedPdfError,
    QualityGateError,
    StorageFailureError,
    UnsupportedFileTypeError,
)


@pytest.mark.parametrize(
    ("error_type", "code", "status", "retryable"),
    [
        (UnsupportedFileTypeError, "unsupported_document", 415, False),
        (CorruptPdfError, "corrupt_pdf", 422, False),
        (PasswordProtectedPdfError, "password_protected_pdf", 422, False),
        (PageRenderError, "page_render_failure", 422, True),
        (ImageDecodeError, "image_decode_failure", 422, False),
        (OcrBackendFailure, "ocr_backend_failure", 502, True),
        (InvalidGeometryError, "invalid_geometry", 422, False),
        (StorageFailureError, "storage_failure", 500, True),
        (QualityGateError, "quality_gate_failure", 422, False),
    ],
)
def test_phase2_errors_have_stable_boundary_metadata(error_type, code, status, retryable) -> None:
    error = error_type("phase2 failure")

    assert error.details.code == code
    assert error.details.http_status == status
    assert error.details.retryable is retryable
    assert str(error) == "phase2 failure"
