from .models import BackendTextLine, OcrBackend, OcrRegion, OcrResult
from .runtime import (
    BackendCapability,
    InferenceGate,
    LazyModel,
    ModelLoadMode,
    RuntimeDevice,
    inspect_backend,
    resolve_device,
)
from .verification.engine import VerificationEngine, VerificationOutcome, VerificationPolicy

__all__ = [
    "BackendTextLine",
    "OcrBackend",
    "OcrRegion",
    "OcrResult",
    "BackendCapability",
    "InferenceGate",
    "LazyModel",
    "ModelLoadMode",
    "RuntimeDevice",
    "inspect_backend",
    "resolve_device",
    "VerificationEngine",
    "VerificationOutcome",
    "VerificationPolicy",
]
