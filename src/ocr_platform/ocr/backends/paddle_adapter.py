"""Optional PaddleOCR printed-text adapter.

PaddleOCR is kept behind this module so the base installation never imports
its runtime or downloads model weights. Paddle recognizers are configured one
language at a time; a mixed Persian/English configuration is expanded by the
factory into separate provider-language instances. A Persian request maps to
Paddle's Arabic-script recognizer, but that mapping is not a claim of Persian
language accuracy.
"""

from __future__ import annotations

import importlib
import inspect
import math
import re
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ocr_platform.domain import ExtractionMethod, PolygonPoint, TextType
from ocr_platform.errors import BackendUnavailableError, ConfigurationError, ProcessingError

from ..models import BackendTextLine, BackendWord, OcrRegion, OcrResult


@dataclass(frozen=True, slots=True)
class PaddleLanguage:
    """A configured logical language and its one-model Paddle language."""

    requested: str
    provider: str
    capability_note: str | None = None


# These aliases describe provider language names supported by this adapter,
# not every language exposed by every PaddleOCR release.
_PADDLE_LANGUAGE_ALIASES = {
    "ar": "ar",
    "ara": "ar",
    "arabic": "ar",
    "fa": "ar",
    "fas": "ar",
    "en": "en",
    "eng": "en",
    "ch": "ch",
    "chi": "ch",
    "zh": "ch",
    "chinese_cht": "chinese_cht",
    "de": "german",
    "fr": "french",
    "it": "it",
    "es": "es",
    "pt": "pt",
    "ru": "cyrillic",
    "uk": "cyrillic",
    "be": "cyrillic",
    "korean": "korean",
    "japan": "japan",
    "ja": "japan",
    "latin": "latin",
    "cyrillic": "cyrillic",
    "devanagari": "devanagari",
    "ta": "ta",
    "te": "te",
    "ka": "ka",
}


def resolve_paddle_languages(languages: Sequence[str]) -> tuple[PaddleLanguage, ...]:
    """Resolve language codes into deterministic one-model Paddle instances."""

    resolved: list[PaddleLanguage] = []
    seen_provider_languages: set[str] = set()
    for configured in languages:
        value = str(configured).strip().lower()
        if not value:
            continue
        for requested in value.split("+"):
            requested = requested.strip()
            if not requested:
                raise ConfigurationError("PaddleOCR language selection contains an empty item")
            provider = _canonical_paddle_language(requested)
            if provider in seen_provider_languages:
                continue
            seen_provider_languages.add(provider)
            resolved.append(
                PaddleLanguage(
                    requested=requested,
                    provider=provider,
                    capability_note=_language_capability_note(requested, provider),
                )
            )
    if not resolved:
        raise ConfigurationError("PaddleOCR requires at least one configured language")
    return tuple(resolved)


