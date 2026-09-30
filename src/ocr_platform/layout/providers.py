"""Optional model-backed layout adapters.

The adapter is deliberately unavailable-safe: when PaddleOCR or its model
runtime is absent, it raises a typed backend error rather than returning fake
regions or silently selecting the Pillow fallback.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, ImageOps

from ocr_platform.errors import (
    BackendUnavailableError,
    ConfigurationError,
    OcrBackendFailure,
)

from .classification import map_provider_label
from .ports import LayoutRegion


class PaddleStructureLayoutBackend:
    name = "paddle-pp-structure"
    model = "pp-structure"
    model_version = "runtime"

    def __init__(self) -> None:
        self._engine: Any | None = None
        self.unavailable_reason = "paddleocr and its model runtime are not installed"
        try:
            import numpy as np
            from paddleocr import PPStructure

            self._numpy = np
            self._engine = PPStructure(show_log=False, layout=True)
            self.unavailable_reason = ""
        except ImportError:
            self._numpy = None
        except Exception as exc:
            self.unavailable_reason = f"paddle layout runtime could not initialize: {exc}"

    @property
    def available(self) -> bool:
        return self._engine is not None and self._numpy is not None

    def detect(
        self, image_bytes: bytes, *, page_width: float, page_height: float
    ) -> tuple[LayoutRegion, ...]:
        if not self.available:
            raise BackendUnavailableError(self.unavailable_reason)
        try:
            with Image.open(BytesIO(image_bytes)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                array = self._numpy.asarray(image)
            raw_results = self._engine(array)
        except Exception as exc:
            raise OcrBackendFailure("Paddle layout backend failed") from exc
        try:
            parsed = (self._parse_item(item) for item in raw_results)
            return tuple(item for item in parsed if item is not None)
        except (TypeError, ValueError, IndexError) as exc:
            raise OcrBackendFailure("Paddle layout backend returned malformed output") from exc

    @staticmethod
    def _parse_item(item: Any) -> LayoutRegion | None:
        if not isinstance(item, dict):
            return None
        bbox = item.get("bbox") or item.get("box")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        label = item.get("type") or item.get("label") or "unknown"
        confidence = item.get("score")
        classification = map_provider_label(label, confidence=confidence)
        polygon_value = item.get("polygon") or item.get("poly")
        polygon = None
        if isinstance(polygon_value, (list, tuple)):
            try:
                polygon = tuple((float(point[0]), float(point[1])) for point in polygon_value)
            except (TypeError, ValueError, IndexError):
                polygon = None
        return LayoutRegion(
            bbox=tuple(float(value) for value in bbox),
            block_type=classification.block_type,
            confidence=float(confidence) if confidence is not None else None,
            reading_order=0,
            polygon=polygon,
            provider_polygon=polygon,
            provider_label=str(label),
            route_hint=classification.route_hint,
            text_type=classification.text_type,
            needs_review=classification.needs_review,
            uncertainty_flags=classification.uncertainty_flags,
        )


def build_layout_backend(name: str, *, max_pixels: int = 4_000_000):
    normalized = name.strip().lower()
    if normalized in {"heuristic", "pillow", "projection"}:
        from .heuristic import HeuristicLayoutBackend, HeuristicLayoutConfig

        return HeuristicLayoutBackend(HeuristicLayoutConfig(max_pixels=max_pixels))
    if normalized in {"pp_structure", "paddleocr", "paddle-pp-structure"}:
        return PaddleStructureLayoutBackend()
    if normalized in {"unavailable", "none", "disabled"}:
        from .ports import UnavailableLayoutBackend

        return UnavailableLayoutBackend("layout backend is disabled")
    raise ConfigurationError(f"unknown layout backend: {name}")
