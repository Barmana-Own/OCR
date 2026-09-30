from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ocr_platform.api.app import create_app
from ocr_platform.config import Settings
from ocr_platform.domain import Document, DocumentSource, VerificationStatus


class StubPipeline:
    def process_path(
        self,
        path: Path,
        *,
        filename: str,
        declared_content_type: str | None = None,
        document_id: str | None = None,
    ) -> Document:
        return Document(
            id="doc-test",
            pipeline_version="0.1.0",
            source=DocumentSource(
                filename=filename,
                content_type=declared_content_type or "application/octet-stream",
                byte_size=path.stat().st_size,
                checksum_sha256="a" * 64,
                source_uri="artifact://doc-test/source.bin",
            ),
            configuration_hash="b" * 64,
            processing_checksum="c" * 64,
            processing_started_at=datetime.now(UTC),
            processing_finished_at=datetime.now(UTC),
            status=VerificationStatus.ACCEPTED,
        )


def _png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_health_is_public_and_processing_requires_auth(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        require_auth=True,
        api_keys=("secret",),
    )
    client = TestClient(create_app(settings=settings, pipeline=StubPipeline()))
    assert client.get("/healthz").status_code == 200
    response = client.post(
        "/v1/documents/process",
        files={"file": ("source.png", b"data", "image/png")},
    )
    assert response.status_code == 401


def test_upload_limit_is_enforced_before_pipeline(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        require_auth=True,
        api_keys=("secret",),
        max_upload_bytes=3,
    )
    client = TestClient(create_app(settings=settings, pipeline=StubPipeline()))
    response = client.post(
        "/v1/documents/process",
        headers={"X-OCR-API-Key": "secret"},
        files={"file": ("source.png", b"data", "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_document"


def test_valid_upload_returns_canonical_document(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        require_auth=True,
        api_keys=("secret",),
    )
    client = TestClient(create_app(settings=settings, pipeline=StubPipeline()))
    response = client.post(
        "/v1/documents/process",
        headers={"X-OCR-API-Key": "secret"},
        files={"file": ("source.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "doc-test"
    assert response.headers["X-Request-ID"]