class PaddleOcrBackend:
    """Printed OCR adapter backed by an installed PaddleOCR runtime."""

    name = "paddle"
    model = "paddleocr"
    confidence_scale = "paddle_0_1"
    backend_family = "paddleocr"

    def __init__(
        self,
        *,
        language: str = "en",
        requested_language: str | None = None,
        language_note: str | None = None,
        device: str = "auto",
        model_path: str | Path | None = None,
        cache_path: str | Path | None = None,
        model_load_mode: str = "lazy",
        allow_model_downloads: bool = False,
        timeout_seconds: int = 120,
        show_log: bool = False,
    ) -> None:
        if not language or "+" in language:
            raise ValueError(
                "PaddleOCR requires one language per recognizer; configure "
                "OCR_PADDLE_LANGUAGES for multiple models"
            )
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("PaddleOCR device must be auto, cpu, or cuda")
        if model_load_mode not in {"lazy", "startup"}:
            raise ValueError("PaddleOCR model load mode must be lazy or startup")
        if timeout_seconds <= 0:
            raise ValueError("PaddleOCR timeout must be positive")
        try:
            provider_language = _canonical_paddle_language(language)
        except ConfigurationError as exc:
            raise ValueError(str(exc)) from exc

        self.language = provider_language
        self.requested_language = (requested_language or language).strip().lower()
        self.language_note = language_note or _language_capability_note(
            self.requested_language, self.language
        )
        self.device = device
        self.model_path = _clean_optional(model_path)
        self.cache_path = _clean_optional(cache_path)
        self.model_load_mode = model_load_mode
        self.allow_model_downloads = allow_model_downloads
        self.timeout_seconds = timeout_seconds
        self.show_log = show_log
        self._engine: Any | None = None
        self._package_version = "unavailable"
        self._resolved_device: str | None = None
        self._load_lock = threading.Lock()
        if model_load_mode == "startup":
            self._load_engine()

    @property
    def model_version(self) -> str:
        return self._package_version

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        if not _module_available("paddleocr"):
            return "PaddleOCR is not installed; install the optional 'paddle' extra"
        if self.allow_model_downloads:
            return None
        if not self.model_path:
            return (
                "PaddleOCR local model path is not configured and model downloads are disabled"
            )
        if not Path(self.model_path).expanduser().exists():
            return "configured PaddleOCR model path does not exist"
        return None

    @property
    def reason(self) -> str:
        return self.unavailable_reason or "configured PaddleOCR runtime is available"

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        engine = self._load_engine()
        started = time.monotonic()
        try:
            raw = self._invoke(engine, image_bytes)
        except BackendUnavailableError:
            raise
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError("PaddleOCR failed to process the image", retryable=True) from exc
        if time.monotonic() - started > self.timeout_seconds:
            raise ProcessingError("PaddleOCR timed out", retryable=True)

        try:
            lines, parse_warnings = _parse_result_with_warnings(raw)
        except Exception as exc:
            raise ProcessingError("PaddleOCR returned malformed output", retryable=False) from exc
        runtime_metadata = [
            ("language", self.language),
            ("requested_language", self.requested_language),
            ("model_identifier", f"paddleocr:{self.language}"),
            ("provider_version", self.model_version),
            ("device", self.device),
            ("resolved_device", self._resolved_device or self.device),
            ("api", "ocr_or_predict"),
            ("model_load_mode", self.model_load_mode),
            ("allow_model_downloads", str(self.allow_model_downloads).lower()),
            ("timeout_seconds", str(self.timeout_seconds)),
            ("confidence_policy", "paddle_0_1_raw_no_rescaling"),
        ]
        if self.language_note:
            runtime_metadata.append(("language_capability_note", self.language_note))
        if self.model_path:
            runtime_metadata.append(("model_path_configured", "true"))
        if self.cache_path:
            runtime_metadata.append(("cache_path_configured", "true"))
        return OcrResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            method=ExtractionMethod.OCR,
            confidence_scale=self.confidence_scale,
            dpi=float(dpi),
            region_scale=float(region_scale),
            preprocess_variant=preprocess_variant,
            lines=lines,
            runtime_metadata=tuple(runtime_metadata),
            warnings=parse_warnings,
            backend_family=self.backend_family,
        )

    def _load_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._load_lock:
            if self._engine is not None:
                return self._engine
            unavailable_reason = self.unavailable_reason
            if unavailable_reason is not None:
                raise BackendUnavailableError(unavailable_reason)
            try:
                module = importlib.import_module("paddleocr")
                constructor = module.PaddleOCR
                self._package_version = str(getattr(module, "__version__", "unknown"))
            except (ImportError, AttributeError) as exc:
                raise BackendUnavailableError(
                    "PaddleOCR is not installed; install the optional 'paddle' extra and "
                    "the platform-specific Paddle runtime"
                ) from exc

            self._resolved_device = self._resolve_device()
            kwargs = _constructor_kwargs(
                constructor,
                language=self.language,
                device=self.device,
                resolved_device=self._resolved_device,
                model_path=self.model_path,
                cache_path=self.cache_path,
                show_log=self.show_log,
            )
            try:
                self._engine = constructor(**kwargs)
            except RuntimeError as exc:
                if _looks_like_oom(exc):
                    raise ProcessingError(
                        "PaddleOCR model loading exhausted device memory", retryable=True
                    ) from exc
                raise BackendUnavailableError("PaddleOCR model could not be loaded") from exc
            except Exception as exc:
                raise BackendUnavailableError("PaddleOCR model could not be loaded") from exc
            return self._engine

    def _resolve_device(self) -> str:
        if self.device == "cpu":
            return "cpu"
        try:
            paddle = importlib.import_module("paddle")
        except ImportError as exc:
            if self.device == "cuda":
                raise BackendUnavailableError(
                    "CUDA PaddleOCR was requested but the Paddle runtime is unavailable"
                ) from exc
            return "cpu"
        cuda_available = _paddle_cuda_available(paddle)
        if self.device == "cuda" and not cuda_available:
            raise BackendUnavailableError(
                "CUDA PaddleOCR was requested but no CUDA-capable Paddle runtime is available"
            )
        return "cuda" if cuda_available else "cpu"

    @staticmethod
    def _invoke(engine: Any, image_bytes: bytes) -> Any:
        ocr = getattr(engine, "ocr", None)
        if callable(ocr):
            try:
                parameters = inspect.signature(ocr).parameters
            except (TypeError, ValueError):
                parameters = {}
            return ocr(image_bytes, cls=True) if "cls" in parameters else ocr(image_bytes)
        predictor = getattr(engine, "predict", None)
        if callable(predictor):
            try:
                parameters = inspect.signature(predictor).parameters
            except (TypeError, ValueError):
                parameters = {}
            return predictor(input=image_bytes) if "input" in parameters else predictor(image_bytes)
        raise BackendUnavailableError(
            "installed PaddleOCR runtime exposes no supported inference API"
        )


