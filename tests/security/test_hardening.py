from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ocr_platform.api.app import create_app
from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError, InvalidDocumentError
from ocr_platform.ingestion.source import build_document_source
from ocr_platform.pipeline import DocumentPipeline
from tests.api.test_app import StubPipeline


def test_staging_and_production_require_authentication() -> None:
    with pytest.raises(ConfigurationError, match="require OCR_REQUIRE_AUTH"):
        Settings(environment="production", require_auth=False, api_keys=("key",))


def test_production_requires_api_keys() -> None:
    with pytest.raises(ConfigurationError, match="production authentication"):
        Settings(environment="production", require_auth=True, api_keys=())


def test_resource_bounds_are_positive() -> None:
    with pytest.raises(ConfigurationError, match="pixel limits"):
        Settings(environment="test", max_render_pixels=0)


def test_pipeline_enforces_size_limit_before_processing(tmp_path: Path) -> None:
    path = tmp_path / "source.png"
    Image.new("RGB", (10, 10), "white").save(path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_upload_bytes=1)
    with pytest.raises(InvalidDocumentError, match="size limit"):
        DocumentPipeline(settings, backends=()).process_path(
            path,
            filename="source.png",
            declared_content_type="image/png",
        )


def test_source_filename_is_not_silently_truncated(tmp_path: Path) -> None:
    path = tmp_path / "source.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(InvalidDocumentError, match="filename"):
        build_document_source(
            path,
            filename="a" * 256,
            declared_content_type="image/png",
            source_uri="artifact://doc/source.bin",
        )


def test_auth_error_uses_safe_envelope_and_request_id(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        require_auth=True,
        api_keys=("secret-value",),
    )
    client = TestClient(create_app(settings=settings, pipeline=StubPipeline()))
    response = client.post(
        "/v1/documents/process",
        headers={"X-Request-ID": "request-123"},
        files={"file": ("source.png", b"data", "image/png")},
    )
    assert response.status_code == 401
    assert response.json() == {
        "code": "authentication_required",
        "message": "API authentication is required",
        "request_id": "request-123",
        "retryable": False,
    }
    assert "secret-value" not in response.text
