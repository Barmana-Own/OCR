"""FastAPI application factory and safe asynchronous upload boundary."""

import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response

from ocr_platform.config import Settings, get_settings
from ocr_platform.database import FileDocumentRepository, FileJobRepository
from ocr_platform.dataset import DatasetExportPolicy
from ocr_platform.domain import Document
from ocr_platform.errors import (
    ArtifactStorageError,
    DocumentNotFoundError,
    ErrorDetails,
    InvalidDocumentError,
    JobNotFoundError,
    OcrPlatformError,
)
from ocr_platform.observability.logging import configure_logging, get_logger, set_request_id
from ocr_platform.observability.metrics import MetricsRegistry
from ocr_platform.ocr.runtime import inspect_backend, resolve_device
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.storage import read_artifact_uri
from ocr_platform.workers.models import JobRecord, ProcessingMode
from ocr_platform.workers.orchestrator import DocumentJobService
from ocr_platform.workers.policy import ProcessingModePolicy

from .auth import build_api_key_dependency
from .schemas import ErrorResponse, HealthResponse, JobSubmissionResponse
from .uploads import (
    read_upload_bytes,
    validate_filename,
    validate_upload_content,
)

logger = get_logger(__name__)
_SAFE_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def create_app(
    *,
    settings: Settings | None = None,
    pipeline: DocumentPipeline | None = None,
    job_service: DocumentJobService | None = None,
) -> FastAPI:
    selected_settings = settings or get_settings()
    configure_logging(
        allow_sensitive_debug_logging=selected_settings.allow_sensitive_debug_logging
    )
    metrics = MetricsRegistry()
    selected_pipeline = pipeline or DocumentPipeline(selected_settings, metrics=metrics)
    selected_store = getattr(selected_pipeline, "store", None)
    if pipeline is not None:
        pipeline_metrics = getattr(selected_pipeline, "metrics", None)
        if isinstance(pipeline_metrics, MetricsRegistry):
            metrics = pipeline_metrics

    if job_service is None:
        if pipeline is None:

            def pipeline_factory(mode: ProcessingMode) -> DocumentPipeline:
                mode_settings = ProcessingModePolicy.for_mode(
                    selected_settings, mode
                ).settings
                if mode_settings == selected_settings:
                    return selected_pipeline
                return DocumentPipeline(
                    mode_settings,
                    artifact_store=selected_store,
                    metrics=metrics,
                )

        else:

            def pipeline_factory(mode: ProcessingMode) -> DocumentPipeline:
                del mode
                return selected_pipeline

        selected_job_service = DocumentJobService(
            selected_settings,
            pipeline_factory=pipeline_factory,
            artifact_store=selected_store,
            job_repository=FileJobRepository(selected_settings.storage_root),
            document_repository=FileDocumentRepository(selected_settings.storage_root),
            metrics=metrics,
        )
    else:
        selected_job_service = job_service
        metrics = getattr(selected_job_service, "metrics", metrics)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        yield
        selected_job_service.shutdown()

    application = FastAPI(
        title="OCR Platform",
        version=selected_settings.pipeline_version,
        description="Provenance-preserving OCR and document dataset pipeline.",
        lifespan=lifespan,
    )
    application.state.settings = selected_settings
    application.state.pipeline = selected_pipeline
    application.state.job_service = selected_job_service
    application.state.metrics = metrics
    api_key_dependency = build_api_key_dependency(selected_settings)

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_request_id(request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.exception_handler(OcrPlatformError)
    async def platform_error_handler(request: Request, exc: OcrPlatformError) -> JSONResponse:
        return _error_response(
            request,
            exc.details.code,
            exc.details.message,
            exc.details.retryable,
            exc.details.http_status,
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(request, "invalid_request", "request validation failed", False, 422)

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", request.headers.get("X-Request-ID", "-"))
        logger.exception("unexpected request failure", extra={"request_id": request_id})
        return _error_response(
            request,
            "internal_error",
            "an internal processing error occurred",
            False,
            500,
        )

    @application.get("/healthz", response_model=HealthResponse)
    async def health() -> HealthResponse:
        capabilities = _capability_payload(selected_pipeline, selected_settings)
        return HealthResponse(
            status="ok",
            service="ocr-platform",
            pipeline_version=selected_settings.pipeline_version,
            capabilities=capabilities,
        )

    @application.get("/readyz", response_model=HealthResponse)
    async def readiness() -> HealthResponse:
        selected_settings.storage_root.mkdir(parents=True, exist_ok=True)
        if not os.access(selected_settings.storage_root, os.W_OK):
            raise InvalidDocumentError("artifact storage is not writable")
        capabilities = _capability_payload(selected_pipeline, selected_settings)
        if selected_settings.environment in {"staging", "production"} and any(
            not bool(item["available"]) for item in capabilities
        ):
            raise OcrPlatformError(
                ErrorDetails(
                    "backend_not_ready",
                    "required OCR capability is unavailable",
                    503,
                    True,
                )
            )
        return HealthResponse(
            status="ready",
            service="ocr-platform",
            pipeline_version=selected_settings.pipeline_version,
            capabilities=capabilities,
        )

    @application.get("/metrics")
    async def metrics_endpoint(
        _: Annotated[str, Depends(api_key_dependency)],
    ) -> dict[str, list[dict[str, object]]]:
        return metrics.snapshot()

    @application.post(
        "/v1/documents",
        response_model=JobSubmissionResponse,
        status_code=202,
    )
    async def submit_document(
        request: Request,
        file: Annotated[UploadFile, File(...)],
        mode: Annotated[ProcessingMode, Form()] = ProcessingMode.BALANCED,
        _: Annotated[str, Depends(api_key_dependency)] = "",
    ) -> JobSubmissionResponse:
        filename = validate_filename(file.filename)
        declared_type = file.content_type
        try:
            data = await read_upload_bytes(
                file, max_bytes=selected_settings.max_upload_bytes
            )
            detected_type = validate_upload_content(
                data,
                declared_content_type=declared_type,
                allowed_content_types=selected_settings.allowed_content_types,
            )
            idempotency_key = request.headers.get("Idempotency-Key") or request.headers.get(
                "X-Idempotency-Key"
            )
            submission = selected_job_service.submit_bytes(
                data,
                filename=filename,
                content_type=detected_type,
                mode=mode,
                idempotency_key=idempotency_key,
            )
            request.state.job_id = submission.job.job_id
            request.state.document_id = submission.job.document_id
            return JobSubmissionResponse(
                job_id=submission.job.job_id,
                document_id=submission.job.document_id,
                status=submission.job.status,
                mode=submission.job.mode,
                source_checksum=submission.job.source_checksum,
                configuration_hash=submission.job.configuration_hash,
                progress=submission.job.progress,
                created_at=submission.job.created_at,
                idempotent_replay=submission.idempotent_replay,
            )
        finally:
            await file.close()

    @application.get("/v1/jobs/{job_id}", response_model=JobRecord)
    async def get_job(
        request: Request,
        job_id: str,
        _: Annotated[str, Depends(api_key_dependency)],
    ) -> JobRecord:
        _validate_resource_id(job_id, resource="job")
        request.state.job_id = job_id
        job = selected_job_service.get_job(job_id)
        request.state.document_id = job.document_id
        return job

    @application.get("/v1/documents/{document_id}", response_model=Document)
    async def get_document(
        request: Request,
        document_id: str,
        _: Annotated[str, Depends(api_key_dependency)],
    ) -> Document:
        _validate_resource_id(document_id, resource="document")
        request.state.document_id = document_id
        return selected_job_service.get_document(document_id)

    @application.delete("/v1/documents/{document_id}")
    async def delete_document(
        request: Request,
        document_id: str,
        _: Annotated[str, Depends(api_key_dependency)],
    ) -> dict[str, object]:
        _validate_resource_id(document_id, resource="document")
        request.state.document_id = document_id
        return selected_job_service.delete_document(document_id).to_payload()

    @application.get("/v1/documents/{document_id}/manifest")
    async def get_manifest(
        request: Request,
        document_id: str,
        policy: str = "accepted_verified",
        _: Annotated[str, Depends(api_key_dependency)] = "",
    ) -> dict[str, object]:
        _validate_resource_id(document_id, resource="document")
        request.state.document_id = document_id
        selected_policy = _parse_export_policy(policy)
        exported = selected_job_service.export_document(
            document_id,
            formats=("json",),
            policy=selected_policy,
        )
        return exported.manifest

    @application.get("/v1/documents/{document_id}/pages/{page}/image")
    async def get_page_image(
        request: Request,
        document_id: str,
        page: int,
        _: Annotated[str, Depends(api_key_dependency)],
    ) -> Response:
        _validate_resource_id(document_id, resource="document")
        request.state.document_id = document_id
        if page <= 0:
            raise InvalidDocumentError("page number must be positive")
        document = selected_job_service.get_document(document_id)
        if page > len(document.pages):
            raise InvalidDocumentError("page number is out of range")
        rendered_uri = document.pages[page - 1].rendered_uri
        if not rendered_uri:
            raise ArtifactStorageError("page image is unavailable")
        image_bytes = read_artifact_uri(selected_job_service.artifact_store, rendered_uri)
        return Response(content=image_bytes, media_type="image/png")

    @application.get("/v1/documents/{document_id}/exports/{format}")
    async def get_export(
        request: Request,
        document_id: str,
        format: str,
        policy: str = "accepted_verified",
        _: Annotated[str, Depends(api_key_dependency)] = "",
    ) -> Response:
        _validate_resource_id(document_id, resource="document")
        request.state.document_id = document_id
        if format not in {"json", "txt", "md", "manifest", "pages", "crops"}:
            raise InvalidDocumentError("unsupported export format")
        selected_policy = _parse_export_policy(policy)
        selected_format = "json" if format == "manifest" else format
        exported = selected_job_service.export_document(
            document_id,
            formats=(selected_format,),
            policy=selected_policy,
        )
        if format == "manifest":
            return FileResponse(
                exported.manifest_path,
                media_type="application/json",
                filename="manifest.json",
            )
        if format in {"json", "txt", "md"}:
            filename = {
                "json": "document.json",
                "txt": "document.txt",
                "md": "document.md",
            }[format]
            path = exported.root / filename
            if not path.is_file():
                raise ArtifactStorageError("requested export artifact is unavailable")
            media_type = {
                "json": "application/json",
                "txt": "text/plain",
                "md": "text/markdown",
            }[format]
            return FileResponse(path, media_type=media_type, filename=filename)
        files = sorted(
            path.relative_to(exported.root).as_posix()
            for path in exported.root.rglob("*")
            if path.is_file()
        )
        return JSONResponse(
            content={
                "document_id": document_id,
                "format": format,
                "policy": selected_policy.value,
                "files": files,
            }
        )

    @application.post("/v1/documents/process", response_model=Document)
    async def process_document(
        request: Request,
        file: Annotated[UploadFile, File(...)],
        _: Annotated[str, Depends(api_key_dependency)],
    ) -> Document:
        filename = validate_filename(file.filename)
        temporary_path: Path | None = None
        try:
            data = await read_upload_bytes(
                file, max_bytes=selected_settings.max_upload_bytes
            )
            selected_type = validate_upload_content(
                data,
                declared_content_type=file.content_type,
                allowed_content_types=selected_settings.allowed_content_types,
            )
            with tempfile.NamedTemporaryFile(
                prefix="ocr-upload-", suffix=".bin", delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(data)
            return selected_pipeline.process_path(
                temporary_path,
                filename=filename,
                declared_content_type=selected_type,
            )
        finally:
            await file.close()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    return application


def _capability_payload(
    pipeline: object,
    settings: Settings,
) -> list[dict[str, object]]:
    backends = getattr(pipeline, "backends", ())
    try:
        device = resolve_device(settings.device)
    except OcrPlatformError as exc:
        return [
            {
                "backend": "runtime",
                "model": "device",
                "model_version": "configured",
                "available": False,
                "device": settings.device,
                "reason": exc.details.message,
            }
        ]
    return [
        inspect_backend(backend, device=device).to_payload()
        for backend in backends
    ]


def _parse_export_policy(value: str) -> DatasetExportPolicy:
    try:
        return DatasetExportPolicy(value)
    except ValueError as exc:
        raise InvalidDocumentError("export policy is invalid") from exc


def _validate_resource_id(value: str, *, resource: str) -> None:
    if _SAFE_RESOURCE_ID.fullmatch(value):
        return
    if resource == "job":
        raise JobNotFoundError()
    raise DocumentNotFoundError()


def _error_response(
    request: Request,
    code: str,
    message: str,
    retryable: bool,
    status_code: int,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", request.headers.get("X-Request-ID", "-"))
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
            job_id=getattr(request.state, "job_id", None),
            document_id=getattr(request.state, "document_id", None),
        ).model_dump(mode="json", exclude_none=True),
    )


app = create_app()
