from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ocr_platform.api.app import create_app
from ocr_platform.config import Settings
from ocr_platform.database.local import InMemoryDocumentRepository, InMemoryJobRepository
from ocr_platform.domain import (
    CoordinateSpace,
    Document,
    DocumentSource,
    Page,
    PageType,
    ProcessingStatus,
    VerificationStatus,
)
from ocr_platform.storage import LocalArtifactStore
from ocr_platform.workers.orchestrator import DocumentJobService


def _png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (12, 12), "white").save(stream, format="PNG")
    return stream.getvalue()


class ApiPipeline:
    def __init__(self, store: LocalArtifactStore) -> None:
        self.store = store

    def process_path(
        self,
        path: Path,
        *,
        filename: str,
        declared_content_type: str | None = None,
        document_id: str | None = None,
        progress_callback=None,
    ) -> Document:
        assert document_id is not None
        if progress_callback is not None:
            progress_callback(1, 1, "ocr")
        rendered = self.store.put_bytes(
            document_id,
            "pages/page_0001/original_render_300dpi.png",
            _png_bytes(),
        )
        now = datetime.now(UTC)
        return Document(
            id=document_id,
            pipeline_version="0.1.0",
            source=DocumentSource(
                filename=filename,
                content_type=declared_content_type or "image/png",
                byte_size=path.stat().st_size,
                checksum_sha256="a" * 64,
                source_uri=f"artifact://{document_id}/source/original.bin",
            ),
            configuration_hash="b" * 64,
            processing_checksum="c" * 64,
            processing_started_at=now,
            processing_finished_at=now,
            pages=[
                Page(
                    page_number=1,
                    width=12,
                    height=12,
                    coordinate_space=CoordinateSpace.RENDERED_PIXEL,
                    page_type=PageType.IMAGE,
                    source_uri=f"artifact://{document_id}/source/original.bin",
                    rendered_uri=rendered.uri,
                    source_dpi=300,
                    rendered_width=12,
                    rendered_height=12,
                )
            ],
            processing_status=ProcessingStatus.COMPLETED,
            status=VerificationStatus.ACCEPTED,
        )


def _client(tmp_path: Path, *, max_upload_bytes: int = 50 * 1024 * 1024):
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        temporary_workspace=tmp_path / "tmp",
        require_auth=True,
        api_keys=("secret",),
        max_upload_bytes=max_upload_bytes,
        worker_count=1,
        max_queued_jobs=4,
    )
    store = LocalArtifactStore(settings.storage_root)
    pipeline = ApiPipeline(store)
    service = DocumentJobService(
        settings,
        pipeline=pipeline,
        artifact_store=store,
        job_repository=InMemoryJobRepository(),
        document_repository=InMemoryDocumentRepository(),
    )
    return (
        TestClient(create_app(settings=settings, pipeline=pipeline, job_service=service)),
        service,
    )


def test_async_submission_lifecycle_and_exports(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    with client:
        response = client.post(
            "/v1/documents",
            headers={"X-OCR-API-Key": "secret", "Idempotency-Key": "upload-1"},
            data={"mode": "balanced"},
            files={"file": ("source.png", _png_bytes(), "image/png")},
        )
        assert response.status_code == 202
        payload = response.json()
        job_id = payload["job_id"]
        document_id = payload["document_id"]
        job = service.wait_for(job_id, timeout=5)
        assert job.status.value == "completed"

        status = client.get(f"/v1/jobs/{job_id}", headers={"X-OCR-API-Key": "secret"})
        document = client.get(
            f"/v1/documents/{document_id}", headers={"X-OCR-API-Key": "secret"}
        )
        manifest = client.get(
            f"/v1/documents/{document_id}/manifest",
            headers={"X-OCR-API-Key": "secret"},
        )
        export = client.get(
            f"/v1/documents/{document_id}/exports/txt?policy=strict_verified_only",
            headers={"X-OCR-API-Key": "secret"},
        )
        image = client.get(
            f"/v1/documents/{document_id}/pages/1/image",
            headers={"X-OCR-API-Key": "secret"},
        )

    assert status.status_code == 200
    assert status.json()["progress"]["percent"] == 100
    assert document.status_code == 200
    assert document.json()["id"] == document_id
    assert manifest.status_code == 200
    assert manifest.json()["document_id"] == document_id
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/plain")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")


