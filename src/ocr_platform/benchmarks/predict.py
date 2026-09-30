"""Run the real document pipeline and convert its result to benchmark records."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from ocr_platform.config import Settings
from ocr_platform.domain import Document
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.workers import ProcessingMode, ProcessingModePolicy

from .models import (
    BackendCandidate,
    BenchmarkCategory,
    GroundTruthDataset,
    PredictionDataset,
    PredictionDocument,
    PredictionLine,
    PredictionPage,
    PredictionTableCell,
    TinyTextStage,
    TinyTextStageCandidate,
)


def document_to_prediction(
    document: Document,
    *,
    category: BenchmarkCategory,
) -> PredictionDocument:
    pages: list[PredictionPage] = []
    for page in document.pages:
        lines: list[PredictionLine] = []
        cells: list[PredictionTableCell] = []
        for block in sorted(page.blocks, key=lambda item: item.reading_order):
            for line in sorted(block.lines, key=lambda item: item.reading_order):
                candidates = [
                    BackendCandidate(
                        backend=candidate.extraction.backend,
                        raw_text=candidate.raw_text,
                        normalized_text=candidate.normalized_text,
                        confidence=candidate.confidence,
                        model=candidate.extraction.model,
                        model_version=candidate.extraction.model_version,
                    )
                    for candidate in line.candidates
                ]
                lines.append(
                    PredictionLine(
                        id=line.id,
                        raw_text=line.raw_text,
                        normalized_text=line.normalized_text,
                        bbox=line.bbox,
                        polygon=line.polygon,
                        reading_order=line.reading_order,
                        verification_status=line.verification_status,
                        confidence=line.confidence,
                        backend=line.extraction.backend,
                        model=line.extraction.model,
                        model_version=line.extraction.model_version,
                        configuration_hash=(
                            line.extraction.configuration_hash
                            or document.configuration_hash
                        ),
                        preprocess_variant=line.extraction.preprocess_variant,
                        dpi=line.extraction.dpi,
                        region_scale=line.extraction.region_scale,
                        tiny_text=line.tiny_text,
                        sent_to_verification=len(line.verification_history) > 1
                        or len(line.candidates) > 1,
                        candidates=candidates,
                        tiny_text_stages=_tiny_text_stages(line),
                    )
                )
            for cell in sorted(block.table_cells, key=lambda item: (item.row, item.column)):
                cells.append(
                    PredictionTableCell(
                        id=cell.id,
                        row=cell.row,
                        column=cell.column,
                        raw_text=cell.raw_text,
                        normalized_text=cell.normalized_text,
                        bbox=cell.bbox,
                        polygon=cell.polygon,
                        verification_status=cell.verification_status,
                        confidence=cell.confidence,
                        backend=cell.extraction.backend,
                        candidates=[
                            BackendCandidate(
                                backend=candidate.extraction.backend,
                                raw_text=candidate.raw_text,
                                normalized_text=candidate.normalized_text,
                                confidence=candidate.confidence,
                                model=candidate.extraction.model,
                                model_version=candidate.extraction.model_version,
                            )
                            for candidate in cell.candidates
                        ],
                    )
                )
        page_text = "\n".join(line.raw_text for line in lines)
        pages.append(
            PredictionPage(
                page_number=page.page_number,
                page_text=page_text,
                lines=lines,
                table_cells=cells,
            )
        )
    return PredictionDocument(
        document_id=document.id,
        category=category,
        pages=pages,
    )


def build_prediction_dataset(
    ground_truth: GroundTruthDataset,
    *,
    settings: Settings,
    mode: ProcessingMode | str,
    source_root: Path | None = None,
) -> PredictionDataset:
    """Execute OCR against every ground-truth source and return real predictions.

    Synthetic URIs and missing source files are rejected. This prevents a
    benchmark command from accidentally comparing stored fixtures with
    themselves while claiming that a model was evaluated.
    """

    selected_mode = ProcessingMode(mode)
    effective_settings = ProcessingModePolicy.for_mode(settings, selected_mode).settings
    pipeline = DocumentPipeline(effective_settings)
    predictions: list[PredictionDocument] = []
    for reference in ground_truth.documents:
        source = _resolve_source(reference.source_uri, source_root)
        if not source.is_file():
            raise ValueError(f"benchmark source does not exist: {source}")
        document = pipeline.process_path(
            source,
            filename=source.name,
            document_id=reference.document_id,
        )
        predictions.append(
            document_to_prediction(document, category=reference.category)
        )
    return PredictionDataset(
        schema_version=ground_truth.schema_version,
        dataset_version=ground_truth.dataset_version,
        documents=predictions,
    )


def _resolve_source(source_uri: str, source_root: Path | None) -> Path:
    parsed = urlparse(source_uri)
    windows_path = len(source_uri) >= 2 and source_uri[1] == ":"
    if parsed.scheme and parsed.scheme != "file" and not windows_path:
        raise ValueError("real benchmark sources must be local paths or file:// URIs")
    raw = unquote(parsed.path if parsed.scheme == "file" else source_uri)
    if parsed.scheme == "file" and len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    if not raw or raw.startswith("synthetic:"):
        raise ValueError("synthetic benchmark sources cannot be executed")
    candidate = Path(raw)
    if source_root is not None and not candidate.is_absolute():
        root = source_root.resolve()
        candidate = (root / candidate).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("benchmark source escapes the sources root") from exc
    return candidate.resolve()


def _tiny_text_stages(line) -> list[TinyTextStageCandidate]:
    if not line.tiny_text:
        return []
    stages: list[TinyTextStageCandidate] = []
    for candidate in line.candidates:
        extraction = candidate.extraction
        if extraction.dpi is not None and extraction.dpi >= 600:
            stage = (
                TinyTextStage.CROP_UPSCALED
                if extraction.region_scale > 1
                else TinyTextStage.HIGH_DPI
            )
        else:
            stage = TinyTextStage.FIRST_PASS
        stages.append(
            TinyTextStageCandidate(
                stage=stage,
                raw_text=candidate.raw_text,
                normalized_text=candidate.normalized_text,
                confidence=candidate.confidence,
                backend=extraction.backend,
                model=extraction.model,
                model_version=extraction.model_version,
            )
        )
    stages.append(
        TinyTextStageCandidate(
            stage=TinyTextStage.VERIFIED_FINAL,
            raw_text=line.raw_text,
            normalized_text=line.normalized_text,
            confidence=line.confidence,
            backend=line.extraction.backend,
            model=line.extraction.model,
            model_version=line.extraction.model_version,
        )
    )
    return stages


__all__ = ["build_prediction_dataset", "document_to_prediction"]
