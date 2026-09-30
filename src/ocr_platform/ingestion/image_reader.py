"""Pillow image inspection, EXIF correction, and bounded rendering."""

from __future__ import annotations

from pathlib import Path

from ocr_platform.config import Settings
from ocr_platform.domain import CoordinateSpace, PageType
from ocr_platform.errors import (
    BackendUnavailableError,
    ImageDecodeError,
    InvalidDocumentError,
    PageRenderError,
)
from ocr_platform.imaging.quality import ImageQualityAnalyzer, quality_metadata_fields

from .models import PageInput, PageQualityMetadata, RenderedPage


class ImageReader:
    backend_name = "pillow"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _load_pillow(self):
        try:
            from PIL import Image
        except ImportError as exc:
            raise BackendUnavailableError("Pillow is required for image processing") from exc
        return Image

    def read(
        self,
        path: Path,
        *,
        source_uri: str,
        document_id: str | None = None,
    ) -> tuple[PageInput, ...]:
        Image = self._load_pillow()
        try:
            from PIL import ImageOps

            with Image.open(path) as image:
                original_width, original_height = image.size
                self._validate_dimensions(original_width, original_height)
                orientation = self._exif_orientation(image)
                corrected = ImageOps.exif_transpose(image)
                try:
                    corrected.load()
                    width, height = corrected.size
                    self._validate_dimensions(width, height)
                    quality = self._quality_metadata(
                        corrected,
                        orientation=orientation,
                        original_width=original_width,
                        original_height=original_height,
                        image_format=str(image.format or ""),
                    )
                    page_id = f"{document_id}-page-0001" if document_id else None
                    return (
                        PageInput(
                            page_number=1,
                            page_id=page_id,
                            width=float(width),
                            height=float(height),
                            coordinate_space=CoordinateSpace.SOURCE_PIXEL,
                            page_type=PageType.IMAGE,
                            source_uri=f"{source_uri}#page=1",
                            native_text_reliable=False,
                            native_text_reason="raster_image",
                            source_dpi=self._source_dpi(image.info.get("dpi")),
                            image_format=str(image.format or "unknown").lower(),
                            rotation=0,
                            unrotated_width=float(original_width),
                            unrotated_height=float(original_height),
                            quality=quality,
                        ),
                    )
                finally:
                    if corrected is not image:
                        corrected.close()
        except InvalidDocumentError:
            raise
        except Exception as exc:
            raise ImageDecodeError() from exc

    def render(self, path: Path, *, source_uri: str) -> RenderedPage:
        Image = self._load_pillow()
        try:
            from PIL import ImageOps

            with Image.open(path) as image:
                original_width, original_height = image.size
                self._validate_dimensions(original_width, original_height)
                orientation = self._exif_orientation(image)
                dpi = int(
                    round(self._source_dpi(image.info.get("dpi")) or self.settings.default_dpi)
                )
                corrected = ImageOps.exif_transpose(image)
                try:
                    corrected.load()
                    width, height = corrected.size
                    self._validate_dimensions(width, height)
                    image_bytes = self._encode_png(Image, corrected)
                    return RenderedPage(
                        page_number=1,
                        width=width,
                        height=height,
                        dpi=dpi,
                        image_format="png",
                        image_bytes=image_bytes,
                        source_uri=source_uri,
                        rotation=0,
                        quality=self._quality_metadata(
                            corrected,
                            orientation=orientation,
                            original_width=original_width,
                            original_height=original_height,
                            image_format=str(image.format or ""),
                        ),
                    )
                finally:
                    if corrected is not image:
                        corrected.close()
        except InvalidDocumentError:
            raise
        except Exception as exc:
            raise PageRenderError("image could not be rendered") from exc

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ImageDecodeError("image dimensions must be positive")
        if width > self.settings.max_page_width or height > self.settings.max_page_height:
            raise InvalidDocumentError("image page dimensions exceed configured page dimensions")
        if width * height > self.settings.max_render_pixels:
            raise InvalidDocumentError("image exceeds configured pixel limit")

    @staticmethod
    def _exif_orientation(image) -> int | None:
        try:
            value = image.getexif().get(274)
        except Exception:
            return None
        return int(value) if isinstance(value, int) and 1 <= value <= 8 else None

    @staticmethod
    def _source_dpi(value: object) -> float | None:
        if isinstance(value, tuple) and value and isinstance(value[0], (int, float)):
            return float(value[0]) if value[0] > 0 else None
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return None

    @staticmethod
    def _quality_metadata(
        image,
        *,
        orientation: int | None,
        original_width: int,
        original_height: int,
        image_format: str | None,
    ) -> PageQualityMetadata:
        metrics = ImageQualityAnalyzer().analyze(image, image_format=image_format)
        fields = quality_metadata_fields(metrics)
        flags = list(fields["quality_flags"])
        if image.size != (original_width, original_height):
            flags.append("exif_orientation_applied")
        return PageQualityMetadata(
            pixel_count=int(fields["pixel_count"]),
            mean_luminance=float(fields["mean_luminance"]),
            contrast=float(fields["contrast"]),
            sharpness=float(fields["sharpness"]),
            blur_score=float(fields["blur_score"]),
            skew_angle_degrees=fields["skew_angle_degrees"],
            perspective_distortion_score=fields["perspective_distortion_score"],
            background_variation=fields["background_variation"],
            estimated_text_scale=fields["estimated_text_scale"],
            compression_artifact_score=fields["compression_artifact_score"],
            exif_orientation=orientation,
            quality_flags=tuple(flags),
        )

    @staticmethod
    def _encode_png(Image, image) -> bytes:
        from io import BytesIO

        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=False)
        return buffer.getvalue()