def _constructor_kwargs(
    constructor: Any,
    *,
    language: str,
    device: str,
    model_path: str | None,
    show_log: bool,
    cache_path: str | None = None,
    resolved_device: str | None = None,
) -> dict[str, Any]:
    """Pass only parameters supported by the installed PaddleOCR version."""

    try:
        parameters = inspect.signature(constructor).parameters
    except (TypeError, ValueError):
        parameters = {}
    kwargs: dict[str, Any] = {}
    if "lang" in parameters:
        kwargs["lang"] = language
    if "show_log" in parameters:
        kwargs["show_log"] = show_log
    selected_device = resolved_device or ("cpu" if device == "auto" else device)
    if "device" in parameters:
        kwargs["device"] = "gpu:0" if selected_device == "cuda" else "cpu"
    if "use_gpu" in parameters:
        kwargs["use_gpu"] = selected_device == "cuda"
    if model_path:
        for parameter in (
            "det_model_dir",
            "rec_model_dir",
            "cls_model_dir",
            "text_detection_model_dir",
            "text_recognition_model_dir",
            "textline_orientation_model_dir",
        ):
            if parameter in parameters:
                kwargs[parameter] = model_path
    if cache_path:
        for parameter in ("cache_dir", "download_dir"):
            if parameter in parameters:
                kwargs[parameter] = cache_path
    return kwargs


def _parse_result(raw: Any) -> Iterable[BackendTextLine]:
    """Normalize PaddleOCR records without exposing provider structures."""

    return _parse_result_with_warnings(raw)[0]


def _parse_result_with_warnings(raw: Any) -> tuple[tuple[BackendTextLine, ...], tuple[str, ...]]:
    records = _records(raw)
    warnings: list[str] = []
    if not records:
        warnings.append("paddle_output_no_records")
        return (), tuple(warnings)
    words: list[BackendWord] = []
    for index, record in enumerate(records):
        parsed, record_warnings = _parse_record_with_warnings(record)
        warnings.extend(f"record_{index}:{warning}" for warning in record_warnings)
        if parsed is not None:
            words.append(parsed)
    if not words:
        warnings.append("paddle_output_no_valid_records")
    return tuple(_group_words_into_lines(words)), tuple(dict.fromkeys(warnings))


def _records(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if hasattr(raw, "to_dict") and callable(raw.to_dict):
        return _records(raw.to_dict())
    if hasattr(raw, "json") and callable(raw.json):
        try:
            import json

            return _records(json.loads(raw.json()))
        except (TypeError, ValueError):
            return []
    if isinstance(raw, Mapping):
        for key in ("res", "result", "results", "ocr_res"):
            if key in raw:
                return _records(raw[key])
        texts = _as_sequence(raw.get("rec_texts"))
        boxes = _as_sequence(raw.get("rec_boxes"))
        if boxes is None:
            boxes = _as_sequence(raw.get("rec_polys"))
        if texts is not None and boxes is not None:
            scores = _as_sequence(raw.get("rec_scores"))
            if scores is None:
                scores = [None] * len(texts)
            return list(zip(boxes, zip(texts, scores, strict=False), strict=False))
        return []
    sequence = _as_sequence(raw)
    if sequence is not None:
        if len(sequence) == 1 and isinstance(sequence[0], Sequence) and not _looks_like_record(
            sequence[0]
        ):
            return list(sequence[0])
        return list(sequence)
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, bytearray, Mapping)):
        return _records(list(raw))
    return []


