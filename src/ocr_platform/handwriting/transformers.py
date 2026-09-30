"""Optional Transformer-based handwriting recognition adapter.

The adapter is model-agnostic. A deployment supplies a specific local or
Hugging Face model identifier and is responsible for validating its language
coverage and licensing. The base installation never imports Transformers or
Torch, and no confidence probability is fabricated when the model does not
expose a calibrated score.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Mapping
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from typing import Any

from ocr_platform.domain import ExtractionMethod, TextType
from ocr_platform.errors import (
    BackendUnavailableError,
    ImageDecodeError,
    ProcessingError,
)
from ocr_platform.ocr.models import BackendTextLine, OcrRegion, OcrResult


class TransformersHandwritingBackend:
    """Run a configured TrOCR-style vision encoder/decoder model.

    ``model_id`` is either a Hugging Face repository identifier or a local
    model directory. ``model_path`` is retained as a compatibility alias for
    deployments that only configured ``OCR_HANDWRITING_MODEL_PATH``.
    ``local_files_only`` defaults to true so a worker cannot unexpectedly
    download model weights. Remote downloads and remote model code require
    explicit configuration and a controlled model provisioning environment.
    """

    name = "transformers_htr"
    confidence_scale = "uncalibrated_none"
    backend_family = "transformers-htr"

    def __init__(
        self,
        *,
        model_id: str | None = None,
        processor_id: str | None = None,
        revision: str | None = None,
        model_path: str | None = None,
        device: str = "auto",
        local_files_only: bool = True,
        trust_remote_code: bool = False,
        max_generation_length: int = 256,
        max_new_tokens: int | None = None,
        cache_dir: str | None = None,
        language: str = "und",
        script: str = "Unknown",
        max_image_pixels: int = 12_000_000,
        timeout_seconds: int = 120,
    ) -> None:
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("HTR device must be auto, cpu, or cuda")
        if max_new_tokens is not None:
            max_generation_length = max_new_tokens
        if not 1 <= max_generation_length <= 4096:
            raise ValueError("HTR max generation length must be between 1 and 4096")
        if max_image_pixels <= 0:
            raise ValueError("HTR maximum image pixels must be positive")
        if timeout_seconds <= 0:
            raise ValueError("HTR timeout must be positive")
        self.model_id = _clean_optional(model_id)
        self.processor_id = _clean_optional(processor_id)
        self.revision = _clean_optional(revision)
        self.model_path = _clean_optional(model_path)
        self.device = device
        self.local_files_only = local_files_only
        self.trust_remote_code = trust_remote_code
        self.max_generation_length = max_generation_length
        self.cache_dir = _clean_optional(cache_dir)
        self.language = language
        self.script = script
        self.max_image_pixels = max_image_pixels
        self.timeout_seconds = timeout_seconds
        self._processor: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._resolved_device: str | None = None
        self._model_version = self.revision or "unloaded"

    @property
    def model(self) -> str:
        return self.model_id or self.model_path or "unconfigured"

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def available(self) -> bool:
        """Return capability availability without loading model weights."""

        return self.unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        source = self._model_source
        if source is None:
            return "HTR model path or model ID is not configured"
        if self.model_id is None and not Path(source).expanduser().exists():
            return "configured HTR model path does not exist"
        for module_name in ("torch", "transformers"):
            if not _module_available(module_name):
                return "Transformers HTR requires the optional 'htr' extra"
        return None

    @property
    def capability_reason(self) -> str | None:
        """Alias used by capability reporting integrations."""

        return self.unavailable_reason

    @property
    def reason(self) -> str:
        """Compatibility field used by generic capability inspection."""

        return self.unavailable_reason or "configured HTR runtime is available"

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        processor, model, torch = self._load_model()
        image = self._decode_image(image_bytes)
        try:
            inputs = processor(images=image, return_tensors="pt")
            inputs = _move_inputs(inputs, self._resolved_device or self.device)
            generation_kwargs: dict[str, object] = {
                "max_new_tokens": self.max_generation_length,
                "max_time": float(self.timeout_seconds),
            }
            with _inference_context(torch):
                generated = model.generate(**inputs, **generation_kwargs)
            decoded = processor.batch_decode(generated, skip_special_tokens=True)
            text = str(decoded[0]) if decoded else ""
        except ProcessingError:
            raise
        except RuntimeError as exc:
            if _looks_like_oom(exc):
                raise ProcessingError(
                    "Transformers HTR inference exhausted the configured device memory",
                    retryable=True,
                ) from exc
            raise ProcessingError("Transformers HTR inference failed", retryable=True) from exc
        except Exception as exc:
            raise ProcessingError("Transformers HTR inference failed", retryable=True) from exc

        runtime_metadata = (
            ("device", str(getattr(model, "device", self._resolved_device or self.device))),
            ("model_id", self.model),
            ("processor_id", self.processor_id or self.model),
            ("revision", self.model_version),
            ("local_files_only", str(self.local_files_only).lower()),
            ("trust_remote_code", str(self.trust_remote_code).lower()),
            ("max_generation_length", str(self.max_generation_length)),
            ("timeout_seconds", str(self.timeout_seconds)),
            ("image_pixels", str(image.width * image.height)),
            ("preprocess_variant", preprocess_variant),
        )
        common = {
            "backend": self.name,
            "model": self.model,
            "model_version": self.model_version,
            "method": ExtractionMethod.HANDWRITING_RECOGNITION,
            "confidence_scale": self.confidence_scale,
            "dpi": float(dpi),
            "region_scale": float(region_scale),
            "preprocess_variant": preprocess_variant,
            "runtime_metadata": runtime_metadata,
            "backend_family": self.backend_family,
        }
        if not text.strip():
            return OcrResult(
                **common,
                lines=(),
                warnings=("empty_htr_output", "confidence_unavailable"),
            )
        return OcrResult(
            **common,
            lines=(
                BackendTextLine(
                    raw_text=text,
                    # HTR recognizes the supplied crop as one region. This is
                    # source geometry, not a fabricated detector box.
                    bbox=region.bbox,
                    confidence=None,
                    language=self.language,
                    script=self.script,
                    text_type=TextType.HANDWRITTEN,
                ),
            ),
            warnings=("confidence_unavailable",),
        )

    @property
    def _model_source(self) -> str | None:
        return self.model_id or self.model_path

    def _decode_image(self, image_bytes: bytes) -> Any:
        try:
            from PIL import Image
        except ImportError as exc:
            raise BackendUnavailableError("HTR image decoding requires Pillow") from exc
        try:
            with Image.open(BytesIO(image_bytes)) as opened:
                width, height = opened.size
                if width <= 0 or height <= 0:
                    raise ImageDecodeError("HTR image dimensions must be positive")
                if width * height > self.max_image_pixels:
                    raise ImageDecodeError("HTR image exceeds configured pixel limit")
                return opened.convert("RGB")
        except ImageDecodeError:
            raise
        except Exception as exc:
            raise ImageDecodeError("HTR image could not be decoded") from exc

    def _load_model(self) -> tuple[Any, Any, Any]:
        if self._processor is not None and self._model is not None and self._torch is not None:
            return self._processor, self._model, self._torch
        source = self._model_source
        if source is None:
            raise BackendUnavailableError(
                "HTR model path or model ID is not configured"
            )
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
            processor_class = getattr(transformers, "AutoProcessor", None)
            model_class = getattr(transformers, "VisionEncoderDecoderModel", None)
            if model_class is None:
                model_class = getattr(transformers, "AutoModelForVision2Seq", None)
            if processor_class is None or model_class is None:
                raise AttributeError("required Transformers model classes are unavailable")
        except (ImportError, AttributeError) as exc:
            raise BackendUnavailableError(
                "Transformers HTR requires the optional 'htr' extra"
            ) from exc
        device = self._resolve_device(torch)
        model_kwargs = self._pretrained_kwargs()
        processor_source = self.processor_id or source
        try:
            processor = processor_class.from_pretrained(processor_source, **model_kwargs)
            model = model_class.from_pretrained(source, **model_kwargs)
            moved_model = model.to(device)
            if moved_model is not None:
                model = moved_model
            model.eval()
            config = getattr(model, "config", None)
            loaded_version = getattr(config, "_commit_hash", None) or getattr(
                config, "revision", None
            )
            self._model_version = str(loaded_version or self.revision or "unknown")
        except RuntimeError as exc:
            if _looks_like_oom(exc):
                raise ProcessingError(
                    "Transformers HTR model loading exhausted the configured device memory",
                    retryable=True,
                ) from exc
            raise BackendUnavailableError("configured HTR model could not be loaded") from exc
        except Exception as exc:
            raise BackendUnavailableError(
                "configured HTR model could not be loaded from the configured source"
            ) from exc
        self._processor, self._model, self._torch = processor, model, torch
        self._resolved_device = device
        return processor, model, torch

    def _pretrained_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "local_files_only": self.local_files_only,
            "trust_remote_code": self.trust_remote_code,
        }
        if self.revision is not None:
            kwargs["revision"] = self.revision
        if self.cache_dir is not None:
            kwargs["cache_dir"] = self.cache_dir
        return kwargs

    def _resolve_device(self, torch: Any) -> str:
        if self.device == "cpu":
            return "cpu"
        try:
            cuda_available = bool(torch.cuda.is_available())
        except Exception as exc:
            if self.device == "cuda":
                raise BackendUnavailableError("CUDA HTR runtime is unavailable") from exc
            cuda_available = False
        if self.device == "cuda" and not cuda_available:
            raise BackendUnavailableError("CUDA HTR was requested but no CUDA device is available")
        return "cuda" if cuda_available else "cpu"


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _module_available(module_name: str) -> bool:
    if module_name in sys.modules:
        return sys.modules[module_name] is not None
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _move_inputs(inputs: object, device: str) -> object:
    if hasattr(inputs, "to"):
        return inputs.to(device)
    if isinstance(inputs, Mapping):
        return {
            key: value.to(device) if hasattr(value, "to") else value
            for key, value in inputs.items()
        }
    raise ProcessingError("Transformers HTR processor returned an unsupported input structure")


def _inference_context(torch: Any) -> object:
    inference_mode = getattr(torch, "inference_mode", None)
    return inference_mode() if callable(inference_mode) else nullcontext()


def _looks_like_oom(error: RuntimeError) -> bool:
    message = str(error).lower()
    return "out of memory" in message or ("cuda error" in message and "memory" in message)


__all__ = ["TransformersHandwritingBackend"]
