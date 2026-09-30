"""Bounded, deterministic image-quality hints for OCR routing.

The analyzer deliberately reports signals rather than a binary quality verdict.
All measurements are computed from a bounded Pillow sample so a large upload
cannot force an unbounded analysis allocation.  Optional computer-vision
accelerators may be added behind this contract later; the required path remains
provider-neutral and conservative.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from statistics import median
from typing import Any

from ocr_platform.errors import ImageDecodeError, InvalidDocumentError


@dataclass(frozen=True, slots=True)
class ImageQualityMetrics:
    width: int
    height: int
    pixel_count: int
    brightness: float
    contrast: float
    sharpness: float
    blur_score: float | None
    skew_angle_degrees: float | None
    perspective_distortion_score: float | None
    background_variation: float | None
    estimated_text_scale: float | None
    compression_artifact_score: float | None
    quality_flags: tuple[str, ...] = ()

    @property
    def mean_luminance(self) -> float:
        return self.brightness

    def as_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "pixel_count": self.pixel_count,
            "brightness": self.brightness,
            "mean_luminance": self.brightness,
            "contrast": self.contrast,
            "sharpness": self.sharpness,
            "blur_score": self.blur_score,
            "skew_angle_degrees": self.skew_angle_degrees,
            "perspective_distortion_score": self.perspective_distortion_score,
            "background_variation": self.background_variation,
            "estimated_text_scale": self.estimated_text_scale,
            "compression_artifact_score": self.compression_artifact_score,
            "quality_flags": list(self.quality_flags),
        }


class ImageQualityAnalyzer:
    """Calculate OCR-routing hints without mutating the input image."""

    def __init__(
        self,
        *,
        max_analysis_pixels: int = 600_000,
        max_input_pixels: int = 50_000_000,
        skew_search_degrees: float = 8.0,
        skew_step_degrees: float = 0.5,
    ) -> None:
        if max_analysis_pixels <= 0:
            raise InvalidDocumentError("quality analysis pixel limit must be positive")
        if max_input_pixels <= 0:
            raise InvalidDocumentError("quality input pixel limit must be positive")
        if skew_search_degrees <= 0 or skew_step_degrees <= 0:
            raise InvalidDocumentError("quality skew search parameters must be positive")
        self.max_analysis_pixels = max_analysis_pixels
        self.max_input_pixels = max_input_pixels
        self.skew_search_degrees = skew_search_degrees
        self.skew_step_degrees = skew_step_degrees

    def analyze(
        self, image: bytes | Any, *, image_format: str | None = None
    ) -> ImageQualityMetrics:
        try:
            from PIL import Image, ImageFilter, ImageOps, ImageStat

            opened_format: str | None = image_format
            image_info: dict[str, object] = {}
            if isinstance(image, (bytes, bytearray, memoryview)):
                with Image.open(BytesIO(bytes(image))) as opened:
                    if opened.width * opened.height > self.max_input_pixels:
                        raise InvalidDocumentError("quality input exceeds configured pixel limit")
                    opened.load()
                    opened_format = opened_format or opened.format
                    image_info = dict(opened.info)
                    original = opened.convert("RGB").copy()
            else:
                if not hasattr(image, "size"):
                    raise ImageDecodeError("quality analysis input is not an image")
                if image.width * image.height > self.max_input_pixels:
                    raise InvalidDocumentError("quality input exceeds configured pixel limit")
                opened_format = opened_format or getattr(image, "format", None)
                image_info = dict(getattr(image, "info", {}) or {})
                original = image.convert("RGB").copy()
            width, height = original.size
            if width <= 0 or height <= 0:
                raise ImageDecodeError("quality analysis image dimensions must be positive")
            sample = self._bounded_sample(original, Image)
            grayscale = ImageOps.grayscale(sample)
            statistics = ImageStat.Stat(grayscale)
            brightness = float(statistics.mean[0])
            contrast = float(statistics.stddev[0])
            edges = grayscale.filter(ImageFilter.FIND_EDGES)
            edge_statistics = ImageStat.Stat(edges)
            sharpness = float(edge_statistics.stddev[0])
            blur_score = max(0.0, min(1.0, 1.0 - sharpness / 64.0))
            skew = self._estimate_skew(grayscale, brightness, contrast)
            background_variation = self._background_variation(grayscale)
            estimated_text_scale = self._estimate_text_scale(grayscale, brightness, contrast)
            perspective = self._estimate_perspective(grayscale)
            compression = self._compression_score(image_info, opened_format)
            flags = self._flags(
                contrast=contrast,
                sharpness=sharpness,
                skew=skew,
                perspective=perspective,
                background_variation=background_variation,
                estimated_text_scale=estimated_text_scale,
                compression=compression,
            )
            return ImageQualityMetrics(
                width=width,
                height=height,
                pixel_count=width * height,
                brightness=brightness,
                contrast=contrast,
                sharpness=sharpness,
                blur_score=blur_score,
                skew_angle_degrees=skew,
                perspective_distortion_score=perspective,
                background_variation=background_variation,
                estimated_text_scale=estimated_text_scale,
                compression_artifact_score=compression,
                quality_flags=flags,
            )
        except (ImageDecodeError, InvalidDocumentError):
            raise
        except Exception as exc:
            raise ImageDecodeError("image quality analysis failed") from exc

    def _bounded_sample(self, image, Image):
        if image.width * image.height <= self.max_analysis_pixels:
            return image
        factor = math.sqrt(self.max_analysis_pixels / (image.width * image.height))
        size = (max(1, int(image.width * factor)), max(1, int(image.height * factor)))
        return image.resize(size, Image.Resampling.BILINEAR)

    def _estimate_skew(self, grayscale, brightness: float, contrast: float) -> float | None:
        threshold = min(220.0, max(80.0, brightness - max(5.0, contrast * 0.20)))
        dark_density = self._dark_density(grayscale, threshold)
        if dark_density < 0.0005 or dark_density > 0.85:
            return None
        best_angle: float | None = None
        best_score = -1.0
        angle = -self.skew_search_degrees
        while angle <= self.skew_search_degrees + 1e-9:
            rotated = grayscale.rotate(
                angle,
                resample=self._nearest_resampling(),
                expand=False,
                fillcolor=255,
            )
            score = self._horizontal_projection_score(rotated, threshold)
            if score > best_score:
                best_angle = angle
                best_score = score
            angle += self.skew_step_degrees
        return best_angle

    @staticmethod
    def _nearest_resampling():
        from PIL import Image

        return Image.Resampling.NEAREST

    @staticmethod
    def _dark_density(grayscale, threshold: float) -> float:
        pixels = grayscale.load()
        total = grayscale.width * grayscale.height
        dark = sum(
            1
            for y in range(grayscale.height)
            for x in range(grayscale.width)
            if pixels[x, y] < threshold
        )
        return dark / total if total else 0.0

    @staticmethod
    def _horizontal_projection_score(grayscale, threshold: float) -> float:
        pixels = grayscale.load()
        row_counts = [
            sum(1 for x in range(grayscale.width) if pixels[x, y] < threshold)
            for y in range(grayscale.height)
        ]
        if not row_counts:
            return 0.0
        mean = sum(row_counts) / len(row_counts)
        return sum((count - mean) ** 2 for count in row_counts) / len(row_counts)

    @staticmethod
    def _background_variation(grayscale) -> float:
        from PIL import ImageFilter, ImageStat

        radius = max(2.0, min(25.0, min(grayscale.size) / 20.0))
        blurred = grayscale.filter(ImageFilter.GaussianBlur(radius=radius))
        return max(0.0, min(1.0, float(ImageStat.Stat(blurred).stddev[0]) / 255.0))

    @staticmethod
    def _estimate_text_scale(grayscale, brightness: float, contrast: float) -> float | None:
        threshold = min(220.0, max(80.0, brightness - max(5.0, contrast * 0.20)))
        pixels = grayscale.load()
        row_has_dark = [
            any(pixels[x, y] < threshold for x in range(grayscale.width))
            for y in range(grayscale.height)
        ]
        runs: list[int] = []
        current = 0
        for has_dark in row_has_dark + [False]:
            if has_dark:
                current += 1
            elif current:
                runs.append(current)
                current = 0
        if not runs:
            return None
        return float(median(runs))

    @staticmethod
    def _estimate_perspective(grayscale) -> float:
        pixels = grayscale.load()
        width, height = grayscale.size
        band_x = max(1, width // 20)
        band_y = max(1, height // 20)

        def mean(points: list[int]) -> float:
            return sum(points) / len(points) if points else 255.0

        top = mean([pixels[x, y] for y in range(band_y) for x in range(width)])
        bottom = mean(
            [pixels[x, y] for y in range(max(0, height - band_y), height) for x in range(width)]
        )
        left = mean([pixels[x, y] for x in range(band_x) for y in range(height)])
        right = mean(
            [pixels[x, y] for x in range(max(0, width - band_x), width) for y in range(height)]
        )
        return max(0.0, min(1.0, (abs(top - bottom) + abs(left - right)) / 510.0))

    @staticmethod
    def _compression_score(info: dict[str, object], image_format: str | None) -> float | None:
        quantization = info.get("quantization")
        values: list[int] = []
        if isinstance(quantization, dict):
            for table in quantization.values():
                if isinstance(table, (list, tuple)):
                    values.extend(int(value) for value in table if isinstance(value, int | float))
        if values:
            return max(0.0, min(1.0, max(values) / 255.0))
        if (image_format or "").lower() in {"jpeg", "jpg"}:
            return None
        return 0.0

    @staticmethod
    def _flags(
        *,
        contrast: float,
        sharpness: float,
        skew: float | None,
        perspective: float | None,
        background_variation: float | None,
        estimated_text_scale: float | None,
        compression: float | None,
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if contrast < 10.0:
            flags.append("low_contrast")
        if sharpness < 3.0:
            flags.append("low_sharpness")
        if skew is not None and abs(skew) >= 1.0:
            flags.append("skew_detected")
        if perspective is not None and perspective >= 0.20:
            flags.append("perspective_suspected")
        if background_variation is not None and background_variation >= 0.12:
            flags.append("uneven_background")
        if estimated_text_scale is not None and estimated_text_scale < 12.0:
            flags.append("tiny_text_suspected")
        if compression is not None and compression >= 0.70:
            flags.append("compression_artifacts_suspected")
        return tuple(flags)


def quality_metadata_fields(metrics: ImageQualityMetrics) -> dict[str, object]:
    """Return fields shared by ingestion's lightweight page metadata record."""

    return {
        "pixel_count": metrics.pixel_count,
        "mean_luminance": metrics.brightness,
        "contrast": metrics.contrast,
        "sharpness": metrics.sharpness,
        "blur_score": metrics.blur_score,
        "skew_angle_degrees": metrics.skew_angle_degrees,
        "perspective_distortion_score": metrics.perspective_distortion_score,
        "background_variation": metrics.background_variation,
        "estimated_text_scale": metrics.estimated_text_scale,
        "compression_artifact_score": metrics.compression_artifact_score,
        "quality_flags": metrics.quality_flags,
    }
