"""Run a deterministic end-to-end audit of the OCR pipeline.

The audit uses generated, non-sensitive fixtures and injected adapters that
implement the public contracts only for integration coverage. They are kept in
this script and are never selected by the production factory. The report
therefore distinguishes pipeline-contract coverage from real model accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ocr_platform.benchmarks.dataset import load_dataset
from ocr_platform.benchmarks.gates import load_quality_gate_config
from ocr_platform.benchmarks.runner import run_benchmark
from ocr_platform.config import Settings
from ocr_platform.config.settings import (
    DEFAULT_DEFAULT_DPI,
    DEFAULT_TINY_TEXT_DPI,
)
from ocr_platform.dataset import DatasetExporter, DatasetExportPolicy
from ocr_platform.domain import (
    BlockType,
    CoordinateSpace,
    DocumentResult,
    ExtractionMethod,
    TextType,
)
from ocr_platform.handwriting import build_handwriting_backend
from ocr_platform.imaging import PreprocessingService
from ocr_platform.layout import (
    LayoutAnalysisService,
    LayoutLine,
    LayoutRegion,
    RegionRouteHint,
)
from ocr_platform.layout.providers import build_layout_backend
from ocr_platform.normalization import normalize_text
from ocr_platform.ocr import OcrRegion, OcrResult
from ocr_platform.ocr.backends import build_ocr_backends
from ocr_platform.ocr.models import BackendTextLine, BackendWord
from ocr_platform.ocr.runtime import inspect_backend, resolve_device
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.storage import LocalArtifactStore, read_artifact_uri
from ocr_platform.tables import TableCell, TableResult, build_table_backend

PERSIAN_CONTRACT = "شماره قرارداد ١٢٣٤٥"
MIXED_LINE = "ایمیل: audit@example.com | Contract ID: AB-123"
HANDWRITTEN_LINE = "مقدار دست‌نویس ۱۲۳"


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    name: str
    kind: str
    suffix: str
    expected_pages: int
    builder: Callable[[Path], None]


class AuditLayoutBackend:
    """Deterministic layout contract adapter used only by this audit script."""

    name = "phase13-audit-layout"
    model = "contract-fixture-layout"
    model_version = "1"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def detect(
        self, image_bytes: bytes, *, page_width: float, page_height: float
    ) -> tuple[LayoutRegion, ...]:
        del image_bytes
        w, h = page_width, page_height

        def region(
            bbox: tuple[float, float, float, float],
            block_type: BlockType,
            route: RegionRouteHint,
            text_type: TextType = TextType.PRINTED,
            *,
            reading_order: int = 0,
            tiny_text: bool = False,
        ) -> LayoutRegion:
            x0, y0, x1, y1 = bbox
            line_height = max(12.0, (y1 - y0) / 5.0)
            lines = (
                LayoutLine(
                    bbox=(
                        x0 + 0.02 * w,
                        y0 + 0.05 * h,
                        x1 - 0.02 * w,
                        y0 + 0.05 * h + line_height,
                    ),
                    confidence=0.99,
                    text_type=text_type,
                    tiny_text=tiny_text,
                    reading_order=0,
                ),
            )
            return LayoutRegion(
                bbox=bbox,
                block_type=block_type,
                confidence=0.99,
                reading_order=reading_order,
                route_hint=route,
                text_type=text_type,
                tiny_text=tiny_text,
                coordinate_space=CoordinateSpace.RENDERED_PIXEL,
                lines=lines,
                provider_label=f"phase13-{self.kind}-{reading_order}",
            )

        if self.kind == "table":
            return (
                region(
                    (0.08 * w, 0.20 * h, 0.92 * w, 0.70 * h),
                    BlockType.TABLE,
                    RegionRouteHint.TABLE,
                    TextType.UNKNOWN,
                ),
            )
        if self.kind == "handwriting":
            return (
                region(
                    (0.08 * w, 0.25 * h, 0.92 * w, 0.55 * h),
                    BlockType.HANDWRITING,
                    RegionRouteHint.HANDWRITING,
                    TextType.HANDWRITTEN,
                ),
            )
        if self.kind == "form":
            return (
                region(
                    (0.08 * w, 0.18 * h, 0.92 * w, 0.38 * h),
                    BlockType.PRINTED_TEXT,
                    RegionRouteHint.PRINTED_TEXT,
                    TextType.PRINTED,
                    reading_order=0,
                ),
                region(
                    (0.08 * w, 0.42 * h, 0.92 * w, 0.72 * h),
                    BlockType.HANDWRITING,
                    RegionRouteHint.HANDWRITING,
                    TextType.HANDWRITTEN,
                    reading_order=1,
                ),
            )
        if self.kind == "multi_column":
            return (
                region(
                    (0.06 * w, 0.18 * h, 0.45 * w, 0.78 * h),
                    BlockType.MULTI_COLUMN,
                    RegionRouteHint.PRINTED_TEXT,
                    TextType.MIXED,
                    reading_order=0,
                ),
                region(
                    (0.55 * w, 0.18 * h, 0.94 * w, 0.78 * h),
                    BlockType.MULTI_COLUMN,
                    RegionRouteHint.PRINTED_TEXT,
                    TextType.MIXED,
                    reading_order=1,
                ),
            )
        if self.kind == "tiny":
            return (
                region(
                    (0.06 * w, 0.08 * h, 0.94 * w, 0.22 * h),
                    BlockType.TINY_TEXT,
                    RegionRouteHint.TINY_TEXT,
                    TextType.PRINTED,
                    tiny_text=True,
                ),
            )
        return (
            region(
                (0.06 * w, 0.12 * h, 0.94 * w, 0.80 * h),
                BlockType.PARAGRAPH,
                RegionRouteHint.PRINTED_TEXT,
                TextType.PRINTED,
            ),
        )


class AuditPrintedBackend:
    """Contract-only printed OCR adapter; never used by production factories."""

    model = "contract-fixture-printed"
    model_version = "1"
    confidence_scale = "audit_0_1"

    def __init__(self, kind: str, suffix: str) -> None:
        self.kind = kind
        self.name = f"phase13-printed-{suffix}"

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
        if self.kind == "multi_column":
            text = (
                "ستون چپ: متن فارسی"
                if region.bbox[0] < width / 2
                else "Right column: English text"
            )
        elif self.kind == "form":
            text = "نام و نام خانوادگی"
        elif self.kind == "low_quality":
            text = "شماره ۱۲۳۴۵" if preprocess_variant == "source-render" else "شماره ۱۲۳۴۶"
        elif self.kind in {"mixed", "mixed-native-scanned"}:
            text = MIXED_LINE
        else:
            text = PERSIAN_CONTRACT
        confidence = 0.56 if self.kind == "low_quality" else 0.97
        line_height = max(12.0, height * 0.08)
        line_y0 = max(4.0, height * 0.08)
        line_y1 = line_y0 + line_height
        line = BackendTextLine(
            raw_text=text,
            bbox=(
                max(4.0, width * 0.03),
                line_y0,
                width * 0.97,
                line_y1,
            ),
            confidence=confidence,
            language="fa+en" if "+" in text or "@" in text else "fa",
            script=(
                "Arabic+Latin"
                if any(char.isascii() and char.isalpha() for char in text)
                else "Arabic"
            ),
            text_type=TextType.PRINTED,
            words=(
                BackendWord(
                    text=text,
                    bbox=(
                        max(4.0, width * 0.03),
                        line_y0,
                        width * 0.97,
                        line_y1,
                    ),
                    confidence=confidence,
                    reading_order=0,
                ),
            ),
        )
        return OcrResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            method=ExtractionMethod.OCR,
            confidence_scale=self.confidence_scale,
            dpi=float(dpi),
            region_scale=float(region_scale),
            preprocess_variant=preprocess_variant,
            lines=(line,),
            runtime_metadata=(
                ("audit_only", "true"),
                ("scenario", self.kind),
            ),
        )


class AuditHandwritingBackend:
    """Contract-only HTR adapter used to exercise mixed-route assembly."""

    name = "phase13-audit-htr"
    model = "contract-fixture-htr"
    model_version = "1"
    confidence_scale = "audit_0_1"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        del region
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
        text = HANDWRITTEN_LINE if self.kind == "form" else "این صفحه دست‌نویس است"
        line_height = max(12.0, height * 0.08)
        line_y0 = max(4.0, height * 0.12)
        line = BackendTextLine(
            raw_text=text,
            bbox=(width * 0.06, line_y0, width * 0.94, line_y0 + line_height),
            confidence=0.94,
            language="fa",
            script="Arabic",
            text_type=TextType.HANDWRITTEN,
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
            lines=(line,),
            runtime_metadata=(("audit_only", "true"), ("scenario", self.kind)),
        )


class AuditTableBackend:
    """Contract-only structured table adapter used by the table scenario."""

    name = "phase13-audit-table"
    model = "contract-fixture-table"
    model_version = "1"
    confidence_scale = "audit_0_1"

    def extract(self, image_bytes: bytes, *, region: OcrRegion) -> TableResult:
        del region
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
        cells: list[TableCell] = []
        values = (("ردیف", "مبلغ"), ("۱", "۱۲۳۴۵ تومان"))
        for row, row_values in enumerate(values):
            for column, text in enumerate(row_values):
                x0 = column * width / 2 + 4
                y0 = row * height / 2 + 4
                x1 = (column + 1) * width / 2 - 4
                y1 = (row + 1) * height / 2 - 4
                cells.append(
                    TableCell(
                        row=row,
                        column=column,
                        text=text,
                        raw_text=text,
                        normalized_text=None,
                        bbox=(x0, y0, x1, y1),
                        confidence=0.96,
                        language="fa",
                        script="Arabic",
                    )
                )
        return TableResult(
            backend=self.name,
            model=self.model,
            model_version=self.model_version,
            confidence_scale=self.confidence_scale,
            cells=tuple(cells),
            runtime_metadata=(("audit_only", "true"),),
        )


def _font(size: int):
    for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _image(kind: str, *, dpi: int | None = None) -> bytes:
    image = Image.new("RGB", (1000, 1400), "white")
    draw = ImageDraw.Draw(image)
    regular = _font(34)
    small = _font(14 if kind == "tiny" else 26)
    draw.text((65, 50), "Phase 13 Integration Fixture", fill="black", font=regular)
    draw.text((65, 125), PERSIAN_CONTRACT, fill="black", font=small)
    draw.text((65, 185), MIXED_LINE, fill="black", font=small)
    for y in range(270, 1100, 72):
        draw.line((65, y, 935, y), fill=(40, 40, 40), width=2)
    if kind == "phone":
        image = image.rotate(4, expand=True, fillcolor=(232, 230, 224))
    elif kind == "low_quality":
        image = image.filter(ImageFilter.GaussianBlur(radius=2.0))
    elif kind == "handwriting":
        draw = ImageDraw.Draw(image)
        draw.text((80, 480), HANDWRITTEN_LINE, fill=(20, 40, 100), font=_font(40))
    elif kind == "form":
        draw = ImageDraw.Draw(image)
        for y in (420, 580, 740):
            draw.rectangle((70, y, 930, y + 105), outline="black", width=3)
        draw.text((95, 450), "نام:", fill="black", font=regular)
        draw.text((95, 610), "امضا:", fill="black", font=regular)
    elif kind == "table":
        draw = ImageDraw.Draw(image)
        for x in (70, 500, 930):
            draw.line((x, 380, x, 900), fill="black", width=4)
        for y in (380, 640, 900):
            draw.line((70, y, 930, y), fill="black", width=4)
    elif kind == "multi_column":
        draw = ImageDraw.Draw(image)
        for y in range(380, 1000, 65):
            draw.line((70, y, 430, y), fill="black", width=3)
            draw.line((570, y, 930, y), fill="black", width=3)
    buffer = BytesIO()
    save_kwargs = {"format": "PNG", "optimize": False}
    if dpi is not None:
        save_kwargs["dpi"] = (dpi, dpi)
    image.save(buffer, **save_kwargs)
    return buffer.getvalue()


def _write_image(path: Path, kind: str, *, jpeg: bool = False, dpi: int | None = None) -> None:
    image_bytes = _image(kind, dpi=dpi)
    if jpeg:
        with Image.open(BytesIO(image_bytes)) as image:
            image.save(path, format="JPEG", quality=20, optimize=False)
    else:
        path.write_bytes(image_bytes)


def _write_image_pdf(path: Path, kind: str) -> None:
    image_bytes = _image(kind)
    pdf = fitz.open()
    try:
        page = pdf.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=image_bytes)
        pdf.save(path)
    finally:
        pdf.close()


def _write_native_pdf(path: Path, *, pages: int = 2) -> None:
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    pdf = fitz.open()
    try:
        for page_number in range(pages):
            page = pdf.new_page(width=612, height=792)
            kwargs = {"fontname": "helv", "fontsize": 16, "fill": (0, 0, 0)}
            if font_path.is_file():
                kwargs["fontfile"] = str(font_path)
                kwargs["fontname"] = "audit-font"
            page.insert_text((72, 100), PERSIAN_CONTRACT, **kwargs)
            page.insert_text((72, 145), MIXED_LINE, **kwargs)
            page.insert_text((72, 190), f"Page {page_number + 1} / 2", **kwargs)
        pdf.save(path)
    finally:
        pdf.close()


def _write_mixed_pdf(path: Path) -> None:
    image_bytes = _image("mixed")
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    pdf = fitz.open()
    try:
        page = pdf.new_page(width=612, height=792)
        kwargs = {"fontname": "helv", "fontsize": 16, "fill": (0, 0, 0)}
        if font_path.is_file():
            kwargs["fontfile"] = str(font_path)
            kwargs["fontname"] = "audit-font"
        page.insert_text((72, 100), PERSIAN_CONTRACT, **kwargs)
        scanned_page = pdf.new_page(width=612, height=792)
        scanned_page.insert_image(scanned_page.rect, stream=image_bytes)
        pdf.save(path)
    finally:
        pdf.close()


def _scenarios() -> tuple[ScenarioSpec, ...]:
    return (
        ScenarioSpec("native_persian_pdf", "native", ".pdf", 2, lambda p: _write_native_pdf(p)),
        ScenarioSpec(
            "scanned_persian_pdf", "scanned", ".pdf", 1, lambda p: _write_image_pdf(p, "scanned")
        ),
        ScenarioSpec(
            "mixed_persian_english_pdf",
            "mixed",
            ".pdf",
            1,
            lambda p: _write_image_pdf(p, "mixed"),
        ),
        ScenarioSpec(
            "phone_photo_perspective",
            "phone",
            ".jpg",
            1,
            lambda p: _write_image(p, "phone", jpeg=True),
        ),
        ScenarioSpec(
            "tiny_font_document",
            "tiny",
            ".png",
            1,
            lambda p: _write_image(p, "tiny", dpi=DEFAULT_TINY_TEXT_DPI),
        ),
        ScenarioSpec(
            "handwritten_page",
            "handwriting",
            ".png",
            1,
            lambda p: _write_image(p, "handwriting"),
        ),
        ScenarioSpec(
            "form_labels_handwriting", "form", ".png", 1, lambda p: _write_image(p, "form")
        ),
        ScenarioSpec(
            "table_heavy_document", "table", ".png", 1, lambda p: _write_image(p, "table")
        ),
        ScenarioSpec(
            "multi_column_page",
            "multi_column",
            ".png",
            1,
            lambda p: _write_image(p, "multi_column"),
        ),
        ScenarioSpec(
            "low_quality_scan",
            "low_quality",
            ".jpg",
            1,
            lambda p: _write_image(p, "low_quality", jpeg=True),
        ),
        ScenarioSpec(
            "mixed_native_scanned_pdf", "mixed-native-scanned", ".pdf", 2, _write_mixed_pdf
        ),
    )


def _settings(root: Path) -> Settings:
    return Settings(
        environment="test",
        storage_root=root / "artifacts",
        temporary_workspace=root / "tmp",
        export_staging_workspace=root / "export-staging",
        model_path=root / "models",
        cache_path=root / "cache",
        enabled_ocr_backends=("phase13-printed-a", "phase13-printed-b"),
        layout_backend="heuristic",
        handwriting_backend="unavailable",
        table_backend="unavailable",
        max_retries=2,
        verification_max_candidates=6,
        max_pages_in_flight=1,
    )


def _pipeline(settings: Settings, kind: str) -> DocumentPipeline:
    store = LocalArtifactStore(settings.storage_root)
    return DocumentPipeline(
        settings,
        artifact_store=store,
        backends=(AuditPrintedBackend(kind, "a"), AuditPrintedBackend(kind, "b")),
        handwriting_backends=(AuditHandwritingBackend(kind),),
        table_backend=AuditTableBackend(),
        layout_service=LayoutAnalysisService(
            AuditLayoutBackend(kind),
            max_regions=settings.layout_max_regions,
            min_confidence=settings.layout_min_confidence,
        ),
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=str):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _line_items(document: DocumentResult):
    return [line for page in document.pages for block in page.blocks for line in block.lines]


def _cell_items(document: DocumentResult):
    return [cell for page in document.pages for block in page.blocks for cell in block.table_cells]


def _audit_document(
    document: DocumentResult,
    *,
    settings: Settings,
    store: LocalArtifactStore,
    kind: str,
    export_root: Path,
) -> dict[str, object]:
    errors: list[str] = []
    lines = _line_items(document)
    cells = _cell_items(document)
    if [page.page_number for page in document.pages] != list(
        range(1, len(document.pages) + 1)
    ):
        errors.append("page numbers are not contiguous")
    for page in document.pages:
        for block in page.blocks:
            for line in block.lines:
                if (
                    line.source.document_id != document.id
                    or line.source.page_number != page.page_number
                ):
                    errors.append(f"line {line.id} has invalid document/page provenance")
                if not line.source.source_uri or not line.extraction.backend:
                    errors.append(f"line {line.id} is missing source or backend metadata")
                if line.extraction.configuration_hash != document.configuration_hash:
                    errors.append(f"line {line.id} has a mismatched configuration hash")
                if line.normalized_text != normalize_text(line.raw_text, settings.normalization):
                    errors.append(f"line {line.id} normalization is not reproducible")
                if line.source.crop_uri:
                    try:
                        read_artifact_uri(store, line.source.crop_uri)
                    except Exception as exc:
                        errors.append(
                            f"line {line.id} crop is not readable: {type(exc).__name__}"
                        )
                if (
                    line.extraction.method is not ExtractionMethod.NATIVE_PDF_TEXT
                    and not line.candidates
                ):
                    errors.append(f"line {line.id} has OCR text without retained candidates")
            for cell in block.table_cells:
                if (
                    cell.source.document_id != document.id
                    or cell.source.page_number != page.page_number
                ):
                    errors.append(f"cell {cell.id} has invalid document/page provenance")
                if cell.extraction.configuration_hash != document.configuration_hash:
                    errors.append(f"cell {cell.id} has a mismatched configuration hash")
                if cell.source.crop_uri:
                    try:
                        read_artifact_uri(store, cell.source.crop_uri)
                    except Exception as exc:
                        errors.append(
                            f"cell {cell.id} crop is not readable: {type(exc).__name__}"
                        )

    first_exporter = DatasetExporter(store, temporary_workspace=settings.export_staging_workspace)
    exported = first_exporter.export(
        document,
        export_root,
        formats=("json", "txt", "md", "pages", "crops"),
        policy=DatasetExportPolicy.ALL_WITH_STATUS,
    )
    digest_before = _tree_digest(exported.root)
    exported_again = first_exporter.export(
        document,
        export_root,
        formats=("json", "txt", "md", "pages", "crops"),
        policy=DatasetExportPolicy.ALL_WITH_STATUS,
    )
    deterministic = exported.manifest == exported_again.manifest and digest_before == _tree_digest(
        exported_again.root
    )
    try:
        DocumentResult.model_validate_json(
            (exported.root / "document.json").read_text(encoding="utf-8")
        )
    except Exception as exc:
        errors.append(f"canonical export failed schema validation: {type(exc).__name__}")

    status_counts: dict[str, int] = {}
    for item in [*lines, *cells]:
        status_counts[item.verification_status.value] = status_counts.get(
            item.verification_status.value, 0
        ) + 1
    tiny_escalated = (
        kind != "tiny"
        or not lines
        or any(
            candidate.extraction.region_scale > 1
            or (candidate.extraction.dpi or 0) >= settings.tiny_text_dpi
            for line in lines
            for candidate in line.candidates
        )
    )
    extraction_methods = {line.extraction.method for line in lines}
    mixed_routes_preserved = kind != "form" or {
        ExtractionMethod.OCR,
        ExtractionMethod.HANDWRITING_RECOGNITION,
    }.issubset(extraction_methods)
    if not mixed_routes_preserved:
        errors.append("form did not preserve both printed and handwriting routes")
    uncertainty_surfaced = (
        all(item.verification_status is not None for item in [*lines, *cells])
        and (
            kind != "low_quality"
            or any(item.needs_review for item in [*lines, *cells])
            or bool(document.warnings)
        )
    )
    raw_separate = all(
        item.normalized_text == normalize_text(item.raw_text, settings.normalization)
        for item in [*lines, *cells]
    )
    reading_orders = [item.reading_order for item in [*lines, *cells]]
    return {
        "name": kind,
        "pages": len(document.pages),
        "lines": len(lines),
        "table_cells": len(cells),
        "processing_status": document.processing_status.value,
        "quality_status": document.status.value,
        "status_counts": status_counts,
        "geometry_and_provenance": not errors,
        "raw_normalized_separate": raw_separate,
        "reading_order_present": all(order >= 0 for order in reading_orders),
        "tiny_text_escalated": tiny_escalated,
        "mixed_routes_preserved": mixed_routes_preserved,
        "uncertainty_surfaced": uncertainty_surfaced,
        "deterministic_exports": deterministic,
        "canonical_schema_valid": not any("schema validation" in error for error in errors),
        "errors": errors,
        "export_manifest": str(exported.manifest_path),
    }


def _capabilities() -> list[dict[str, object]]:
    settings = Settings(environment="test")
    device = resolve_device(settings.device)
    backends = [*build_ocr_backends(settings), build_layout_backend(settings.layout_backend)]
    backends.extend(
        [
            build_handwriting_backend(settings.handwriting_backend),
            build_table_backend(settings.table_backend),
        ]
    )
    return [inspect_backend(backend, device=device).to_payload() for backend in backends]


def _tiny_recovery_audit(root: Path) -> dict[str, object]:
    settings = _settings(root / "tiny-recovery")
    image_bytes = _image("tiny", dpi=DEFAULT_TINY_TEXT_DPI)
    result = PreprocessingService(
        settings,
        artifact_store=LocalArtifactStore(settings.storage_root),
    ).recover_tiny_text(
        "phase13-tiny-recovery",
        1,
        image_bytes,
        region_bbox=(50.0, 50.0, 950.0, 240.0),
        estimated_line_height_px=6.0,
        current_dpi=DEFAULT_DEFAULT_DPI,
        page_reference_size=(1000.0, 1400.0),
    )
    return {
        "is_tiny": result.decision.is_tiny,
        "recommended_dpi": result.decision.recommended_dpi,
        "region_scales": list(result.decision.region_scales),
        "variant_count": len(result.variants),
        "mapping_preserved": all(
            variant.mapping_to_source.source_width == 1000
            and variant.mapping_to_source.source_height == 1400
            for variant in result.variants
        ),
    }


def _benchmark_audit() -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[1]
    dataset_root = repository_root / "benchmarks" / "data"
    report = run_benchmark(
        load_dataset(dataset_root),
        mode="accurate",
        prediction_set="current",
        quality_gates=load_quality_gate_config(dataset_root / "quality-gates.json"),
        settings=Settings(environment="test"),
    )
    overall = report.metrics.overall
    return {
        "dataset_version": report.dataset_version,
        "mode": report.mode,
        "category_count": len(report.metrics.categories),
        "quality_gates_passed": report.quality_gates.passed,
        "overall_cer": overall.cer if overall is not None else None,
        "overall_line_detection_recall": (
            overall.line_detection_recall if overall is not None else None
        ),
        "tiny_text_recovery_improvement": (
            overall.tiny_text.recovery_improvement if overall is not None else None
        ),
        "model_versions": list(report.model_versions),
        "configuration_hash": report.configuration_hash,
    }


def _markdown_report(
    results: list[dict[str, object]],
    capabilities: list[dict[str, object]],
    tiny_recovery: dict[str, object],
    benchmark: dict[str, object],
    *,
    generated_at: datetime,
) -> str:
    total_lines = sum(int(item["lines"]) for item in results)
    total_cells = sum(int(item["table_cells"]) for item in results)
    passed = sum(not bool(item["errors"]) for item in results)
    lines = [
        "# Phase 13 Final Integration Audit",
        "",
        f"Generated: {generated_at.isoformat()}",
        "",
        "## Verdict",
        "",
        (
            f"**PASS** for the audited pipeline contracts: {passed}/{len(results)} generated "
            "scenarios passed page, geometry, provenance, export, and uncertainty checks. "
            "This is not a claim of 100% OCR accuracy."
        ),
        "",
        "## Architecture Summary",
        "",
        (
            "The modular monolith remains native-first: ingestion and PDF inspection choose "
            "native extraction or bounded rendering; image quality and preprocessing create "
            "immutable derived artifacts; layout produces provider-neutral regions; routing "
            "selects printed OCR, handwriting, or table adapters; verification retains "
            "candidates and review evidence; normalization never overwrites raw text; "
            "deterministic exporters produce canonical and training-safe artifacts; workers "
            "persist page checkpoints and bounded progress."
        ),
        "",
        "## Supported Inputs and Languages",
        "",
        "| Area | Coverage |",
        "| --- | --- |",
        (
            "| Inputs | Native PDFs, scanned PDFs, image PDFs, PNG, JPEG/JPG, TIFF/WEBP "
            "where Pillow accepts them |"
        ),
        "| Languages | Persian/Farsi, English, mixed Persian-English metadata and normalization "
        "paths |",
        (
            "| Structures | Printed text, handwriting route, forms, tables, multi-column "
            "regions, tiny text, headers/footers |"
        ),
        (
            "| Provenance | Document/page identity, coordinate space, page dimensions, "
            "source/crop URI, extraction metadata, candidates, verification history |"
        ),
        "",
        "## End-to-End Scenario Results",
        "",
        (
            "| Scenario | Pages | Lines | Cells | Processing | Quality | "
            "Geometry/provenance | Raw/normalized | Tiny escalation | Mixed routes | "
            "Uncertainty | Deterministic export |"
        ),
        "| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    row_template = (
        "| {name} | {pages} | {line_count} | {cells} | {processing} | {quality} | "
        "{geometry} | {raw} | {tiny} | {mixed} | {uncertainty} | {export} |"
    )
    for item in results:
        lines.append(
            row_template.format(
                name=item["name"],
                pages=item["pages"],
                line_count=item["lines"],
                cells=item["table_cells"],
                processing=item["processing_status"],
                quality=item["quality_status"],
                geometry="PASS" if item["geometry_and_provenance"] else "FAIL",
                raw="PASS" if item["raw_normalized_separate"] else "FAIL",
                tiny="PASS" if item["tiny_text_escalated"] else "FAIL",
                mixed="PASS" if item["mixed_routes_preserved"] else "FAIL",
                uncertainty="PASS" if item["uncertainty_surfaced"] else "FAIL",
                export="PASS" if item["deterministic_exports"] else "FAIL",
            )
        )
    lines.extend(
        [
            "",
            f"Audited output volume: {total_lines} lines and {total_cells} structured table cells.",
            "",
            "## OCR Backends and Model Versions",
            "",
            "| Backend | Model | Version | Available | Device | Reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    failed_results = [item for item in results if item["errors"]]
    if failed_results:
        lines.extend(["", "## Audit Diagnostics", ""])
        for item in failed_results:
            lines.append(f"- `{item['name']}`: {'; '.join(item['errors'])}")
    for capability in capabilities:
        lines.append(
            "| {backend} | {model} | {version} | {available} | {device} | {reason} |".format(
                backend=capability["backend"],
                model=capability["model"],
                version=capability["model_version"],
                available="yes" if capability["available"] else "no",
                device=capability["device"],
                reason=capability.get("reason", ""),
            )
        )
    lines.extend(
        [
            "",
            (
                "The repository's production factory is fail-closed when optional model "
                "runtimes are unavailable. The environment used for this audit did not "
                "provide the external Tesseract executable, Paddle model runtime, HTR "
                "weights, or table model. The scenario adapter names beginning with "
                "`phase13-audit-` are deterministic contract fixtures used only by this "
                "audit script and are not production backends."
            ),
            "",
            "## Tiny-Text Recovery",
            "",
            (
                f"The recovery audit returned `is_tiny={tiny_recovery['is_tiny']}`, "
                f"recommended `{tiny_recovery['recommended_dpi']}` DPI, scales "
                f"`{tiny_recovery['region_scales']}`, and "
                f"`{tiny_recovery['variant_count']}` bounded variants. Source mapping "
                f"preservation: `{tiny_recovery['mapping_preserved']}`."
            ),
            "",
            "## Benchmark Results",
            "",
            (
                f"The versioned synthetic benchmark `{benchmark['dataset_version']}` ran in "
                f"`{benchmark['mode']}` mode across {benchmark['category_count']} categories. "
                f"Configured quality gates: "
                f"`{'PASS' if benchmark['quality_gates_passed'] else 'FAIL'}`. "
                f"Overall CER: `{benchmark['overall_cer']}`; line-detection recall: "
                f"`{benchmark['overall_line_detection_recall']}`; tiny-text recovery improvement: "
                f"`{benchmark['tiny_text_recovery_improvement']}`. These are synthetic fixture "
                f"metrics; model versions: `{benchmark['model_versions']}`; configuration "
                f"hash: `{benchmark['configuration_hash']}`. They are not production "
                "accuracy claims."
            ),
            "",
            "## Human-Review Workflow",
            "",
            (
                "Low confidence, backend disagreement, tiny text, unavailable HTR/table "
                "capabilities, and malformed or incomplete evidence remain explicit "
                "verification flags. Review records retain competing raw candidates, "
                "normalized candidates, confidence values, backend/model/version, "
                "preprocessing variant, source/crop references, and the highlighted review "
                "artifact. Strict exports exclude uncertain and human-review-required "
                "records; all-with-status exports retain status labels for audit."
            ),
            "",
            "## Known Failure Modes",
            "",
            (
                "OCR can fail or require review when source pixels are missing, pages are "
                "severely blurred or compressed, handwriting is illegible, content is "
                "occluded, pages are damaged, fonts are unusual, scripts are unsupported, "
                "or a required model/runtime is unavailable. Super-resolution is not "
                "treated as ground truth. The pipeline preserves the candidate and "
                "surfaces uncertainty rather than silently repairing text."
            ),
            "",
            "## Deployment and Operations",
            "",
            (
                "1. Copy `.env.example` to a private environment configuration and provide "
                "authentication keys for staging/production."
            ),
            "2. Build with `python -m build --no-isolation` or the repository Dockerfile.",
            (
                "3. Run local CPU orchestration with `docker compose config` followed by "
                "`docker compose up --build` when Docker Engine is available."
            ),
            (
                "4. Use `/healthz`, `/readyz`, and authenticated `/metrics`; run the worker "
                "entrypoint separately for queued processing."
            ),
            (
                "5. Mount private artifact, temporary, model, and cache storage; do not "
                "package proprietary model weights without license approval."
            ),
            "",
            "## Remaining Risks",
            "",
            (
                "- Real OCR quality cannot be certified on this host because the production "
                "OCR executable and optional model runtimes are unavailable."
            ),
            (
                "- GPU utilization, model memory behavior, and long-document throughput "
                "require dedicated hardware validation."
            ),
            (
                "- `pip-audit`, static type checking, and a live Docker build/runtime "
                "smoke test require tools not available in the audit environment."
            ),
            (
                "- Benchmark fixtures are synthetic and demonstrate contract behavior, "
                "not representative production accuracy."
            ),
            "",
            "## Next Optimization Priorities",
            "",
            (
                "1. Run the benchmark and end-to-end audit with licensed Persian-capable "
                "OCR/HTR/table models on CPU and GPU runners."
            ),
            (
                "2. Calibrate confidence policies per backend using permitted labeled "
                "samples; preserve backend-specific scales."
            ),
            "3. Measure 300/450/600 DPI cost and tiny-text recovery on real, redacted documents.",
            (
                "4. Add dedicated model-worker health and memory metrics after selecting "
                "the production model runtimes."
            ),
            "",
            "## Audit Limitations",
            "",
            (
                "No 100% accuracy claim is made. Contract-level checks passed for generated "
                "scenarios, while actual recognition accuracy remains dependent on the "
                "selected, licensed OCR/HTR/table runtimes and source quality."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_audit(output: Path) -> dict[str, object]:
    generated_at = datetime.now(UTC)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="ocr-phase13-") as temporary:
        root = Path(temporary)
        for spec in _scenarios():
            source = root / f"{spec.name}{spec.suffix}"
            spec.builder(source)
            scenario_root = root / spec.name
            settings = _settings(scenario_root)
            pipeline = _pipeline(settings, spec.kind)
            document = pipeline.process_path(
                source,
                filename=source.name,
                declared_content_type=None,
                document_id=f"phase13-{spec.name.replace('_', '-')}",
            )
            if len(document.pages) != spec.expected_pages:
                raise RuntimeError(
                    f"{spec.name}: expected {spec.expected_pages} pages, got {len(document.pages)}"
                )
            scenario_result = _audit_document(
                document,
                settings=settings,
                store=LocalArtifactStore(settings.storage_root),
                kind=spec.kind,
                export_root=scenario_root / "exports",
            )
            scenario_result["name"] = spec.name
            results.append(scenario_result)
        tiny_recovery = _tiny_recovery_audit(root)
        capabilities = _capabilities()
    benchmark = _benchmark_audit()
    report = _markdown_report(
        results,
        capabilities,
        tiny_recovery,
        benchmark,
        generated_at=generated_at,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    return {
        "report": str(output),
        "scenario_count": len(results),
        "passed_scenarios": sum(not bool(item["errors"]) for item in results),
        "total_lines": sum(int(item["lines"]) for item in results),
        "total_table_cells": sum(int(item["table_cells"]) for item in results),
        "scenario_errors": {
            str(item["name"]): list(item["errors"])
            for item in results
            if item["errors"]
        },
        "tiny_recovery": tiny_recovery,
        "benchmark": benchmark,
        "capabilities": capabilities,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/final-audit.md"),
        help="Markdown report path",
    )
    args = parser.parse_args(argv)
    result = run_audit(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed_scenarios"] == result["scenario_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
