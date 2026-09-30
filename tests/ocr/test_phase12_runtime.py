from contextlib import suppress

import pytest

from ocr_platform.errors import BackendUnavailableError
from ocr_platform.ocr.runtime import (
    InferenceGate,
    LazyModel,
    RuntimeDevice,
    inspect_backend,
    resolve_device,
)


def test_lazy_model_loads_once_and_exposes_safe_capability() -> None:
    calls: list[str] = []
    model = LazyModel(
        model="test-model",
        model_version="1",
        loader=lambda device: calls.append(device) or object(),
        device="cpu",
    )

    first = model.load()
    second = model.load()

    assert first is second
    assert calls == ["cpu"]
    assert model.capability().to_payload() == {
        "backend": "model-runtime",
        "model": "test-model",
        "model_version": "1",
        "available": True,
        "device": "cpu",
    }


def test_unavailable_backend_capability_does_not_include_document_content() -> None:
    backend = type(
        "Unavailable",
        (),
        {
            "name": "unavailable",
            "model": "none",
            "model_version": "none",
            "reason": "model weights are not installed",
        },
    )()
    capability = inspect_backend(backend, device="cpu")

    assert capability.available is False
    assert "document" not in str(capability.to_payload()).lower()


def test_explicit_cuda_failure_is_typed_and_cpu_is_always_safe() -> None:
    assert resolve_device(RuntimeDevice.CPU) == "cpu"
    with suppress(BackendUnavailableError):
        resolve_device(RuntimeDevice.CUDA)


def test_inference_gate_rejects_invalid_concurrency() -> None:
    with pytest.raises(ValueError):
        InferenceGate(0)