def test_document_deletion_is_authenticated_and_removes_private_outputs(
    tmp_path: Path,
) -> None:
    client, service = _client(tmp_path)
    with client:
        headers = {"X-OCR-API-Key": "secret"}
        submission = client.post(
            "/v1/documents",
            headers=headers,
            data={"mode": "balanced"},
            files={"file": ("source.png", _png_bytes(), "image/png")},
        )
        document_id = submission.json()["document_id"]
        source_checksum = submission.json()["source_checksum"]
        service.wait_for(submission.json()["job_id"], timeout=5)
        exported = client.get(
            f"/v1/documents/{document_id}/exports/json",
            headers=headers,
        )
        unauthorized = client.delete(f"/v1/documents/{document_id}")
        deleted = client.delete(f"/v1/documents/{document_id}", headers=headers)
        missing = client.get(f"/v1/documents/{document_id}", headers=headers)
        missing_image = client.get(
            f"/v1/documents/{document_id}/pages/1/image",
            headers=headers,
        )

    service.shutdown()
    assert exported.status_code == 200
    assert unauthorized.status_code == 401
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert missing.status_code == 404
    assert missing_image.status_code == 404
    assert not service.artifact_store.exists(
        document_id, f"uploads/source-{source_checksum}.bin"
    )


def test_upload_validation_rejects_empty_oversized_unsafe_and_bad_signatures(
    tmp_path: Path,
) -> None:
    client, service = _client(tmp_path, max_upload_bytes=8)
    with client:
        cases = [
            ("empty.png", b"", "image/png"),
            ("large.png", b"123456789", "image/png"),
            ("..\\escape.png", _png_bytes(), "image/png"),
            ("source.png", b"not-an-image", "image/png"),
            ("source.pdf", _png_bytes(), "application/pdf"),
        ]
        responses = [
            client.post(
                "/v1/documents",
                headers={"X-OCR-API-Key": "secret"},
                files={"file": (filename, body, content_type)},
            )
            for filename, body, content_type in cases
        ]
    service.shutdown()

    assert all(response.status_code in {415, 422} for response in responses)
    assert all(response.json()["request_id"] for response in responses)


def test_idempotent_resubmission_returns_same_job(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    with client:
        headers = {"X-OCR-API-Key": "secret", "Idempotency-Key": "same-key"}
        first = client.post(
            "/v1/documents",
            headers=headers,
            data={"mode": "fast"},
            files={"file": ("source.png", _png_bytes(), "image/png")},
        )
        service.wait_for(first.json()["job_id"], timeout=5)
        second = client.post(
            "/v1/documents",
            headers=headers,
            data={"mode": "fast"},
            files={"file": ("source.png", _png_bytes(), "image/png")},
        )

    service.shutdown()
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["idempotent_replay"] is True


def test_idempotency_key_conflict_is_explicit(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    with client:
        headers = {"X-OCR-API-Key": "secret", "Idempotency-Key": "conflict-key"}
        first = client.post(
            "/v1/documents",
            headers=headers,
            data={"mode": "fast"},
            files={"file": ("source.png", _png_bytes(), "image/png")},
        )
        different = bytearray(_png_bytes())
        different[-1] = (different[-1] + 1) % 256
        second = client.post(
            "/v1/documents",
            headers=headers,
            data={"mode": "fast"},
            files={"file": ("source.png", bytes(different), "image/png")},
        )

    service.shutdown()
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["code"] == "idempotency_conflict"


def test_malformed_resource_ids_use_safe_not_found_errors(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    try:
        with client:
            job = client.get(
                "/v1/jobs/job!", headers={"X-OCR-API-Key": "secret"}
            )
            document = client.get(
                "/v1/documents/doc!", headers={"X-OCR-API-Key": "secret"}
            )
    finally:
        service.shutdown()

    assert job.status_code == 404
    assert job.json()["code"] == "job_not_found"
    assert document.status_code == 404
    assert document.json()["code"] == "document_not_found"
