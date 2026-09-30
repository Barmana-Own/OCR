"""Provider-neutral model lifecycle, device selection, and inference limits."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, Semaphore
from typing import Protocol, TypeVar

from ocr_platform.errors import BackendUnavailableError


class RuntimeDevice(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"


class ModelLoadMode(StrEnum):
    LAZY = "lazy"
    STARTUP = "startup"


def resolve_device(requested: str) -> str:
    """Resolve a configured device without importing GPU libraries on CPU paths."""

    selected = requested.strip().lower()
    if selected == RuntimeDevice.CPU:
        return RuntimeDevice.CPU.value
    if selected not in {RuntimeDevice.AUTO, RuntimeDevice.CUDA}:
        raise ValueError("device must be auto, cpu, or cuda")
    if importlib.util.find_spec("torch") is None:
        if selected == RuntimeDevice.CUDA:
            raise BackendUnavailableError("CUDA runtime is not installed")
        return RuntimeDevice.CPU.value
    try:
        import torch

        available = bool(torch.cuda.is_available())
    except Exception as exc:
        if selected == RuntimeDevice.CUDA:
            raise BackendUnavailableError("CUDA runtime is unavailable") from exc
        return RuntimeDevice.CPU.value
    if selected == RuntimeDevice.CUDA and not available:
        raise BackendUnavailableError("CUDA device is unavailable")
    return RuntimeDevice.CUDA.value if available else RuntimeDevice.CPU.value


@dataclass(frozen=True)
class BackendCapability:
    backend: str
    model: str
    model_version: str
    available: bool
    device: str
    reason: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "backend": self.backend,
            "model": self.model,
            "model_version": self.model_version,
            "available": self.available,
            "device": self.device,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def inspect_backend(backend: object, *, device: str) -> BackendCapability:
    name = str(getattr(backend, "name", backend.__class__.__name__))
    model = str(getattr(backend, "model", "unknown"))
    version = str(getattr(backend, "model_version", "unknown"))
    available = bool(getattr(backend, "available", name != "unavailable"))
    reason = None if available else str(getattr(backend, "reason", "backend unavailable"))
    return BackendCapability(name, model, version, available, device, reason)


T = TypeVar("T")


class ModelLoader(Protocol[T]):
    def __call__(self, device: str) -> T: ...


class LazyModel[T]:
    """Load a model once and retain a safe capability state after failure."""

    def __init__(
        self,
        *,
        model: str,
        model_version: str,
        loader: Callable[[str], T],
        device: str = RuntimeDevice.AUTO,
        load_mode: str = ModelLoadMode.LAZY,
    ) -> None:
        self.model = model
        self.model_version = model_version
        self._loader = loader
        self._requested_device = device
        self._load_mode = ModelLoadMode(load_mode)
        self._lock = Lock()
        self._loaded: T | None = None
        self._resolved_device: str | None = None
        self._error: str | None = None
        if self._load_mode is ModelLoadMode.STARTUP:
            self.load()

    @property
    def is_loaded(self) -> bool:
        return self._loaded is not None

    def load(self) -> T:
        if self._loaded is not None:
            return self._loaded
        with self._lock:
            if self._loaded is not None:
                return self._loaded
            try:
                self._resolved_device = resolve_device(self._requested_device)
                self._loaded = self._loader(self._resolved_device)
                self._error = None
                return self._loaded
            except BackendUnavailableError as exc:
                self._error = exc.details.message
                raise
            except Exception as exc:
                self._error = "model loading failed"
                raise BackendUnavailableError(self._error) from exc

    def capability(self) -> BackendCapability:
        return BackendCapability(
            backend="model-runtime",
            model=self.model,
            model_version=self.model_version,
            available=self._loaded is not None,
            device=self._resolved_device or self._requested_device,
            reason=self._error,
        )


class InferenceGate:
    """Bound concurrent inference without coupling to an execution provider."""

    def __init__(self, max_concurrency: int = 1) -> None:
        if max_concurrency <= 0:
            raise ValueError("inference concurrency must be positive")
        self._semaphore = Semaphore(max_concurrency)

    @contextmanager
    def slot(self) -> Iterator[None]:
        with self._semaphore:
            yield
