"""Optional PaddleOCR printed-text adapter.

The adapter keeps PaddleOCR imports and result objects at the provider
boundary.  It supports the 2.x ``ocr`` API and the compatible ``predict``
shape exposed by newer installations, but never supplies fallback text when
the runtime or model cannot be loaded.
"""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import Iterable, Mapping, Sequence
from importlib.util import find_spec
from typing import Any

from ocr_platform.domain import ExtractionMethod, PolygonPoint, TextType
from ocr_platform.errors import BackendUnavailableError, ProcessingError

from ..models import BackendTextLine, BackendWord, OcrRegion, OcrResult


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
        device: str = "auto",
        model_path: str | None = None,
        show_log: bool = False,
    ) -> None:
        if not language or any(not item for item in language.split("+")):
            raise ValueError("PaddleOCR language selection must not be empty")
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("PaddleOCR device must be auto, cpu, or cuda")
        self.language = _paddle_language(language)
        self.device = device
        self.model_path = model_path
        self.show_log = show_log
        self._engine: Any | None = None
        self._package_version = "unavailable"

    @property
    def model_version(self) -> str:
        return self._package_version

    @property
    def available(self) -> bool:
        return find_spec("paddleocr") is not None

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
        try:
            raw = self._invoke(engine, image_bytes)
            lines = tuple(_parse_result(raw))
        except BackendUnavailableError:
            raise
        except Exception as exc:
            raise ProcessingError("PaddleOCR failed to process the image", retryable=True) from exc
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
            runtime_metadata=(
                ("language", self.language),
                ("device", self.device),
                ("api", "ocr_or_predict"),
            ),
            backend_family=self.backend_family,
        )

    def _load_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            module = importlib.import_module("paddleocr")
            constructor = module.PaddleOCR
            self._package_version = str(getattr(module, "__version__", "unknown"))
        except (ImportError, AttributeError) as exc:
            raise BackendUnavailableError(
                "PaddleOCR is not installed; install the optional 'paddle' extra and model runtime"
            ) from exc
        kwargs = _constructor_kwargs(
            constructor,
            language=self.language,
            device=self.device,
            model_path=self.model_path,
            show_log=self.show_log,
        )
        try:
            self._engine = constructor(**kwargs)
        except Exception as exc:
            raise BackendUnavailableError("PaddleOCR model could not be loaded") from exc
        return self._engine

    @staticmethod
    def _invoke(engine: Any, image_bytes: bytes) -> Any:
        if callable(getattr(engine, "ocr", None)):
            return engine.ocr(image_bytes, cls=True)
        if callable(getattr(engine, "predict", None)):
            return engine.predict(image_bytes)
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
    if "device" in parameters and device in {"cpu", "cuda"}:
        kwargs["device"] = "gpu:0" if device == "cuda" else "cpu"
    if "use_angle_cls" in parameters:
        kwargs["use_angle_cls"] = True
    if device == "cuda" and "use_gpu" in parameters:
        kwargs["use_gpu"] = True
    elif device == "cpu" and "use_gpu" in parameters:
        kwargs["use_gpu"] = False
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
    return kwargs


def _parse_result(raw: Any) -> Iterable[BackendTextLine]:
    """Normalize PaddleOCR 2.x and simple 3.x prediction records."""

    records = _records(raw)
    words: list[BackendWord] = []
    for record in records:
        parsed = _parse_record(record)
        if parsed is not None:
            words.append(parsed)
    return _group_words_into_lines(words)


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
        texts = raw.get("rec_texts")
        scores = raw.get("rec_scores")
        boxes = raw.get("rec_boxes") or raw.get("rec_polys")
        if texts is not None and boxes is not None:
            return list(
                zip(
                    boxes,
                    zip(texts, scores or [None] * len(texts), strict=False),
                    strict=False,
                )
            )
        return []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        if len(raw) == 1 and isinstance(raw[0], Sequence) and not _looks_like_record(raw[0]):
            return list(raw[0])
        return list(raw)
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, bytearray, Mapping)):
        return _records(list(raw))
    return []


def _looks_like_record(value: Any) -> bool:
    return isinstance(value, Sequence) and len(value) >= 2 and _is_polygon(value[0])


def _parse_record(record: Any) -> BackendWord | None:
    if isinstance(record, Mapping):
        polygon = record.get("polygon") or record.get("points") or record.get("box")
        text = record.get("text") or record.get("rec_text")
        confidence = record.get("score")
        if confidence is None:
            confidence = record.get("confidence")
    elif isinstance(record, Sequence) and len(record) >= 2:
        polygon = record[0]
        text_score = record[1]
        if isinstance(text_score, Sequence) and not isinstance(text_score, (str, bytes)):
            text = text_score[0] if text_score else ""
            confidence = text_score[1] if len(text_score) > 1 else None
        else:
            text = text_score
            confidence = None
    else:
        return None
    text = "" if text is None else str(text)
    if not text.strip() or not _is_polygon(polygon):
        return None
    points = tuple(_point(item) for item in polygon)
    if any(point is None for point in points):
        return None
    typed_points = tuple(point for point in points if point is not None)
    x0 = min(point.x for point in typed_points)
    y0 = min(point.y for point in typed_points)
    x1 = max(point.x for point in typed_points)
    y1 = max(point.y for point in typed_points)
    normalized_confidence = _confidence(confidence)
    return BackendWord(
        text=text.strip(),
        bbox=(x0, y0, x1, y1),
        confidence=normalized_confidence,
        reading_order=0,
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
                polygon=None,
                words=tuple(
                    BackendWord(
                        text=word.text,
                        bbox=word.bbox,
                        confidence=word.confidence,
                        reading_order=index,
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


def _is_polygon(value: Any) -> bool:
    return isinstance(value, Sequence) and len(value) >= 2 and all(
        _is_point(item) for item in value
    )


def _is_point(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
        return False
    try:
        float(value[0])
        float(value[1])
    except (TypeError, ValueError):
        return False
    return True


def _point(value: Any) -> PolygonPoint | None:
    try:
        x, y = float(value[0]), float(value[1])
        if x < 0 or y < 0:
            return None
        return PolygonPoint(x=x, y=y)
    except (TypeError, ValueError, IndexError):
        return None


def _confidence(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return max(0.0, min(1.0, parsed / 100 if parsed > 1 else parsed))


def _paddle_language(language: str) -> str:
    mapping = {"fas": "fa", "eng": "en"}
    return "+".join(mapping.get(item.lower(), item.lower()) for item in language.split("+"))


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


__all__ = ["PaddleOcrBackend"]
