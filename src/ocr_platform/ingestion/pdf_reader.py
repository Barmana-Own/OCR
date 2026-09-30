"""PyMuPDF PDF inspection and bounded rendering."""

from __future__ import annotations

from pathlib import Path

from ocr_platform.config import Settings
from ocr_platform.domain import CoordinateSpace, PageType
from ocr_platform.errors import (
    BackendUnavailableError,
    CorruptPdfError,
    InvalidDocumentError,
    PageRenderError,
    PasswordProtectedPdfError,
)
from ocr_platform.imaging.policy import bounded_render_dimensions
from ocr_platform.imaging.quality import ImageQualityAnalyzer, quality_metadata_fields

from .models import NativeTextEvidence, NativeTextLine, PageInput, PageQualityMetadata, RenderedPage


class PdfReader:
    """Inspect PDF pages independently and render only bounded page rasters."""

    backend_name = "pymupdf"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _load_fitz(self):
        try:
            import fitz
        except ImportError as exc:
            raise BackendUnavailableError("PyMuPDF is required for PDF processing") from exc
        return fitz

    def extract(self, path: Path, *, document_id: str, source_uri: str) -> tuple[PageInput, ...]:
        fitz = self._load_fitz()
        try:
            document = fitz.open(path)
        except Exception as exc:
            raise CorruptPdfError("PDF could not be opened") from exc
        try:
            if getattr(document, "needs_pass", False):
                raise PasswordProtectedPdfError()
            if len(document) > self.settings.max_pages:
                raise InvalidDocumentError("PDF exceeds configured page limit")
            pages: list[PageInput] = []
            for index in range(len(document)):
                page = document.load_page(index)
                visible_width = float(page.rect.width)
                visible_height = float(page.rect.height)
                media_width = float(page.mediabox.width)
                media_height = float(page.mediabox.height)
                self._validate_page_dimensions(visible_width, visible_height)
                self._validate_page_dimensions(media_width, media_height)
                native_lines = self._native_lines(page)
                image_regions = self._image_regions(page)
                evidence = self._native_evidence(
                    native_lines,
                    width=visible_width,
                    height=visible_height,
                )
                image_coverage = self._coverage(image_regions, visible_width, visible_height)
                rotation = self._normalise_rotation(getattr(page, "rotation", 0))
                page_type = (
                    PageType.MIXED
                    if image_regions and native_lines
                    else PageType.NATIVE_TEXT
                    if evidence.reliable
                    else PageType.SCANNED
                )
                quality_flags: list[str] = []
                if any(
                    line.bbox[3] - line.bbox[1] < self.settings.tiny_text_line_height_points
                    for line in native_lines
                ):
                    quality_flags.append("tiny_text")
                if evidence.reason not in {"embedded_text_reliable", "no_embedded_text"}:
                    quality_flags.append(evidence.reason)
                if image_coverage > 0.75:
                    quality_flags.append("image_dominant")
                pages.append(
                    PageInput(
                        page_number=index + 1,
                        page_id=f"{document_id}-page-{index + 1:04d}",
                        width=visible_width,
                        height=visible_height,
                        coordinate_space=CoordinateSpace.PDF_POINT,
                        page_type=page_type,
                        source_uri=f"{source_uri}#page={index + 1}",
                        native_text_reliable=evidence.reliable,
                        native_text_reason=evidence.reason,
                        native_lines=tuple(native_lines),
                        image_regions=tuple(image_regions),
                        rotation=rotation,
                        unrotated_width=media_width,
                        unrotated_height=media_height,
                        native_text_evidence=evidence,
                        quality=PageQualityMetadata(
                            text_coverage=evidence.text_coverage,
                            image_coverage=image_coverage,
                            plausibility_score=evidence.plausibility_score,
                            suspicious_text_ratio=evidence.suspicious_ratio,
                            quality_flags=tuple(quality_flags),
                        ),
                    )
                )
            return tuple(pages)
        except (InvalidDocumentError, PasswordProtectedPdfError):
            raise
        except Exception as exc:
            raise CorruptPdfError("PDF page inspection failed") from exc
        finally:
            document.close()

    read = extract

    def _native_lines(self, page) -> list[NativeTextLine]:
        try:
            fitz = self._load_fitz()
            text_flags = getattr(fitz, "TEXTFLAGS_TEXT", None)
            payload = (
                page.get_text("dict")
                if text_flags is None
                else page.get_text("dict", flags=text_flags)
            )
        except Exception as exc:
            raise CorruptPdfError("PDF text layer could not be read") from exc
        lines: list[NativeTextLine] = []
        for block_index, block in enumerate(payload.get("blocks", [])):
            if block.get("type") != 0:
                continue
            for line_index, line in enumerate(block.get("lines", [])):
                text = "".join(str(span.get("text", "")) for span in line.get("spans", []))
                text = text.rstrip("\r\n")
                bbox = line.get("bbox")
                if text.strip() and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    values = tuple(float(value) for value in bbox)
                    if values[2] >= values[0] and values[3] >= values[1]:
                        lines.append(
                            NativeTextLine(
                                text=text,
                                bbox=values,
                                block_index=block_index,
                                line_index=line_index,
                            )
                        )
        return lines
    def _image_regions(self, page) -> list[tuple[float, float, float, float]]:
        regions: list[tuple[float, float, float, float]] = []
        try:
            if hasattr(page, "get_image_info"):
                image_info = page.get_image_info()
                for item in image_info:
                    bbox = item.get("bbox")
                    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                        values = tuple(float(value) for value in bbox)
                        if values[2] > values[0] and values[3] > values[1]:
                            regions.append(values)
            if not regions:
                for block in page.get_text("blocks"):
                    if len(block) < 7 or int(block[6]) != 1:
                        continue
                    values = tuple(float(value) for value in block[:4])
                    if values[2] > values[0] and values[3] > values[1]:
                        regions.append(values)
        except Exception as exc:
            raise CorruptPdfError("PDF image regions could not be read") from exc
        return regions
    def _native_evidence(
        self,
        lines: list[NativeTextLine],
        *,
        width: float,
        height: float,
    ) -> NativeTextEvidence:
        text = "\n".join(line.text for line in lines)
        visible = [char for char in text if not char.isspace()]
        character_count = len(visible)
        suspicious_count = sum(
            char == "\ufffd" or (not char.isprintable() and not char.isspace())
            for char in visible
        )
        suspicious_ratio = suspicious_count / character_count if character_count else 0.0
        useful_count = sum(char.isalnum() for char in visible)
        plausibility = (
            (useful_count / character_count) * (1.0 - suspicious_ratio)
            if character_count
            else 0.0
        )
        coverage = self._coverage([line.bbox for line in lines], width, height)
        reason = "embedded_text_reliable"
        reliable = True
        if not lines:
            reason, reliable = "no_embedded_text", False
        elif character_count < self.settings.native_text_min_characters:
            reason, reliable = "embedded_text_too_sparse", False
        elif suspicious_ratio > self.settings.native_text_max_suspicious_ratio:
            reason, reliable = "embedded_text_suspicious", False
        elif plausibility < self.settings.native_text_min_plausibility:
            reason, reliable = "embedded_text_implausible", False
        elif coverage < self.settings.native_text_min_coverage:
            reason, reliable = "embedded_text_low_coverage", False
        return NativeTextEvidence(
            character_count=character_count,
            line_count=len(lines),
            text_coverage=coverage,
            plausibility_score=plausibility,
            suspicious_ratio=suspicious_ratio,
            has_text_objects=bool(lines),
            reliable=reliable,
            reason=reason,
        )

    @staticmethod
    def _coverage(
        boxes: list[tuple[float, float, float, float]], width: float, height: float
    ) -> float:
        if width <= 0 or height <= 0:
            return 0.0
        area = sum(
            max(0.0, right - left) * max(0.0, bottom - top)
            for left, top, right, bottom in boxes
        )
        return min(1.0, area / (width * height))

    def _validate_page_dimensions(self, width: float, height: float) -> None:
        if width <= 0 or height <= 0:
            raise InvalidDocumentError("PDF page dimensions must be positive")
        if width > self.settings.max_page_width or height > self.settings.max_page_height:
            raise InvalidDocumentError("PDF page dimensions exceed configured page dimensions")

    @staticmethod
    def _normalise_rotation(rotation: int) -> int:
        normalised = int(rotation or 0) % 360
        return normalised if normalised in {0, 90, 180, 270} else 0

    def render_page(self, path: Path, *, page_number: int, dpi: int) -> RenderedPage:
        fitz = self._load_fitz()
        if dpi <= 0:
            raise PageRenderError("DPI must be positive", retryable=False)
        if page_number <= 0:
            raise PageRenderError("page number must be positive", retryable=False)
        document = None
        try:
            document = fitz.open(path)
            if getattr(document, "needs_pass", False):
                raise PasswordProtectedPdfError()
            if page_number > len(document):
                raise PageRenderError("page number is outside the PDF")
            page = document.load_page(page_number - 1)
            self._validate_page_dimensions(float(page.rect.width), float(page.rect.height))
            width, height = bounded_render_dimensions(
                float(page.rect.width),
                float(page.rect.height),
                dpi,
                self.settings.max_render_pixels,
            )
            scale = dpi / 72.0
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            if pixmap.width * pixmap.height > self.settings.max_render_pixels:
                raise PageRenderError("rendered page exceeds configured pixel limit")
            image_bytes = pixmap.tobytes("png")
            metrics = ImageQualityAnalyzer().analyze(image_bytes, image_format="png")
            quality_fields = quality_metadata_fields(metrics)
            return RenderedPage(
                page_number=page_number,
                width=pixmap.width or width,
                height=pixmap.height or height,
                dpi=dpi,
                image_format="png",
                image_bytes=image_bytes,
                source_uri=f"file://{path}#page={page_number}",
                rotation=self._normalise_rotation(getattr(page, "rotation", 0)),
                quality=PageQualityMetadata(
                    pixel_count=int(quality_fields["pixel_count"]),
                    mean_luminance=float(quality_fields["mean_luminance"]),
                    contrast=float(quality_fields["contrast"]),
                    sharpness=float(quality_fields["sharpness"]),
                    blur_score=float(quality_fields["blur_score"]),
                    skew_angle_degrees=quality_fields["skew_angle_degrees"],
                    perspective_distortion_score=quality_fields["perspective_distortion_score"],
                    background_variation=quality_fields["background_variation"],
                    estimated_text_scale=quality_fields["estimated_text_scale"],
                    compression_artifact_score=quality_fields["compression_artifact_score"],
                    quality_flags=tuple(quality_fields["quality_flags"]),
                ),
            )
        except (InvalidDocumentError, PageRenderError, PasswordProtectedPdfError):
            raise
        except Exception as exc:
            raise PageRenderError("PDF page could not be rendered") from exc
        finally:
            if document is not None:
                document.close()



