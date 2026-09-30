"""Optional PaddleOCR PP-Structure table adapter.

Only provider-produced table cells are emitted. If the runtime returns a table
without cell geometry, the result keeps an explicit warning and no invented
cells; the pipeline can preserve normal OCR text through its fallback path.
When row/column indexes are absent, the adapter derives zero-based addresses
only from valid provider cell boxes using deterministic row-center grouping and
left-to-right ordering.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterable, Mapping, Sequence
from importlib.util import find_spec
from typing import Any

from ocr_platform.domain import PolygonPoint
from ocr_platform.errors import BackendUnavailableError, ProcessingError
from ocr_platform.ocr.models import OcrRegion

from .ports import TableCell, TableResult
from .validation import validate_table_cells


class PaddleStructureTableBackend:
    name = "pp_structure"
    model = "paddleocr-ppstructure"
    confidence_scale = "paddle_0_1"
    backend_family = "paddleocr-structure"

    def __init__(
        self,
        *,
        language: str = "en",
        model_path: str | None = None,
        device: str = "auto",
        show_log: bool = False,
    ) -> None:
        self.language = language
        self.model_path = model_path
        self.device = device
        self.show_log = show_log
        self._engine: Any | None = None
        self._package_version = "unavailable"

    @property
    def model_version(self) -> str:
        return self._package_version

    @property
    def available(self) -> bool:
        return find_spec("paddleocr") is not None

    def extract(self, image_bytes: bytes, *, region: OcrRegion) -> TableResult:
        engine = self._load_engine()
        try:
            raw = _invoke_structure_engine(engine, image_bytes)
            cells, warnings = _parse_structure_result(raw)
            validation = validate_table_cells(cells, region_bbox=region.bbox)
            cells = list(validation.cells)
            warnings.extend(validation.warnings)
        except BackendUnavailableError:
            raise
        except Exception as exc:
            raise ProcessingError(
                "PaddleOCR PP-Structure failed to process the table", retryable=True
            ) from exc
        return TableResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            confidence_scale=self.confidence_scale,
            cells=tuple(cells),
            runtime_metadata=(("language", self.language), ("device", self.device)),
            warnings=tuple(warnings),
            review_flags=validation.review_flags,
            backend_family=self.backend_family,
        )

    def _load_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            module = importlib.import_module("paddleocr")
            constructor = getattr(module, "PPStructure", None) or getattr(
                module, "PPStructureV3", None
            )
            if constructor is None:
                raise AttributeError("PP-Structure constructor is unavailable")
            self._package_version = str(getattr(module, "__version__", "unknown"))
        except (ImportError, AttributeError) as exc:
            raise BackendUnavailableError(
                "PaddleOCR PP-Structure is not installed; install the optional 'paddle' extra"
            ) from exc
        try:
            parameters = inspect.signature(constructor).parameters
        except (TypeError, ValueError):
            parameters = {}
        kwargs: dict[str, Any] = {}
        for key, value in (("lang", self.language), ("show_log", self.show_log)):
            if key in parameters:
                kwargs[key] = value
        if "use_gpu" in parameters and self.device in {"cpu", "cuda"}:
            kwargs["use_gpu"] = self.device == "cuda"
        if self.model_path:
            for key in ("table_model_dir", "layout_model_dir", "det_model_dir"):
                if key in parameters:
                    kwargs[key] = self.model_path
        try:
            self._engine = constructor(**kwargs)
        except Exception as exc:
            raise BackendUnavailableError(
                "PaddleOCR PP-Structure model could not be loaded"
            ) from exc
        return self._engine


def _parse_structure_result(raw: Any) -> tuple[list[TableCell], list[str]]:
    records = _structure_records(raw)
    if records is None:
        return [], ["table backend returned no structured records"]
    table_records = [record for record in records if isinstance(record, Mapping)]
    cells: list[TableCell] = []
    warnings: list[str] = []
    for table_index, record in enumerate(table_records):
        if record.get("type") not in {None, "table"}:
            continue
        payload = record.get("res") if isinstance(record.get("res"), Mapping) else record
        boxes = payload.get("cell_bbox") or payload.get("cell_bboxes")
        recognition = payload.get("rec_res") or payload.get("cell_texts") or []
        if not isinstance(boxes, Sequence) or not boxes:
            warnings.append(f"table_{table_index}: cell geometry was not returned")
            continue
        for cell_index, box in enumerate(boxes):
            geometry = _geometry(box)
            if geometry is None:
                warnings.append(f"table_{table_index}: invalid cell geometry at index {cell_index}")
                continue
            parsed_box, polygon = geometry
            text, confidence = _recognition_at(recognition, cell_index)
            if text is None:
                warnings.append(f"table_{table_index}: cell text missing at index {cell_index}")
                continue
            row, column = _row_column(payload, cell_index, parsed_box, boxes)
            cells.append(
                TableCell(
                    row=row,
                    column=column,
                    text=text,
                    raw_text=text,
                    bbox=parsed_box,
                    confidence=confidence,
                    polygon=polygon,
                )
            )
    if not cells and not warnings:
        warnings.append("table backend returned no cell records")
    return cells, warnings


def _invoke_structure_engine(engine: Any, image_bytes: bytes) -> Any:
    """Invoke PP-Structure 2.x or 3.x without leaking provider details."""

    predictor = getattr(engine, "predict", None)
    if callable(predictor):
        try:
            parameters = inspect.signature(predictor).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "input" in parameters:
            return predictor(input=image_bytes)
        return predictor(image_bytes)
    if callable(engine):
        return engine(image_bytes)
    raise BackendUnavailableError(
        "installed PP-Structure runtime exposes no supported inference API"
    )


def _structure_records(raw: Any) -> list[Any] | None:
    if raw is None:
        return None
    if hasattr(raw, "to_dict") and callable(raw.to_dict):
        return _structure_records(raw.to_dict())
    if hasattr(raw, "json"):
        value = raw.json
        try:
            value = value() if callable(value) else value
        except Exception:
            return None
        if isinstance(value, (str, bytes, bytearray)):
            try:
                import json

                value = json.loads(value)
            except (TypeError, ValueError):
                return None
        return _structure_records(value)
    if isinstance(raw, Mapping):
        return [raw]
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return list(raw)
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, bytearray, Mapping)):
        return list(raw)
    return None


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    geometry = _geometry(value)
    return geometry[0] if geometry is not None else None


def _geometry(
    value: Any,
) -> tuple[tuple[float, float, float, float], tuple[PolygonPoint, ...] | None] | None:
    try:
        values = list(value)
        if len(values) == 4 and all(not _is_point(item) for item in values):
            x0, y0, x1, y1 = (float(item) for item in values)
            polygon = None
        else:
            points = [(float(item[0]), float(item[1])) for item in values]
            if len(points) < 3:
                return None
            x0 = min(point[0] for point in points)
            y0 = min(point[1] for point in points)
            x1 = max(point[0] for point in points)
            y1 = max(point[1] for point in points)
            polygon = tuple(PolygonPoint(x=point[0], y=point[1]) for point in points)
        if x1 <= x0 or y1 <= y0 or min(x0, y0) < 0:
            return None
        return (x0, y0, x1, y1), polygon
    except (TypeError, ValueError, IndexError):
        return None


def _is_point(value: Any) -> bool:
    if isinstance(value, (str, bytes, bytearray)):
        return False
    try:
        return len(value) >= 2
    except (TypeError, ValueError):
        return False


def _recognition_at(records: Any, index: int) -> tuple[str | None, float | None]:
    if not isinstance(records, Sequence) or index >= len(records):
        return None, None
    record = records[index]
    if isinstance(record, Mapping):
        text = record.get("text") or record.get("rec_text")
        confidence = record.get("confidence")
        if confidence is None:
            confidence = record.get("score")
    elif isinstance(record, Sequence) and not isinstance(record, (str, bytes)):
        text = record[0] if record else None
        confidence = record[1] if len(record) > 1 else None
    else:
        text, confidence = str(record), None
    if text is None:
        return None, None
    try:
        parsed_confidence = float(confidence) if confidence is not None else None
        if parsed_confidence is not None and parsed_confidence > 1:
            parsed_confidence /= 100
        if parsed_confidence is not None:
            parsed_confidence = max(0.0, min(1.0, parsed_confidence))
    except (TypeError, ValueError):
        parsed_confidence = None
    return str(text), parsed_confidence


def _row_column(
    payload: Mapping[str, Any],
    index: int,
    box: tuple[float, float, float, float],
    boxes: Any,
) -> tuple[int, int]:
    rows = payload.get("row_indices") or payload.get("rows")
    columns = payload.get("column_indices") or payload.get("columns")
    if (
        isinstance(rows, Sequence)
        and index < len(rows)
        and isinstance(columns, Sequence)
        and index < len(columns)
    ):
        try:
            return max(0, int(rows[index])), max(0, int(columns[index]))
        except (TypeError, ValueError):
            pass
    y_center = (box[1] + box[3]) / 2
    row_centers: list[float] = []
    tolerance = max(2.0, (box[3] - box[1]) * 0.6)
    parsed_boxes = [_bbox(candidate) for candidate in boxes]
    for candidate_box in parsed_boxes:
        if candidate_box is None:
            continue
        center = (candidate_box[1] + candidate_box[3]) / 2
        if not any(abs(center - existing) <= tolerance for existing in row_centers):
            row_centers.append(center)
    row_centers.sort()
    row = (
        min(range(len(row_centers)), key=lambda item: abs(row_centers[item] - y_center))
        if row_centers
        else 0
    )
    same_row = [
        (candidate_box, cell_index)
        for cell_index, candidate_box in enumerate(parsed_boxes)
        if candidate_box is not None
        and abs(((candidate_box[1] + candidate_box[3]) / 2) - y_center) <= tolerance
    ]
    same_row.sort(key=lambda item: item[0][0])
    column = next((position for position, item in enumerate(same_row) if item[1] == index), index)
    return row, column


PaddleTableBackend = PaddleStructureTableBackend

__all__ = ["PaddleStructureTableBackend", "PaddleTableBackend"]