def _parse_record(record: Any) -> BackendWord | None:
    """Backward-compatible single-record parser used by adapter tests/tools."""

    return _parse_record_with_warnings(record)[0]


def _parse_record_with_warnings(record: Any) -> tuple[BackendWord | None, tuple[str, ...]]:
    warnings: list[str] = []
    if hasattr(record, "to_dict") and callable(record.to_dict):
        try:
            return _parse_record_with_warnings(record.to_dict())
        except (AttributeError, TypeError, ValueError):
            return None, ("malformed_record",)
    if hasattr(record, "json") and callable(record.json):
        try:
            import json

            payload = record.json()
            if isinstance(payload, str):
                payload = json.loads(payload)
            return _parse_record_with_warnings(payload)
        except (AttributeError, TypeError, ValueError):
            return None, ("malformed_record",)
    if isinstance(record, Mapping):
        polygon = _first_present(record, ("polygon", "points", "box"))
        text = record.get("text") or record.get("rec_text")
        confidence = record.get("score")
        if confidence is None:
            confidence = record.get("confidence")
    elif (
        isinstance(record, Sequence)
        and not isinstance(record, (str, bytes, bytearray))
        and len(record) >= 2
    ):
        polygon = record[0]
        text_score = record[1]
        if isinstance(text_score, Sequence) and not isinstance(text_score, (str, bytes)):
            text = text_score[0] if text_score else ""
            confidence = text_score[1] if len(text_score) > 1 else None
        else:
            text = text_score
            confidence = None
    else:
        return None, ("malformed_record",)
    text = "" if text is None else str(text)
    if not text.strip():
        warnings.append("empty_text")
    geometry = _geometry(polygon)
    if geometry is None:
        warnings.append("invalid_geometry")
    if warnings:
        return None, tuple(warnings)
    bbox, typed_polygon = geometry
    normalized_confidence, confidence_warning = _confidence_with_warning(confidence)
    if confidence_warning:
        warnings.append(confidence_warning)
    return (
        BackendWord(
            text=text.strip(),
            bbox=bbox,
            confidence=normalized_confidence,
            reading_order=0,
            polygon=typed_polygon,
        ),
        tuple(warnings),
    )


def _group_words_into_lines(words: list[BackendWord]) -> list[BackendTextLine]:
    ordered = sorted(words, key=lambda word: (word.bbox[1], word.bbox[0]))
    groups: list[list[BackendWord]] = []
    for word in ordered:
        center = (word.bbox[1] + word.bbox[3]) / 2
        height = max(1.0, word.bbox[3] - word.bbox[1])
        matching = next(
            (
                group
                for group in reversed(groups)
                if abs(center - _group_center(group)) <= max(height, _group_height(group)) * 0.7
            ),
            None,
        )
        if matching is None:
            groups.append([word])
        else:
            matching.append(word)
    lines: list[BackendTextLine] = []
    for _reading_order, group in enumerate(groups):
        group.sort(key=lambda word: word.bbox[0])
        text = " ".join(word.text for word in group)
        confidence_values = [word.confidence for word in group if word.confidence is not None]
        x0 = min(word.bbox[0] for word in group)
        y0 = min(word.bbox[1] for word in group)
        x1 = max(word.bbox[2] for word in group)
        y1 = max(word.bbox[3] for word in group)
        lines.append(
            BackendTextLine(
                raw_text=text,
                bbox=(x0, y0, x1, y1),
                confidence=(sum(confidence_values) / len(confidence_values)
                            if confidence_values else None),
                language=_infer_language(text),
                script=_infer_script(text),
                text_type=TextType.PRINTED,
                polygon=group[0].polygon if len(group) == 1 else None,
                words=tuple(
                    BackendWord(
                        text=word.text,
                        bbox=word.bbox,
                        confidence=word.confidence,
                        reading_order=index,
                        polygon=word.polygon,
                    )
                    for index, word in enumerate(group)
                ),
            )
        )
    return lines


def _group_center(group: Sequence[BackendWord]) -> float:
    return sum((word.bbox[1] + word.bbox[3]) / 2 for word in group) / len(group)


def _group_height(group: Sequence[BackendWord]) -> float:
    return sum(word.bbox[3] - word.bbox[1] for word in group) / len(group)


