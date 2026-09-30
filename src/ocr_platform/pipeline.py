"""Application orchestration for native-first document processing."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from ocr_platform.config import Settings
from ocr_platform.domain import (
    Block,
    BlockType,
    BoundingBox,
    CoordinateSpace,
    Document,
    DocumentSource,
    ExtractionMetadata,
    ExtractionMethod,
    Line,
    OCRCandidate,
    Page,
    PageType,
    ProcessingStatus,
    ProcessingWarning,
    Provenance,
    QualityAssessment,
    ReviewFlag,
    TableCellResult,
    TextType,
    VerificationStatus,
    WarningSeverity,
    Word,
)
from ocr_platform.errors import (
    ArtifactStorageError,
    BackendUnavailableError,
    InvalidDocumentError,
    OcrPlatformError,
    ProcessingError,
)
from ocr_platform.handwriting import HandwritingBackend, build_handwriting_backend
from ocr_platform.imaging import map_bbox_to_page, map_polygon_to_page, prepare_image
from ocr_platform.ingestion import DocumentReaderService, PageInput, RenderedPage
from ocr_platform.layout import (
    LayoutAnalysisService,
    LayoutRegion,
    LayoutResult,
    build_layout_backend,
)
from ocr_platform.normalization import normalize_text
from ocr_platform.observability.metrics import MetricsRegistry
from ocr_platform.observability.tracing import trace_span
from ocr_platform.ocr import (
    OcrBackend,
    OcrRegion,
    VerificationEngine,
    VerificationPolicy,
)
from ocr_platform.ocr.backends import build_ocr_backends
from ocr_platform.ocr.models import BackendTextLine, OcrResult
from ocr_platform.ocr.routing import PageRouter, RegionRoute, RegionRouter, sort_reading_order
from ocr_platform.ocr.runtime import InferenceGate
from ocr_platform.ocr.verification.engine import AttemptCandidate, make_candidate
from ocr_platform.quality.metrics import disagreement_rate, mean_confidence
from ocr_platform.storage import (
    ArtifactLayout,
    ArtifactStore,
    StoredArtifact,
    build_artifact_store,
    sha256_bytes,
    sha256_file,
)
from ocr_platform.tables import (
    TableBackend,
    TableResult,
    build_table_backend,
    validate_table_cells,
)
from ocr_platform.utils import stable_hash

_PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


class DocumentPipeline:
    """Coordinates ingestion, OCR, verification, and canonical output.

    The pipeline is deliberately synchronous and side-effect limited: source
    and derived bytes go through the configured artifact store, while OCR
    backends are injected ports.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        artifact_store: ArtifactStore | None = None,
        reader_service: DocumentReaderService | None = None,
        backends: Sequence[OcrBackend] | None = None,
        router: PageRouter | None = None,
        layout_service: LayoutAnalysisService | None = None,
        verifier: VerificationEngine | None = None,
        handwriting_backends: Sequence[HandwritingBackend] | None = None,
        table_backend: TableBackend | None = None,
        region_router: RegionRouter | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.metrics = metrics or MetricsRegistry()
        self.inference_gate = InferenceGate(settings.gpu_inference_concurrency)
        self.store = artifact_store or build_artifact_store(settings)
        self.layout = ArtifactLayout()
        self.readers = reader_service or DocumentReaderService(settings)
        self.backends = tuple(backends) if backends is not None else build_ocr_backends(settings)
        self.handwriting_backends = (
            tuple(handwriting_backends)
            if handwriting_backends is not None
            else (
                build_handwriting_backend(
                    settings.handwriting_backend,
                    model_path=str(settings.handwriting_model_path),
                    device=settings.device,
                ),
            )
        )
        self.table_backend = table_backend or build_table_backend(
            settings.table_backend,
            language="+".join(settings.ocr_languages),
            device=settings.device,
            model_path=str(settings.model_path),
        )
        self.region_router = region_router or RegionRouter()
        self.router = router or PageRouter()
        self.layout_service = layout_service or LayoutAnalysisService(
            build_layout_backend(
                settings.layout_backend,
                max_pixels=settings.layout_max_pixels,
            ),
            max_regions=settings.layout_max_regions,
            min_confidence=settings.layout_min_confidence,
        )
        self.verifier = verifier or VerificationEngine(
            VerificationPolicy(
                confidence_threshold=settings.confidence_threshold,
                verified_threshold=settings.verification_threshold,
                max_attempts=settings.verification_max_candidates,
                min_consensus_candidates=settings.verification_min_consensus_candidates,
                require_consensus_for_verified=settings.verification_require_consensus_for_verified,
                allow_consensus_override_low_confidence=(
                    settings.verification_allow_consensus_override_low_confidence
                ),
                require_independent_backend_consensus=(
                    settings.verification_require_independent_backend_consensus
                ),
                min_independent_backend_families=(
                    settings.verification_min_independent_backend_families
                ),
                min_text_length=settings.verification_min_text_length,
                max_suspicious_char_rate=settings.verification_max_suspicious_char_rate,
                min_image_quality=settings.verification_min_image_quality,
                backend_confidence_thresholds=settings.backend_confidence_thresholds,
            )
        )

    def process_path(
        self,
        path: Path,
        *,
        filename: str,
        declared_content_type: str | None = None,
        document_id: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> Document:
        if not path.is_file():
            raise InvalidDocumentError("source file does not exist")
        try:
            source_size = path.stat().st_size
        except OSError as exc:
            raise InvalidDocumentError("source file could not be inspected") from exc
        if source_size > self.settings.max_upload_bytes:
            raise InvalidDocumentError("source exceeds configured size limit")
        source_checksum = sha256_file(path)
        resolved_document_id = document_id or f"doc-{source_checksum[:16]}"
        processing_checksum = stable_hash(
            {
                "source_checksum": source_checksum,
                "pipeline_version": self.settings.pipeline_version,
                "schema_version": self.settings.schema_version,
                "configuration_hash": self.settings.configuration_hash,
                "backends": [
                    f"{backend.name}:{backend.model}:{backend.model_version}"
                    for backend in self.backends
                ],
                "handwriting_backends": [
                    f"{backend.name}:{backend.model}:{backend.model_version}"
                    for backend in self.handwriting_backends
                ],
                "table_backend": (
                    f"{self.table_backend.name}:{self.table_backend.model}:"
                    f"{self.table_backend.model_version}"
                ),
            }
        )
        source_artifact = self._store_source(resolved_document_id, path, source_checksum)
        source_uri = source_artifact.uri
        source = self._build_source(
            path,
            filename=filename,
            declared_content_type=declared_content_type,
            source_uri=source_uri,
        )
        started = datetime.now(UTC)
        with trace_span("ingestion", metrics=self.metrics), trace_span(
            "pdf_extraction" if source.content_type == "application/pdf" else "image_decode",
            metrics=self.metrics,
        ):
            page_inputs = self.readers.read(
                source_artifact.path,
                document_id=resolved_document_id,
                content_type=source.content_type,
                source_uri=source_uri,
            )
        if not page_inputs:
            raise InvalidDocumentError("document contains no pages")
        if len(page_inputs) > self.settings.max_pages:
            raise InvalidDocumentError("source exceeds configured page limit")
        if progress_callback is not None:
            progress_callback(0, len(page_inputs), "page_processing")
        pages: list[Page] = []
        warnings: list[str] = []
        for page_index, page_input in enumerate(page_inputs, start=1):
            try:
                page, page_warnings = self._process_page(
                    resolved_document_id,
                    source_artifact.path,
                    page_input,
                    source=source,
                )
            except OcrPlatformError as exc:
                page = self._failed_page(page_input, ReviewFlag.BACKEND_FAILURE)
                page_warnings = [
                    f"page {page_input.page_number} processing failed: {exc.details.code}"
                ]
            except Exception:
                page = self._failed_page(page_input, ReviewFlag.BACKEND_FAILURE)
                page_warnings = [
                    f"page {page_input.page_number} processing failed: unexpected_error"
                ]
            pages.append(page)
            warnings.extend(page_warnings)
            if progress_callback is not None:
                progress_callback(page_index, len(page_inputs), "page_processing")
        finished = datetime.now(UTC)
        if progress_callback is not None:
            progress_callback(len(page_inputs), len(page_inputs), "verification")
        with trace_span("quality", metrics=self.metrics):
            quality = self._quality(pages, warnings)
        return Document(
            id=resolved_document_id,
            schema_version=self.settings.schema_version,
            pipeline_version=self.settings.pipeline_version,
            source=source,
            configuration_hash=self.settings.configuration_hash,
            processing_checksum=processing_checksum,
            normalization_policy=self.settings.normalization.to_payload(),
            processing_started_at=started,
            processing_finished_at=finished,
            pages=pages,
            status=quality.status,
            quality=quality,
            processing_status=(
                ProcessingStatus.COMPLETED_WITH_WARNINGS
                if warnings or quality.status == VerificationStatus.HUMAN_REVIEW_REQUIRED
                else ProcessingStatus.COMPLETED
            ),
            processing_warnings=[
                ProcessingWarning(
                    code="pipeline_warning",
                    severity=WarningSeverity.WARNING,
                    phase="processing",
                    message=warning,
                    document_id=resolved_document_id,
                )
                for warning in warnings
            ],
            warnings=warnings,
        )

    @staticmethod
    def _failed_page(page_input: PageInput, flag: ReviewFlag) -> Page:
        render_artifact = page_input.render_artifact
        return Page(
            page_number=page_input.page_number,
            id=page_input.page_id,
            width=page_input.width,
            height=page_input.height,
            coordinate_space=page_input.coordinate_space,
            page_type=page_input.page_type,
            source_uri=page_input.source_uri,
            rendered_uri=render_artifact.uri if render_artifact else None,
            source_dpi=page_input.source_dpi,
            rendered_width=render_artifact.width if render_artifact else None,
            rendered_height=render_artifact.height if render_artifact else None,
            native_text_reliable=page_input.native_text_reliable,
            native_text_reason=page_input.native_text_reason,
            page_flags=[flag],
        )

    def _store_source(self, document_id: str, path: Path, checksum: str) -> StoredArtifact:
        artifact_name = self.layout.source_name
        if self.store.exists(document_id, artifact_name):
            existing = self.store.get(document_id, artifact_name)
            if existing.checksum_sha256 != checksum:
                raise InvalidDocumentError("document id already references a different source")
            return existing
        try:
            return self.store.put_bytes(document_id, artifact_name, path.read_bytes())
        except ArtifactStorageError:
            if self.store.exists(document_id, artifact_name):
                existing = self.store.get(document_id, artifact_name)
                if existing.checksum_sha256 == checksum:
                    return existing
            raise

    @staticmethod
    def _build_source(
        path: Path,
        *,
        filename: str,
        declared_content_type: str | None,
        source_uri: str,
    ) -> DocumentSource:
        from ocr_platform.ingestion.source import build_document_source

        return build_document_source(
            path,
            filename=filename,
            declared_content_type=declared_content_type,
            source_uri=source_uri,
        )

    def _process_page(
        self,
        document_id: str,
        source_path: Path,
        page_input: PageInput,
        *,
        source: DocumentSource,
    ) -> tuple[Page, list[str]]:
        if page_input.native_text_reliable:
            with trace_span("layout", metrics=self.metrics):
                native_layout = self.layout_service.analyze_native(
                    page_input.native_lines,
                    page_width=page_input.width,
                    page_height=page_input.height,
                    coordinate_space=page_input.coordinate_space,
                )
        else:
            native_layout = None
        router_decision = self.router.route(page_input, tiny_text_hint=page_input.tiny_text)
        if not router_decision.requires_ocr:
            return self._native_page(document_id, page_input, native_layout), self._layout_warnings(
                native_layout
            )
        ocr_page, warnings = self._ocr_page(
            document_id, source_path, page_input, router_decision.regions, source=source
        )
        if page_input.native_text_reliable:
            return (
                self._merge_mixed_page(
                    document_id, page_input, ocr_page, native_layout=native_layout
                ),
                warnings,
            )
        return ocr_page, warnings

    def _merge_mixed_page(
        self,
        document_id: str,
        page_input: PageInput,
        ocr_page: Page,
        *,
        native_layout: LayoutResult | None = None,
    ) -> Page:
        native_page = self._native_page(document_id, page_input, native_layout)
        offset = len(native_page.blocks)
        merged_blocks = list(native_page.blocks)
        merged_blocks.extend(
            block.model_copy(update={"reading_order": offset + index})
            for index, block in enumerate(ocr_page.blocks)
        )
        return native_page.model_copy(
            update={
                "page_type": PageType.MIXED,
                "rendered_uri": ocr_page.rendered_uri,
                "rendered_width": ocr_page.rendered_width,
                "rendered_height": ocr_page.rendered_height,
                "blocks": merged_blocks,
                "page_flags": list(dict.fromkeys(native_page.page_flags + ocr_page.page_flags)),
                "native_text_reason": (f"{page_input.native_text_reason};ocr_image_regions"),
            }
        )

    def _native_page(
        self,
        document_id: str,
        page_input: PageInput,
        layout_result: LayoutResult | None = None,
    ) -> Page:
        extraction = ExtractionMetadata(
            method=ExtractionMethod.NATIVE_PDF_TEXT,
            backend="pymupdf-native",
            model="embedded-text",
            model_version="fitz",
            preprocess_variant="none",
            confidence_scale="not_applicable",
            configuration_hash=self.settings.configuration_hash,
        )
        grouped: dict[int, list] = defaultdict(list)
        for native_line in page_input.native_lines:
            grouped[native_line.block_index].append(native_line)
        blocks: list[Block] = []
        for block_order, native_lines in enumerate(grouped.values()):
            lines = [
                self._line_from_native(document_id, page_input, native_line, extraction, line_order)
                for line_order, native_line in enumerate(
                    sorted(native_lines, key=lambda item: (item.bbox[1], item.bbox[0]))
                )
            ]
            bbox = _union_bbox(line.bbox for line in lines)
            layout_region = _best_layout_region(
                bbox,
                layout_result.regions if layout_result is not None else (),
            )
            block = Block(
                id=f"page-{page_input.page_number}-block-{block_order}",
                block_type=(layout_region.block_type if layout_region else BlockType.PRINTED_TEXT),
                bbox=bbox,
                reading_order=(layout_region.reading_order if layout_region else block_order),
                confidence=(layout_region.confidence if layout_region else None),
                source=Provenance(
                    document_id=document_id,
                    page_number=page_input.page_number,
                    source_uri=page_input.source_uri,
                    coordinate_space=page_input.coordinate_space,
                ),
                lines=lines,
            )
            blocks.append(block)
        return Page(
            page_number=page_input.page_number,
            id=page_input.page_id,
            width=page_input.width,
            height=page_input.height,
            coordinate_space=page_input.coordinate_space,
            page_type=PageType.NATIVE_TEXT,
            source_uri=page_input.source_uri,
            source_dpi=page_input.source_dpi,
            blocks=blocks,
            native_text_reliable=True,
            native_text_reason=page_input.native_text_reason,
        )

    def _line_from_native(
        self, document_id: str, page_input: PageInput, native_line, extraction, line_order: int
    ) -> Line:
        raw_text = native_line.text
        return Line(
            id=f"page-{page_input.page_number}-line-{native_line.block_index}-{line_order}",
            raw_text=raw_text,
            normalized_text=normalize_text(raw_text, self.settings.normalization),
            bbox=BoundingBox(
                x0=native_line.bbox[0],
                y0=native_line.bbox[1],
                x1=native_line.bbox[2],
                y1=native_line.bbox[3],
            ),
            confidence=None,
            language=_infer_language(raw_text),
            script=_infer_script(raw_text),
            text_type=TextType.PRINTED,
            reading_order=line_order,
            source=Provenance(
                document_id=document_id,
                page_number=page_input.page_number,
                source_uri=page_input.source_uri,
                coordinate_space=page_input.coordinate_space,
            ),
            extraction=extraction,
            verification_status=VerificationStatus.VERIFIED,
        )

    def _ocr_page(
        self,
        document_id: str,
        source_path: Path,
        page_input: PageInput,
        regions: Iterable[OcrRegion],
        *,
        source: DocumentSource,
    ) -> tuple[Page, list[str]]:
        warnings: list[str] = []
        region_values = tuple(regions)
        render_dpi = (
            self.settings.tiny_text_dpi
            if any(region.tiny_text for region in region_values)
            else self.settings.default_dpi
        )
        rendered_page = self._render_page(source_path, source.content_type, page_input, render_dpi)
        image_bytes = rendered_page.image_bytes
        if self.layout_service is not None and not page_input.native_text_reliable:
            try:
                with trace_span("layout", metrics=self.metrics):
                    layout_result = self.layout_service.analyze(
                        image_bytes,
                        page_width=rendered_page.width,
                        page_height=rendered_page.height,
                        coordinate_space=CoordinateSpace.RENDERED_PIXEL,
                    )
                warnings.extend(self._layout_warnings(layout_result))
                if layout_result.regions:
                    region_values = self.router.route(
                        page_input,
                        layout_regions=layout_result.regions,
                    ).regions
            except BackendUnavailableError as exc:
                warnings.append(f"layout backend unavailable: {exc.details.message}")
            except InvalidDocumentError as exc:
                warnings.append(f"layout analysis failed: {exc.details.message}")
        rendered_regions = tuple(
            self._to_rendered_region(region, page_input, rendered_page) for region in region_values
        )
        render_artifact = self.store.put_bytes(
            document_id,
            f"page-{page_input.page_number:04d}-render-{render_dpi}.png",
            image_bytes,
            overwrite=True,
        )
        high_quality_page: RenderedPage | None = None
        blocks: list[Block] = []
        for region in rendered_regions:
            route = self.region_router.route(region)
            if route.requires_table:
                table_result, region_warnings, table_failure_flags = self._extract_table_region(
                    image_bytes,
                    rendered_page,
                    region,
                )
                warnings.extend(region_warnings)
                if table_result is None:
                    warnings.append(
                        f"{region.region_id}: table structure unavailable; preserving text OCR"
                    )
                    fallback_results, fallback_warnings = self._recognize_region(
                        image_bytes,
                        rendered_page,
                        region,
                        backends=self.backends,
                    )
                    warnings.extend(fallback_warnings)
                    if fallback_results:
                        fallback_block, fallback_block_warnings = self._block_from_results(
                            document_id,
                            page_input,
                            region,
                            fallback_results,
                            render_artifact.uri,
                            image_bytes=image_bytes,
                            rendered_page=rendered_page,
                            force_review=True,
                            extra_flags=tuple(
                                dict.fromkeys(
                                    (
                                        *table_failure_flags,
                                        ReviewFlag.TABLE_STRUCTURE_UNCERTAIN,
                                    )
                                )
                            ),
                        )
                        blocks.append(fallback_block)
                        warnings.extend(fallback_block_warnings)
                    else:
                        blocks.append(
                            self._empty_block(
                                document_id,
                                page_input,
                                region,
                                render_artifact.uri,
                                flags=tuple(
                                    dict.fromkeys(
                                        (
                                            *table_failure_flags,
                                            ReviewFlag.TABLE_STRUCTURE_UNCERTAIN,
                                        )
                                    )
                                ),
                            )
                        )
                    continue
                block, block_warnings = self._block_from_table_result(
                    document_id,
                    page_input,
                    region,
                    table_result,
                    render_artifact.uri,
                )
                blocks.append(block)
                warnings.extend(block_warnings)
                continue

            route_backends = self._backends_for_routes(route.routes)
            results, region_warnings = self._recognize_region(
                image_bytes,
                rendered_page,
                region,
                backends=route_backends,
            )
            if (
                source.content_type == "application/pdf"
                and self.settings.verification_enable_high_quality_retry
                and rendered_page.dpi < self.settings.high_quality_dpi
                and (not results or not self._result_is_confident(results[-1]))
                and len(results) < self.settings.verification_max_candidates
            ):
                try:
                    if high_quality_page is None:
                        high_quality_page = self._render_page(
                            source_path,
                            source.content_type,
                            page_input,
                            self.settings.high_quality_dpi,
                        )
                        self.store.put_bytes(
                            document_id,
                            f"page-{page_input.page_number:04d}-render-{int(high_quality_page.dpi)}.png",
                            high_quality_page.image_bytes,
                            overwrite=True,
                        )
                    high_region = self._scale_rendered_region(
                        region, rendered_page, high_quality_page
                    )
                    high_results, high_warnings = self._recognize_region(
                        high_quality_page.image_bytes,
                        high_quality_page,
                        high_region,
                        backends=route_backends,
                        max_results=self.settings.verification_max_candidates - len(results),
                        variant_override=("source-render",),
                    )
                    results.extend(
                        self._map_result_between_pages(
                            result,
                            source_page=high_quality_page,
                            target_page=rendered_page,
                        )
                        for result in high_results
                    )
                    region_warnings.extend(high_warnings)
                except (InvalidDocumentError, ProcessingError, ArtifactStorageError) as exc:
                    region_warnings.append(f"high-quality retry failed: {exc}")
            warnings.extend(region_warnings)
            if not results:
                warnings.append(f"{region.region_id}: no OCR backend produced a result")
                flags = [ReviewFlag.MISSING_BACKEND]
                if route.requires_handwriting:
                    flags.append(ReviewFlag.CAPABILITY_UNAVAILABLE)
                blocks.append(
                    self._empty_block(
                        document_id,
                        page_input,
                        region,
                        render_artifact.uri,
                        flags=tuple(flags),
                    )
                )
                continue
            htr_succeeded = any(
                result.method == ExtractionMethod.HANDWRITING_RECOGNITION for result in results
            )
            block, block_warnings = self._block_from_results(
                document_id,
                page_input,
                region,
                results,
                render_artifact.uri,
                image_bytes=image_bytes,
                rendered_page=rendered_page,
                force_review=bool(region_warnings)
                or (route.requires_handwriting and not htr_succeeded),
                extra_flags=(
                    tuple(
                        flag
                        for flag in (
                            ReviewFlag.BACKEND_FAILURE if region_warnings else None,
                            (
                                ReviewFlag.CAPABILITY_UNAVAILABLE
                                if route.requires_handwriting and not htr_succeeded
                                else None
                            ),
                        )
                        if flag is not None
                    )
                ),
            )
            blocks.append(block)
            warnings.extend(block_warnings)
        page_type = PageType.SCANNED if source.content_type == "application/pdf" else PageType.IMAGE
        page_flags = (
            [ReviewFlag.MISSING_BACKEND]
            if all(block.needs_review and not block.lines for block in blocks)
            else []
        )
        return (
            Page(
                page_number=page_input.page_number,
                id=page_input.page_id,
                width=page_input.width,
                height=page_input.height,
                coordinate_space=page_input.coordinate_space,
                page_type=page_type,
                source_uri=page_input.source_uri,
                rendered_uri=render_artifact.uri,
                source_dpi=page_input.source_dpi,
                rendered_width=rendered_page.width,
                rendered_height=rendered_page.height,
                blocks=blocks,
                native_text_reliable=False,
                native_text_reason=page_input.native_text_reason,
                page_flags=page_flags,
            ),
            warnings,
        )

    @staticmethod
    def _to_rendered_region(
        region: OcrRegion,
        page_input: PageInput,
        rendered_page: RenderedPage,
    ) -> OcrRegion:
        if region.coordinate_space == CoordinateSpace.RENDERED_PIXEL:
            x_scale = y_scale = 1.0
        else:
            if page_input.width <= 0 or page_input.height <= 0:
                raise InvalidDocumentError("page dimensions must be positive")
            x_scale = rendered_page.width / page_input.width
            y_scale = rendered_page.height / page_input.height
        x0, y0, x1, y1 = region.bbox
        bbox = (
            max(0.0, min(float(rendered_page.width), x0 * x_scale)),
            max(0.0, min(float(rendered_page.height), y0 * y_scale)),
            max(0.0, min(float(rendered_page.width), x1 * x_scale)),
            max(0.0, min(float(rendered_page.height), y1 * y_scale)),
        )
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise InvalidDocumentError(f"{region.region_id} has no visible pixels")
        return replace(
            region,
            bbox=bbox,
            coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        )

    @staticmethod
    def _scale_rendered_region(
        region: OcrRegion,
        source_page: RenderedPage,
        target_page: RenderedPage,
    ) -> OcrRegion:
        if source_page.width <= 0 or source_page.height <= 0:
            raise InvalidDocumentError("source rendered page dimensions must be positive")
        x_scale = target_page.width / source_page.width
        y_scale = target_page.height / source_page.height
        x0, y0, x1, y1 = region.bbox
        return replace(
            region,
            bbox=(x0 * x_scale, y0 * y_scale, x1 * x_scale, y1 * y_scale),
            coordinate_space=CoordinateSpace.RENDERED_PIXEL,
        )

    @staticmethod
    def _map_result_between_pages(
        result: OcrResult,
        *,
        source_page: RenderedPage,
        target_page: RenderedPage,
    ) -> OcrResult:
        if source_page.width <= 0 or source_page.height <= 0:
            raise InvalidDocumentError("source rendered page dimensions must be positive")
        x_scale = target_page.width / source_page.width
        y_scale = target_page.height / source_page.height

        def scale_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
            return (box[0] * x_scale, box[1] * y_scale, box[2] * x_scale, box[3] * y_scale)

        mapped_lines = tuple(
            replace(
                line,
                bbox=scale_box(line.bbox),
                polygon=(
                    tuple(
                        replace(point, x=point.x * x_scale, y=point.y * y_scale)
                        for point in line.polygon
                    )
                    if line.polygon
                    else None
                ),
                words=tuple(replace(word, bbox=scale_box(word.bbox)) for word in line.words),
            )
            for line in result.lines
        )
        return replace(result, lines=mapped_lines)

    def _backends_for_routes(
        self, routes: Sequence[RegionRoute]
    ) -> tuple[OcrBackend | HandwritingBackend, ...]:
        selected: list[OcrBackend | HandwritingBackend] = []
        for route in routes:
            if route is RegionRoute.PRINTED:
                selected.extend(self.backends)
            elif route is RegionRoute.HANDWRITING:
                selected.extend(self.handwriting_backends)
        return tuple(selected)

    def _extract_table_region(
        self,
        image_bytes: bytes,
        rendered_page: RenderedPage,
        region: OcrRegion,
    ) -> tuple[TableResult | None, list[str], tuple[ReviewFlag, ...]]:
        warnings: list[str] = []
        table_variant = self._table_preprocess_variant(region)
        try:
            with trace_span("preprocessing", metrics=self.metrics):
                prepared = prepare_image(
                    image_bytes,
                    region_bbox=region.bbox,
                    page_width=rendered_page.width,
                    page_height=rendered_page.height,
                    variant=table_variant,
                    max_crop_pixels=self.settings.max_crop_pixels,
                    max_region_scale=self.settings.max_region_scale,
                )
            backend_region = replace(
                region,
                bbox=(0.0, 0.0, float(prepared.width), float(prepared.height)),
            )
            with self.inference_gate.slot(), trace_span("table", metrics=self.metrics):
                raw_result = self.table_backend.extract(
                    prepared.image_bytes,
                    region=backend_region,
                )
            result = (
                raw_result
                if isinstance(raw_result, TableResult)
                else TableResult(
                    backend=self.table_backend.name,
                    model=self.table_backend.model,
                    model_version=self.table_backend.model_version,
                    confidence_scale=getattr(
                        self.table_backend, "confidence_scale", "backend_specific"
                    ),
                    backend_family=getattr(self.table_backend, "backend_family", "unknown"),
                    cells=tuple(raw_result),
                )
            )
            validation = validate_table_cells(
                result.cells,
                region_bbox=backend_region.bbox,
            )
            result = replace(
                result,
                cells=validation.cells,
                warnings=tuple((*result.warnings, *validation.warnings)),
                review_flags=tuple(
                    dict.fromkeys((*result.review_flags, *validation.review_flags))
                ),
            )
            warnings.extend(f"{result.backend}: {warning}" for warning in result.warnings)
            if not validation.usable:
                warnings.append(f"{result.backend}: table structure unusable; fallback required")
                flags = tuple(
                    dict.fromkeys(
                        (*validation.review_flags, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
                    )
                )
                return None, warnings, flags
            mapped_cells = tuple(
                replace(
                    cell,
                    bbox=map_bbox_to_page(cell.bbox, prepared),
                    polygon=map_polygon_to_page(cell.polygon, prepared),
                )
                for cell in result.cells
            )
            result = replace(
                result,
                cells=mapped_cells,
                dpi=float(rendered_page.dpi),
                region_scale=float(prepared.scale),
                preprocess_variant=table_variant,
            )
            return result, warnings, ()
        except BackendUnavailableError as exc:
            warnings.append(f"{self.table_backend.name}: {exc.details.message}")
            return (
                None,
                warnings,
                (
                    ReviewFlag.MISSING_BACKEND,
                    ReviewFlag.CAPABILITY_UNAVAILABLE,
                    ReviewFlag.TABLE_STRUCTURE_UNCERTAIN,
                ),
            )
        except OcrPlatformError as exc:
            warnings.append(f"{self.table_backend.name}: {exc.details.message}")
            return (
                None,
                warnings,
                (ReviewFlag.BACKEND_FAILURE, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN),
            )
        except Exception as exc:
            warnings.append(
                f"{self.table_backend.name}: table extraction failed ({type(exc).__name__})"
            )
            return (
                None,
                warnings,
                (ReviewFlag.BACKEND_FAILURE, ReviewFlag.TABLE_STRUCTURE_UNCERTAIN),
            )

    def _table_preprocess_variant(self, region: OcrRegion) -> str:
        """Choose one bounded crop scale for tiny table regions.

        Table structure extraction receives the same local crop mapping as
        printed OCR.  Only tiny regions use an upscale, and the first
        configured candidate keeps the table route deterministic and bounded.
        """
        if not region.tiny_text:
            return "source-render"
        scale = next(
            (
                candidate
                for candidate in self.settings.region_scale_candidates
                if candidate > 1 and candidate <= self.settings.max_region_scale
            ),
            None,
        )
        return f"region-scale-{scale}" if scale is not None else "source-render"

    def _recognize_region(
        self,
        image_bytes: bytes,
        rendered_page: RenderedPage,
        region: OcrRegion,
        *,
        backends: Sequence[OcrBackend | HandwritingBackend] | None = None,
        max_results: int | None = None,
        variant_override: Sequence[str] | None = None,
    ) -> tuple[list[OcrResult], list[str]]:
        results: list[OcrResult] = []
        warnings: list[str] = []
        budget = self.settings.verification_max_candidates if max_results is None else max_results
        if budget <= 0:
            return results, warnings
        variants = (
            tuple(variant_override)
            if variant_override is not None
            else self._variants_for(region)
        )
        selected_backends = self.backends if backends is None else backends
        for backend in selected_backends:
            for variant in variants:
                if len(results) >= budget:
                    return results, warnings
                try:
                    profile_name = self._profile_for_variant(region, variant)
                    with trace_span("preprocessing", metrics=self.metrics):
                        prepared = prepare_image(
                            image_bytes,
                            region_bbox=region.bbox,
                            page_width=rendered_page.width,
                            page_height=rendered_page.height,
                            variant=variant,
                            max_crop_pixels=self.settings.max_crop_pixels,
                            max_region_scale=self.settings.max_region_scale,
                            profile_name=profile_name,
                            enabled_profiles=self.settings.preprocessing_profiles,
                        )
                    backend_region = replace(
                        region,
                        bbox=(0.0, 0.0, float(prepared.width), float(prepared.height)),
                    )
                    with self.inference_gate.slot(), trace_span("ocr", metrics=self.metrics):
                        result = backend.recognize(
                            prepared.image_bytes,
                            region=backend_region,
                            dpi=rendered_page.dpi,
                            region_scale=prepared.scale,
                            preprocess_variant=variant,
                        )
                    result = self._map_result_to_page(result, prepared)
                    result = replace(
                        result,
                        dpi=float(rendered_page.dpi),
                        region_scale=float(prepared.scale),
                        preprocess_variant=variant,
                        runtime_metadata=tuple(
                            (*result.runtime_metadata,)
                            if profile_name is None
                            else (*result.runtime_metadata, ("preprocessing_profile", profile_name))
                        ),
                    )
                    results.append(result)
                    warnings.extend(f"{result.backend}: {warning}" for warning in result.warnings)
                    if self._result_is_confident(result) and not region.tiny_text:
                        break
                except BackendUnavailableError as exc:
                    warnings.append(f"{backend.name}: {exc.details.message}")
                    break
                except (InvalidDocumentError, ProcessingError) as exc:
                    warnings.append(f"{backend.name} {variant}: {exc.details.message}")
        return results, warnings

    def _variants_for(self, region: OcrRegion) -> tuple[str, ...]:
        if self.settings.max_retries <= 0:
            return ("source-render",)
        if region.tiny_text:
            retry_variants = tuple(
                f"region-scale-{scale}"
                for scale in self.settings.region_scale_candidates
                if scale <= self.settings.max_region_scale
            ) + ("grayscale", "contrast")
        else:
            retry_variants = ("grayscale", "contrast")
        return ("source-render",) + retry_variants[: self.settings.max_retries]

    def _profile_for_variant(self, region: OcrRegion, variant: str) -> str | None:
        if variant == "source-render":
            return self.settings.default_preprocessing_profile
        if region.tiny_text and variant.startswith("region-scale-"):
            return "tiny_text"
        return None

    def _map_result_to_page(self, result: OcrResult, prepared) -> OcrResult:
        mapped_lines = []
        for line in result.lines:
            mapped_words = tuple(
                replace(word, bbox=map_bbox_to_page(word.bbox, prepared)) for word in line.words
            )
            mapped_lines.append(
                replace(
                    line,
                    bbox=map_bbox_to_page(line.bbox, prepared),
                    polygon=map_polygon_to_page(line.polygon, prepared),
                    words=mapped_words,
                )
            )
        return replace(result, lines=tuple(mapped_lines))

    def _result_is_confident(self, result: OcrResult) -> bool:
        threshold = dict(self.settings.backend_confidence_thresholds).get(
            result.backend, self.settings.confidence_threshold
        )
        return bool(result.lines) and all(
            line.confidence is not None and line.confidence >= threshold
            for line in result.lines
        )

    def _render_page(
        self, source_path: Path, content_type: str, page_input: PageInput, dpi: int
    ) -> RenderedPage:
        if content_type == "application/pdf":
            with trace_span("pdf_rendering", metrics=self.metrics):
                return self.readers.pdf_reader.render_page(
                    source_path,
                    page_number=page_input.page_number,
                    dpi=dpi,
                )
        with trace_span(
            "image_rendering" if content_type.startswith("image/") else "office_rendering",
            metrics=self.metrics,
        ):
            return self.readers.render_page(
                source_path,
                content_type=content_type,
                page_number=page_input.page_number,
                dpi=dpi,
                source_uri=page_input.source_uri,
            )

    def _extraction_from_ocr_result(self, result: OcrResult) -> ExtractionMetadata:
        return ExtractionMetadata(
            method=result.method,
            backend=result.backend,
            model=result.model,
            model_version=result.model_version,
            dpi=result.dpi,
            region_scale=result.region_scale,
            preprocess_variant=result.preprocess_variant,
            confidence_scale=result.confidence_scale,
            backend_family=result.backend_family,
            configuration_hash=self.settings.configuration_hash,
            runtime_metadata=dict(result.runtime_metadata),
            warnings=list(result.warnings),
        )

    def _store_line_crop(
        self,
        document_id: str,
        page_number: int,
        line_id: str,
        image_bytes: bytes,
        rendered_page: RenderedPage,
        bbox: tuple[float, float, float, float],
    ) -> tuple[str | None, str | None]:
        try:
            prepared = prepare_image(
                image_bytes,
                region_bbox=bbox,
                page_width=rendered_page.width,
                page_height=rendered_page.height,
                variant="source-render",
                max_crop_pixels=self.settings.max_crop_pixels,
                max_region_scale=self.settings.max_region_scale,
            )
            artifact = self.store.put_bytes(
                document_id,
                f"page-{page_number:04d}/crops/{line_id}.png",
                prepared.image_bytes,
                overwrite=True,
            )
            return artifact.uri, None
        except (ArtifactStorageError, InvalidDocumentError) as exc:
            return None, f"{line_id}: line crop was not stored: {exc.details.message}"

    def _store_review_artifact(
        self,
        document_id: str,
        page_input: PageInput,
        line: Line,
        *,
        image_bytes: bytes | None,
        rendered_page: RenderedPage | None,
        rendered_uri: str,
        processing_identity: str,
    ) -> tuple[str | None, str | None]:
        if image_bytes is None or rendered_page is None:
            return None, f"{line.id}: review artifact source image is unavailable"
        try:
            from PIL import Image, ImageDraw

            image = Image.open(BytesIO(image_bytes)).convert("RGB")
            overlay = image.copy()
            draw = ImageDraw.Draw(overlay)
            box = (
                max(0, int(line.bbox.x0)),
                max(0, int(line.bbox.y0)),
                min(image.width, int(line.bbox.x1)),
                min(image.height, int(line.bbox.y1)),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                return None, f"{line.id}: review bbox is outside rendered page"
            draw.rectangle(box, outline=(220, 30, 30), width=max(2, image.width // 1000))
            overlay_stream = BytesIO()
            overlay.save(overlay_stream, format="PNG", optimize=False)
            review_id = stable_hash(
                {"line_id": line.id, "processing_identity": processing_identity}
            )[:32]
            overlay_name = self.layout.page_review_name(
                page_input.page_number, f"{review_id}-overlay", "png"
            )
            overlay_artifact = self._put_immutable_artifact(
                document_id, overlay_name, overlay_stream.getvalue()
            )
            payload = {
                "schema_version": "1.0.0",
                "processing_identity": processing_identity,
                "document_id": document_id,
                "page_number": page_input.page_number,
                "line_id": line.id,
                "source_page_uri": line.source.source_uri,
                "rendered_page_uri": rendered_uri,
                "highlighted_page_uri": overlay_artifact.uri,
                "line_crop_uri": line.source.crop_uri,
                "bbox": line.bbox.as_list(),
                "polygon": (
                    [point.model_dump(mode="json") for point in line.polygon]
                    if line.polygon
                    else None
                ),
                "coordinate_space": line.source.coordinate_space.value,
                "page_dimensions": {
                    "width": rendered_page.width,
                    "height": rendered_page.height,
                    "dpi": rendered_page.dpi,
                },
                "status": line.verification_status.value,
                "needs_review": line.needs_review,
                "selected_candidate_id": line.selected_candidate_id,
                "reason_codes": [reason.value for reason in line.reason_codes],
                "uncertainty_flags": [flag.value for flag in line.uncertainty_flags],
                "candidates": [candidate.model_dump(mode="json") for candidate in line.candidates],
                "verification_history": [
                    attempt.model_dump(mode="json", exclude={"created_at"})
                    for attempt in line.verification_history
                ],
                "extraction": line.extraction.model_dump(mode="json"),
            }
            review_name = self.layout.page_review_name(page_input.page_number, review_id, "json")
            review_artifact = self._put_immutable_artifact(
                document_id,
                review_name,
                (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
                    "utf-8"
                ),
            )
            return review_artifact.uri, None
        except (ArtifactStorageError, InvalidDocumentError, OSError, ValueError) as exc:
            return None, f"{line.id}: review artifact was not stored: {exc}"

    def _put_immutable_artifact(
        self, document_id: str, artifact_name: str, data: bytes
    ) -> StoredArtifact:
        try:
            return self.store.put_bytes(document_id, artifact_name, data)
        except ArtifactStorageError:
            if self.store.exists(document_id, artifact_name):
                existing = self.store.get(document_id, artifact_name)
                if existing.checksum_sha256 == sha256_bytes(data):
                    return existing
            raise

    def _block_from_results(
        self,
        document_id: str,
        page_input: PageInput,
        region: OcrRegion,
        results: Sequence[OcrResult],
        rendered_uri: str,
        *,
        image_bytes: bytes | None = None,
        rendered_page: RenderedPage | None = None,
        force_review: bool = False,
        extra_flags: Sequence[ReviewFlag] = (),
    ) -> tuple[Block, list[str]]:
        warnings: list[str] = []
        ordered_results = [
            sort_reading_order(
                list(result.lines),
                direction="rtl"
                if any(line.language.startswith(("fa", "ar")) for line in result.lines)
                else "ltr",
            )
            for result in results
        ]
        line_count = max((len(lines) for lines in ordered_results), default=0)
        lines: list[Line] = []
        for line_index in range(line_count):
            candidates: list[AttemptCandidate] = []
            candidate_records: list[OCRCandidate] = []
            source_lines: list[BackendTextLine] = []
            line_id = f"page-{page_input.page_number}-line-{region.region_id}-{line_index}"
            for result_index, result in enumerate(results):
                if line_index >= len(ordered_results[result_index]):
                    continue
                backend_line = ordered_results[result_index][line_index]
                source_lines.append(backend_line)
                extraction = self._extraction_from_ocr_result(result)
                attempt = make_candidate(
                    backend_line.raw_text,
                    confidence=backend_line.confidence,
                    extraction=extraction,
                    reason=(
                        f"{result.backend}:{result.preprocess_variant}"
                        f":{result.dpi or 0:g}dpi:{result.region_scale:g}x"
                    ),
                    tiny_text=region.tiny_text,
                    candidate_id=f"{line_id}-candidate-{result_index}",
                    language=backend_line.language,
                    script=backend_line.script,
                    normalization_config=self.settings.normalization,
                )
                candidates.append(attempt)
                candidate_records.append(
                    OCRCandidate(
                        id=f"{line_id}-candidate-{result_index}",
                        raw_text=attempt.raw_text,
                        normalized_text=attempt.normalized_text,
                        confidence=attempt.confidence,
                        extraction=attempt.extraction,
                        source=Provenance(
                            document_id=document_id,
                            page_number=page_input.page_number,
                            source_uri=page_input.source_uri,
                            crop_uri=rendered_uri,
                            coordinate_space=region.coordinate_space,
                        ),
                        reason=attempt.reason,
                        tiny_text=attempt.tiny_text,
                    )
                )
            with trace_span("verification", metrics=self.metrics):
                outcome = self.verifier.evaluate(candidates)
            if outcome.selected is None:
                warnings.append(f"{region.region_id}: line {line_index} has no selected candidate")
                continue
            selected_index = next(
                (
                    index
                    for index, attempt in enumerate(candidates)
                    if attempt.candidate_id == outcome.selected_candidate_id
                ),
                0,
            )
            selected_result_line = source_lines[selected_index]
            attempt_reasons = {
                attempt.candidate_id: attempt.reason_codes
                for attempt in outcome.attempts
            }
            candidate_records = [
                candidate.model_copy(
                    update={
                        "reason_codes": list(attempt_reasons.get(candidate.id, ())),
                    }
                )
                for candidate in candidate_records
            ]
            line_crop_uri = None
            if image_bytes is not None and rendered_page is not None:
                line_crop_uri, crop_warning = self._store_line_crop(
                    document_id,
                    page_input.page_number,
                    line_id,
                    image_bytes,
                    rendered_page,
                    selected_result_line.bbox,
                )
                if crop_warning:
                    warnings.append(crop_warning)
            if line_crop_uri:
                candidate_records = [
                    candidate.model_copy(
                        update={
                            "source": candidate.source.model_copy(
                                update={"crop_uri": line_crop_uri}
                            )
                            if candidate.source is not None
                            else None
                        }
                    )
                    for candidate in candidate_records
                ]
            line = self._line_from_verified(
                document_id,
                page_input,
                region,
                line_index,
                selected_result_line,
                outcome,
                rendered_uri,
                candidates=candidate_records,
                line_crop_uri=line_crop_uri,
                force_review=force_review or bool(extra_flags),
                extra_flags=extra_flags,
            )
            if line.needs_review:
                review_uri, review_warning = self._store_review_artifact(
                    document_id,
                    page_input,
                    line,
                    image_bytes=image_bytes,
                    rendered_page=rendered_page,
                    rendered_uri=rendered_uri,
                    processing_identity=stable_hash(
                        {
                            "configuration_hash": self.settings.configuration_hash,
                            "line": {
                                "raw_text": line.raw_text,
                                "normalized_text": line.normalized_text,
                                "confidence": line.confidence,
                                "status": line.verification_status.value,
                                "selected_candidate_id": line.selected_candidate_id,
                                "bbox": line.bbox.as_list(),
                                "reason_codes": [reason.value for reason in line.reason_codes],
                                "uncertainty_flags": [
                                    flag.value for flag in line.uncertainty_flags
                                ],
                            },
                            "candidates": [
                                candidate.model_dump(mode="json") for candidate in line.candidates
                            ],
                            "verification_history": [
                                attempt.model_dump(mode="json", exclude={"created_at"})
                                for attempt in line.verification_history
                            ],
                        }
                    )[:32],
                )
                if review_uri:
                    line = line.model_copy(update={"review_artifact_uri": review_uri})
                if review_warning:
                    warnings.append(review_warning)
            lines.append(line)
        bbox = BoundingBox(
            x0=region.bbox[0],
            y0=region.bbox[1],
            x1=region.bbox[2],
            y1=region.bbox[3],
        )
        block = Block(
            id=f"page-{page_input.page_number}-block-{region.region_id}",
            block_type=region.block_type,
            bbox=bbox,
            reading_order=region.reading_order,
            confidence=mean_confidence([line.confidence for line in lines]),
            source=Provenance(
                document_id=document_id,
                page_number=page_input.page_number,
                source_uri=page_input.source_uri,
                crop_uri=rendered_uri,
                coordinate_space=region.coordinate_space,
            ),
            lines=lines,
            needs_review=force_review or any(line.needs_review for line in lines) or not lines,
            uncertainty_flags=tuple(
                dict.fromkeys(
                    (*extra_flags, *(flag for line in lines for flag in line.uncertainty_flags))
                )
            ),
        )
        return block, warnings

    def _block_from_table_result(
        self,
        document_id: str,
        page_input: PageInput,
        region: OcrRegion,
        result: TableResult,
        rendered_uri: str,
    ) -> tuple[Block, list[str]]:
        extraction = ExtractionMetadata(
            method=result.method,
            backend=result.backend,
            model=result.model,
            model_version=result.model_version,
            dpi=result.dpi,
            region_scale=result.region_scale,
            preprocess_variant=result.preprocess_variant,
            confidence_scale=result.confidence_scale,
            backend_family=result.backend_family,
            configuration_hash=self.settings.configuration_hash,
            runtime_metadata=dict(result.runtime_metadata),
            warnings=list(result.warnings),
        )
        cells: list[TableCellResult] = []
        for cell_index, cell in enumerate(result.cells):
            raw_text = cell.raw_text if cell.raw_text is not None else cell.text
            normalized_text = (
                cell.normalized_text
                if cell.normalized_text is not None
                else normalize_text(raw_text, self.settings.normalization)
            )
            source = Provenance(
                document_id=document_id,
                page_number=page_input.page_number,
                source_uri=page_input.source_uri,
                crop_uri=rendered_uri,
                coordinate_space=region.coordinate_space,
            )
            candidate_id_prefix = (
                f"page-{page_input.page_number}-cell-{region.region_id}-{cell_index}"
            )
            attempts = [
                make_candidate(
                    raw_text,
                    confidence=cell.confidence,
                    extraction=extraction,
                    reason="table_cell_first_pass",
                    tiny_text=region.tiny_text,
                    candidate_id=f"{candidate_id_prefix}-candidate-0",
                    language=cell.language,
                    script=cell.script,
                    normalization_config=self.settings.normalization,
                )
            ]
            for candidate_index, alternate in enumerate(cell.candidates, start=1):
                attempts.append(
                    make_candidate(
                        alternate.raw_text,
                        confidence=alternate.confidence,
                        extraction=extraction,
                        reason=alternate.reason,
                        tiny_text=region.tiny_text,
                        candidate_id=f"{candidate_id_prefix}-candidate-{candidate_index}",
                        language=cell.language,
                        script=cell.script,
                        normalization_config=self.settings.normalization,
                    )
                )
            outcome = self.verifier.evaluate(attempts)
            selected = outcome.selected or attempts[0]
            candidate_attempt_reasons = {
                attempt.candidate_id: attempt.reason_codes for attempt in outcome.attempts
            }
            candidates = [
                OCRCandidate(
                    id=attempt.candidate_id or f"{candidate_id_prefix}-candidate-{index}",
                    raw_text=attempt.raw_text,
                    normalized_text=attempt.normalized_text,
                    confidence=attempt.confidence,
                    extraction=attempt.extraction,
                    source=source,
                    reason=attempt.reason,
                    reason_codes=list(candidate_attempt_reasons.get(attempt.candidate_id, ())),
                    tiny_text=attempt.tiny_text,
                )
                for index, attempt in enumerate(attempts)
            ]
            flags = list(outcome.flags)
            flags.extend(result.review_flags)
            if result.warnings:
                flags.append(ReviewFlag.MANUAL_REVIEW)
            cells.append(
                TableCellResult(
                    id=f"page-{page_input.page_number}-cell-{region.region_id}-{cell_index}",
                    row=cell.row,
                    column=cell.column,
                    raw_text=selected.raw_text,
                    normalized_text=selected.normalized_text or normalized_text,
                    bbox=BoundingBox(
                        x0=cell.bbox[0],
                        y0=cell.bbox[1],
                        x1=cell.bbox[2],
                        y1=cell.bbox[3],
                    ),
                    polygon=list(cell.polygon) if cell.polygon else None,
                    confidence=selected.confidence,
                    language=cell.language,
                    script=cell.script,
                    text_type=TextType.PRINTED,
                    reading_order=cell_index,
                    needs_review=bool(flags)
                    or outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED,
                    source=source,
                    extraction=extraction,
                    verification_status=outcome.status,
                    selected_candidate_id=outcome.selected_candidate_id,
                    uncertainty_flags=flags,
                    reason_codes=list(outcome.reason_codes),
                    verification_history=list(outcome.attempts),
                    candidates=candidates,
                )
            )
        block_flags: list[ReviewFlag] = []
        if not cells:
            block_flags.append(ReviewFlag.TABLE_STRUCTURE_UNCERTAIN)
        if result.warnings:
            block_flags.append(ReviewFlag.MANUAL_REVIEW)
        block_flags.extend(result.review_flags)
        block_flags.extend(flag for cell in cells for flag in cell.uncertainty_flags)
        block_flags = list(dict.fromkeys(block_flags))
        block = Block(
            id=f"page-{page_input.page_number}-block-{region.region_id}",
            block_type=region.block_type,
            bbox=BoundingBox(
                x0=region.bbox[0],
                y0=region.bbox[1],
                x1=region.bbox[2],
                y1=region.bbox[3],
            ),
            reading_order=region.reading_order,
            confidence=mean_confidence([cell.confidence for cell in cells]),
            source=Provenance(
                document_id=document_id,
                page_number=page_input.page_number,
                source_uri=page_input.source_uri,
                crop_uri=rendered_uri,
                coordinate_space=region.coordinate_space,
            ),
            lines=[],
            needs_review=bool(block_flags),
            uncertainty_flags=block_flags,
            table_cells=cells,
        )
        return block, []

    def _line_from_verified(
        self,
        document_id: str,
        page_input: PageInput,
        region: OcrRegion,
        line_index: int,
        backend_line: BackendTextLine,
        outcome,
        rendered_uri: str,
        *,
        candidates: Sequence[OCRCandidate] = (),
        line_crop_uri: str | None = None,
        force_review: bool = False,
        extra_flags: Sequence[ReviewFlag] = (),
    ) -> Line:
        candidate = outcome.selected
        assert candidate is not None
        line_id = f"page-{page_input.page_number}-line-{region.region_id}-{line_index}"
        words = [
            Word(
                id=f"{line_id}-word-{word_index}",
                raw_text=word.text,
                normalized_text=normalize_text(word.text, self.settings.normalization),
                bbox=BoundingBox(
                    x0=max(0.0, word.bbox[0]),
                    y0=max(0.0, word.bbox[1]),
                    x1=max(0.0, word.bbox[2]),
                    y1=max(0.0, word.bbox[3]),
                ),
                confidence=word.confidence,
                reading_order=word.reading_order or word_index,
            )
            for word_index, word in enumerate(backend_line.words)
        ]
        return Line(
            id=line_id,
            raw_text=candidate.raw_text,
            normalized_text=candidate.normalized_text,
            bbox=BoundingBox(
                x0=max(0.0, backend_line.bbox[0]),
                y0=max(0.0, backend_line.bbox[1]),
                x1=max(0.0, backend_line.bbox[2]),
                y1=max(0.0, backend_line.bbox[3]),
            ),
            polygon=list(backend_line.polygon) if backend_line.polygon else None,
            confidence=candidate.confidence,
            language=(
                backend_line.language
                if backend_line.language != "und"
                else _infer_language(candidate.raw_text)
            ),
            script=(
                backend_line.script
                if backend_line.script != "Unknown"
                else _infer_script(candidate.raw_text)
            ),
            text_type=backend_line.text_type,
            reading_order=line_index,
            tiny_text=region.tiny_text,
            needs_review=force_review
            or outcome.status == VerificationStatus.HUMAN_REVIEW_REQUIRED,
            source=Provenance(
                document_id=document_id,
                page_number=page_input.page_number,
                source_uri=page_input.source_uri,
                crop_uri=line_crop_uri or rendered_uri,
                coordinate_space=region.coordinate_space,
            ),
            extraction=candidate.extraction,
            verification_status=(
                VerificationStatus.HUMAN_REVIEW_REQUIRED if force_review else outcome.status
            ),
            selected_candidate_id=outcome.selected_candidate_id,
            uncertainty_flags=list(dict.fromkeys((*extra_flags, *outcome.flags))),
            reason_codes=list(outcome.reason_codes),
            verification_history=list(outcome.attempts),
            candidates=list(candidates),
            words=words,
        )

    @staticmethod
    def _empty_block(
        document_id: str,
        page_input: PageInput,
        region: OcrRegion,
        rendered_uri: str,
        *,
        flags: Sequence[ReviewFlag] = (ReviewFlag.MISSING_BACKEND,),
    ) -> Block:
        return Block(
            id=f"page-{page_input.page_number}-block-{region.region_id}",
            block_type=region.block_type,
            bbox=BoundingBox(
                x0=region.bbox[0],
                y0=region.bbox[1],
                x1=region.bbox[2],
                y1=region.bbox[3],
            ),
            reading_order=region.reading_order,
            source=Provenance(
                document_id=document_id,
                page_number=page_input.page_number,
                source_uri=page_input.source_uri,
                crop_uri=rendered_uri,
                coordinate_space=region.coordinate_space,
            ),
            lines=[],
            needs_review=True,
            uncertainty_flags=list(dict.fromkeys(flags)),
        )

    @staticmethod
    def _quality(pages: Sequence[Page], warnings: Sequence[str]) -> QualityAssessment:
        lines = [line for page in pages for block in page.blocks for line in block.lines]
        cells = [cell for page in pages for block in page.blocks for cell in block.table_cells]
        confidences = [line.confidence for line in lines] + [cell.confidence for cell in cells]
        candidate_disagreements = [
            disagreement_rate([candidate.normalized_text for candidate in line.candidates])
            for line in lines
            if len(line.candidates) > 1
        ] + [
            disagreement_rate([candidate.normalized_text for candidate in cell.candidates])
            for cell in cells
            if len(cell.candidates) > 1
        ]
        disagreement = (
            sum(candidate_disagreements) / len(candidate_disagreements)
            if candidate_disagreements
            else 0.0
        )
        review_count = sum(line.needs_review for line in lines) + sum(
            cell.needs_review for cell in cells
        ) + sum(
            1 for page in pages for block in page.blocks if block.needs_review and not block.lines
        )
        if warnings or review_count:
            status = VerificationStatus.HUMAN_REVIEW_REQUIRED
        elif lines and all(
            line.verification_status == VerificationStatus.VERIFIED for line in lines
        ):
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.ACCEPTED
        return QualityAssessment(
            status=status,
            confidence_mean=mean_confidence(confidences),
            confidence_min=min((value for value in confidences if value is not None), default=None),
            disagreement_rate=disagreement,
            review_line_count=review_count,
            notes=list(warnings)
            + ([f"ocr_disagreement_rate={disagreement:.6f}"] if disagreement else []),
        )

    @staticmethod
    def _layout_warnings(layout_result: LayoutResult | None) -> list[str]:
        if layout_result is None:
            return []
        return [f"layout {warning.code}: {warning.message}" for warning in layout_result.warnings]


def _union_bbox(boxes: Iterable[BoundingBox]) -> BoundingBox:
    values = list(boxes)
    if not values:
        raise InvalidDocumentError("cannot build a block without lines")
    return BoundingBox(
        x0=min(box.x0 for box in values),
        y0=min(box.y0 for box in values),
        x1=max(box.x1 for box in values),
        y1=max(box.y1 for box in values),
    )


def _best_layout_region(
    bbox: BoundingBox, regions: Sequence[LayoutRegion]
) -> LayoutRegion | None:
    if not regions:
        return None
    best = None
    best_intersection = 0.0
    for region in regions:
        intersection_width = max(
            0.0,
            min(bbox.x1, region.bbox[2]) - max(bbox.x0, region.bbox[0]),
        )
        intersection_height = max(
            0.0,
            min(bbox.y1, region.bbox[3]) - max(bbox.y0, region.bbox[1]),
        )
        intersection = intersection_width * intersection_height
        if intersection > best_intersection:
            best = region
            best_intersection = intersection
    return best


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






