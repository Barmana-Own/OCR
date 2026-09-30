"""Safe, typed application errors and processing-boundary failures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDetails:
    code: str
    message: str
    http_status: int = 400
    retryable: bool = False


class OcrPlatformError(Exception):
    """Base error that is safe to expose through the API."""

    details: ErrorDetails

    def __init__(self, details: ErrorDetails) -> None:
        super().__init__(details.message)
        self.details = details


class ConfigurationError(OcrPlatformError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorDetails("configuration_error", message, 500))


class AuthenticationError(OcrPlatformError):
    def __init__(self, message: str = "API authentication is required") -> None:
        super().__init__(ErrorDetails("authentication_required", message, 401))


class AuthorizationError(OcrPlatformError):
    def __init__(self, message: str = "API key is not authorized") -> None:
        super().__init__(ErrorDetails("forbidden", message, 403))


class NotFoundError(OcrPlatformError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(ErrorDetails(code, message, 404))


class JobNotFoundError(NotFoundError):
    def __init__(self, message: str = "job was not found") -> None:
        super().__init__("job_not_found", message)


class DocumentNotFoundError(NotFoundError):
    def __init__(self, message: str = "document was not found") -> None:
        super().__init__("document_not_found", message)


class DocumentBusyError(OcrPlatformError):
    def __init__(
        self, message: str = "document cannot be deleted while processing is active"
    ) -> None:
        super().__init__(ErrorDetails("document_busy", message, 409, True))


class JobNotCompletedError(OcrPlatformError):
    def __init__(self, message: str = "document processing is not complete") -> None:
        super().__init__(ErrorDetails("job_not_completed", message, 409))


class IdempotencyConflictError(OcrPlatformError):
    def __init__(
        self, message: str = "idempotency key was used for a different submission"
    ) -> None:
        super().__init__(ErrorDetails("idempotency_conflict", message, 409))


class QueueCapacityError(OcrPlatformError):
    def __init__(self, message: str = "processing queue is at capacity") -> None:
        super().__init__(ErrorDetails("job_queue_full", message, 429, True))


class UnsupportedDocumentError(OcrPlatformError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorDetails("unsupported_document", message, 415))


class InvalidDocumentError(OcrPlatformError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorDetails("invalid_document", message, 422))


class CorruptPdfError(InvalidDocumentError):
    def __init__(self, message: str = "PDF is corrupt or cannot be parsed") -> None:
        OcrPlatformError.__init__(self, ErrorDetails("corrupt_pdf", message, 422))


class PasswordProtectedPdfError(InvalidDocumentError):
    def __init__(self, message: str = "password-protected PDFs are not supported") -> None:
        OcrPlatformError.__init__(self, ErrorDetails("password_protected_pdf", message, 422))


class PageRenderError(InvalidDocumentError):
    def __init__(self, message: str = "page could not be rendered", retryable: bool = True) -> None:
        OcrPlatformError.__init__(
            self, ErrorDetails("page_render_failure", message, 422, retryable)
        )


class ImageDecodeError(InvalidDocumentError):
    def __init__(self, message: str = "image could not be decoded") -> None:
        OcrPlatformError.__init__(self, ErrorDetails("image_decode_failure", message, 422))


class InvalidGeometryError(InvalidDocumentError):
    def __init__(self, message: str = "geometry is invalid") -> None:
        OcrPlatformError.__init__(self, ErrorDetails("invalid_geometry", message, 422))


class BackendUnavailableError(OcrPlatformError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorDetails("ocr_backend_unavailable", message, 503, True))


class OcrBackendFailure(OcrPlatformError):
    def __init__(self, message: str = "OCR backend failed", retryable: bool = True) -> None:
        super().__init__(ErrorDetails("ocr_backend_failure", message, 502, retryable))


class ProcessingError(OcrPlatformError):
    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(ErrorDetails("processing_error", message, 500, retryable))


class ArtifactStorageError(OcrPlatformError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorDetails("artifact_storage_error", message, 500))


class StorageFailureError(ArtifactStorageError):
    def __init__(
        self, message: str = "artifact storage operation failed", retryable: bool = True
    ) -> None:
        OcrPlatformError.__init__(
            self, ErrorDetails("storage_failure", message, 500, retryable)
        )


class QualityGateError(OcrPlatformError):
    def __init__(self, message: str = "quality gate failed") -> None:
        super().__init__(ErrorDetails("quality_gate_failure", message, 422))


# Semantic aliases keep API-boundary terminology explicit without breaking the
# existing names used by ingestion/storage modules.
UnsupportedFileTypeError = UnsupportedDocumentError
StorageError = StorageFailureError