def _geometry(
    value: Any,
) -> tuple[tuple[float, float, float, float], tuple[PolygonPoint, ...] | None] | None:
    values = _as_sequence(value)
    if values is None:
        return None
    try:
        if len(values) == 4 and all(_is_number(item) for item in values):
            x0, y0, x1, y1 = (float(item) for item in values)
            polygon = None
        else:
            points = [_point(item) for item in values]
            if len(points) < 3 or any(point is None for point in points):
                return None
            typed_points = tuple(point for point in points if point is not None)
            x0 = min(point.x for point in typed_points)
            y0 = min(point.y for point in typed_points)
            x1 = max(point.x for point in typed_points)
            y1 = max(point.y for point in typed_points)
            polygon = typed_points
        if not all(math.isfinite(item) for item in (x0, y0, x1, y1)):
            return None
        if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1, y1), polygon
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _looks_like_record(value: Any) -> bool:
    sequence = _as_sequence(value)
    if sequence is None or len(sequence) < 2 or _geometry(sequence[0]) is None:
        return False
    second = sequence[1]
    if isinstance(second, (str, bytes, bytearray, Mapping)):
        return True
    second_sequence = _as_sequence(second)
    return second_sequence is None or not second_sequence or _geometry(second_sequence[0]) is None


def _point(value: Any) -> PolygonPoint | None:
    sequence = _as_sequence(value)
    if sequence is None or len(sequence) < 2:
        return None
    try:
        x, y = float(sequence[0]), float(sequence[1])
        if not math.isfinite(x) or not math.isfinite(y) or x < 0 or y < 0:
            return None
        return PolygonPoint(x=x, y=y)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _confidence(value: Any) -> float | None:
    """Return a Paddle 0..1 score without percentage rescaling."""

    return _confidence_with_warning(value)[0]


def _confidence_with_warning(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None, "invalid_paddle_confidence"
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        return None, "paddle_confidence_out_of_range_not_rescaled"
    return parsed, None


def _canonical_paddle_language(language: str) -> str:
    normalized = language.strip().lower()
    provider = _PADDLE_LANGUAGE_ALIASES.get(normalized)
    if provider is None:
        raise ConfigurationError(
            f"PaddleOCR language '{language}' is unsupported by this adapter; "
            "configure a validated Paddle language model"
        )
    return provider


def _language_capability_note(requested: str, provider: str) -> str | None:
    if requested in {"fa", "fas"}:
        return (
            "requested Persian; using Paddle Arabic-script model; "
            "Persian accuracy is not claimed"
        )
    if provider == "ar":
        return "using Paddle Arabic-script model; language accuracy is deployment-dependent"
    return None


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _clean_optional(value: str | Path | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _as_sequence(value: Any) -> list[Any] | None:
    if value is None or isinstance(value, (str, bytes, bytearray, Mapping)):
        return None
    if isinstance(value, Sequence):
        return list(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        converted = tolist()
        if isinstance(converted, list):
            return converted
    return None


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _is_number(value: Any) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed)


def _paddle_cuda_available(paddle: Any) -> bool:
    for candidate in (
        getattr(paddle, "is_compiled_with_cuda", None),
        getattr(getattr(paddle, "device", None), "is_compiled_with_cuda", None),
    ):
        if callable(candidate):
            try:
                if bool(candidate()):
                    return True
            except Exception:
                continue
    cuda = getattr(getattr(paddle, "device", None), "cuda", None)
    device_count = getattr(cuda, "device_count", None)
    if callable(device_count):
        try:
            return int(device_count()) > 0
        except Exception:
            return False
    return False


def _looks_like_oom(error: RuntimeError) -> bool:
    message = str(error).lower()
    return "out of memory" in message or ("cuda error" in message and "memory" in message)


_PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _infer_language(text: str) -> str:
    has_rtl = bool(_PERSIAN_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_rtl and has_latin:
        return "fa+en"
    if has_rtl:
        return "fa"
    if has_latin:
        return "en"
    return "und"


def _infer_script(text: str) -> str:
    has_rtl = bool(_PERSIAN_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_rtl and has_latin:
        return "Arabic+Latin"
    if has_rtl:
        return "Arabic"
    if has_latin:
        return "Latin"
    return "Unknown"


__all__ = ["PaddleLanguage", "PaddleOcrBackend", "resolve_paddle_languages"]
