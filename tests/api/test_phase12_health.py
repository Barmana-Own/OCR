from pathlib import Path

from fastapi.testclient import TestClient

from ocr_platform.api.app import create_app
from ocr_platform.config import Settings
from ocr_platform.storage import LocalArtifactStore
from tests.api.test_app import StubPipeline
from tests.api.test_phase9_api import ApiPipeline


def test_health_reports_capability_without_making_liveness_depend_on_it(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        require_auth=True,
        api_keys=("secret",),
    )
    client = TestClient(create_app(settings=settings, pipeline=StubPipeline()))

    health = client.get("/healthz")
    readiness = client.get("/readyz")
    metrics_without_auth = client.get("/metrics")

    assert health.status_code == 200
    assert readiness.status_code == 200
    assert health.json()["capabilities"] == []
    assert metrics_without_auth.status_code == 401


def test_metrics_route_is_authenticated_and_contains_only_counters(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        require_auth=True,
        api_keys=("secret",),
    )
    store = LocalArtifactStore(settings.storage_root)
    pipeline = ApiPipeline(store)
    client = TestClient(create_app(settings=settings, pipeline=pipeline))

    response = client.get("/metrics", headers={"X-OCR-API-Key": "secret"})

    assert response.status_code == 200
    assert set(response.json()) == {"counters", "summaries"}
