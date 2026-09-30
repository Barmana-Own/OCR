from pathlib import Path

from fastapi.testclient import TestClient

from ocr_platform.api.app import create_app
from ocr_platform.config import Settings
from tests.api.test_app import StubPipeline


def test_artifact_and_deletion_routes_require_authentication(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        require_auth=True,
        api_keys=("secret",),
    )
    client = TestClient(create_app(settings=settings, pipeline=StubPipeline()))

    manifest = client.get("/v1/documents/doc-test/manifest")
    image = client.get("/v1/documents/doc-test/pages/1/image")
    deletion = client.delete("/v1/documents/doc-test")

    assert manifest.status_code == 401
    assert image.status_code == 401
    assert deletion.status_code == 401
