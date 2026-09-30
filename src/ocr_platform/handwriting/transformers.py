"""Optional Transformer-based handwriting recognition adapter.

The adapter requires an explicitly configured local or mounted model path. It
does not download weights and reports an unavailable capability when the
runtime or model is absent.
"""

from __future__ import annotations

import importlib
from io import BytesIO
from typing import Any

from ocr_platform.domain import ExtractionMethod, TextType
from ocr_platform.errors import BackendUnavailableError, ProcessingError
from ocr_platform.ocr.models import BackendTextLine, OcrRegion, OcrResult


class TransformersHandwritingBackend:
    name = "transformers_htr"
    model = "vision-encoder-decoder"
    confidence_scale = "not_calibrated"
    backend_family = "transformers-htr"

    def __init__(
        self,
        *,
        model_path: str | None = None,
        device: str = "auto",
        max_new_tokens: int = 256,
    ) -> None:
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("HTR device must be auto, cpu, or cuda")
        if max_new_tokens <= 0:
            raise ValueError("HTR max_new_tokens must be positive")
        self.model_path = model_path
        self.device = device
        self.max_new_tokens = max_new_tokens
        self._processor: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._model_version = "unavailable"

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def available(self) -> bool:
        return bool(self.model_path)

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
        try:
            from PIL import Image

            with Image.open(BytesIO(image_bytes)) as opened:
                image = opened.convert("RGB")
            inputs = processor(images=image, return_tensors="pt")
            inputs = {
                key: value.to(model.device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
            with torch.inference_mode():
                generated = model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            decoded = processor.batch_decode(generated, skip_special_tokens=True)
            text = decoded[0].strip() if decoded else ""
        except Exception as exc:
            raise ProcessingError("handwriting recognition model failed", retryable=True) from exc
        if not text:
            return OcrResult(
                backend=self.name,
                model=self.model,
                model_version=self.model_version,
                method=ExtractionMethod.HANDWRITING_RECOGNITION,
                confidence_scale=self.confidence_scale,
                dpi=float(dpi),
                region_scale=float(region_scale),
                preprocess_variant=preprocess_variant,
                lines=(),
                runtime_metadata=(("device", str(model.device)),),
                warnings=("HTR model returned empty text",),
                backend_family=self.backend_family,
            )
        return OcrResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            method=ExtractionMethod.HANDWRITING_RECOGNITION,
            confidence_scale=self.confidence_scale,
            dpi=float(dpi),
            region_scale=float(region_scale),
            preprocess_variant=preprocess_variant,
            lines=(
                BackendTextLine(
                    raw_text=text,
                    bbox=(0.0, 0.0, float(region.bbox[2]), float(region.bbox[3])),
                    confidence=None,
                    language=_infer_language(text),
                    script=_infer_script(text),
                    text_type=TextType.HANDWRITTEN,
                ),
            ),
            runtime_metadata=(
                ("device", str(model.device)),
                ("max_new_tokens", str(self.max_new_tokens)),
            ),
            backend_family=self.backend_family,
        )

    def _load_model(self) -> tuple[Any, Any, Any]:
        if self._processor is not None and self._model is not None and self._torch is not None:
            return self._processor, self._model, self._torch
        if not self.model_path:
            raise BackendUnavailableError(
                "HTR model path is not configured; set OCR_HANDWRITING_MODEL_PATH"
            )
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
            processor_class = transformers.AutoProcessor
            model_class = transformers.VisionEncoderDecoderModel
        except (ImportError, AttributeError) as exc:
            raise BackendUnavailableError(
                "Transformers HTR requires the optional 'htr' extra"
            ) from exc
        device = self._resolve_device(torch)
        try:
            processor = processor_class.from_pretrained(self.model_path, local_files_only=True)
            model = model_class.from_pretrained(self.model_path, local_files_only=True)
            model.to(device)
            model.eval()
            config_version = getattr(getattr(model, "config", None), "_commit_hash", None)
            self._model_version = str(config_version or self.model_path)
        except Exception as exc:
            raise BackendUnavailableError(
                "configured HTR model could not be loaded from local files"
            ) from exc
        self._processor, self._model, self._torch = processor, model, torch
        return processor, model, torch

    def _resolve_device(self, torch: Any) -> str:
        if self.device == "cuda":
            if not torch.cuda.is_available():
                raise BackendUnavailableError(
                    "CUDA HTR was requested but no CUDA device is available"
                )
            return "cuda"
        if self.device == "auto" and torch.cuda.is_available():
            return "cuda"
        return "cpu"


def _infer_language(text: str) -> str:
    has_rtl = any("\u0600" <= char <= "\u06ff" for char in text)
    has_latin = any(char.isascii() and char.isalpha() for char in text)
    if has_rtl and has_latin:
        return "fa+en"
    if has_rtl:
        return "fa"
    if has_latin:
        return "en"
    return "und"


def _infer_script(text: str) -> str:
    has_rtl = any("\u0600" <= char <= "\u06ff" for char in text)
    has_latin = any(char.isascii() and char.isalpha() for char in text)
    if has_rtl and has_latin:
        return "Arabic+Latin"
    if has_rtl:
        return "Arabic"
    if has_latin:
        return "Latin"
    return "Unknown"


__all__ = ["TransformersHandwritingBackend"]
