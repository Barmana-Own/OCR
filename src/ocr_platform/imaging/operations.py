"""Conservative Pillow implementations of composable image operations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ocr_platform.errors import InvalidDocumentError

from .geometry import (
    CoordinateMapping,
    crop_mapping,
    homography_from_correspondences,
    scale_mapping,
)
from .profiles import PreprocessingOperation
from .quality import ImageQualityMetrics


@dataclass(frozen=True, slots=True)
class AppliedOperation:
    operation: PreprocessingOperation
    parameters: dict[str, object]
    image: Any
    mapping: CoordinateMapping
    warnings: tuple[str, ...] = ()


def apply_operation(
    image: Any,
    operation: PreprocessingOperation | str,
    *,
    parameters: Mapping[str, object] | None = None,
    quality: ImageQualityMetrics | None = None,
    max_output_pixels: int = 50_000_000,
) -> AppliedOperation:
    """Apply exactly one bounded operation and return its local mapping."""

    try:
        selected = PreprocessingOperation(operation)
    except ValueError as exc:
        raise InvalidDocumentError(f"unsupported preprocessing operation: {operation}") from exc
    if image.width <= 0 or image.height <= 0:
        raise InvalidDocumentError("preprocessing image dimensions must be positive")
    if max_output_pixels <= 0:
        raise InvalidDocumentError("preprocessing pixel limit must be positive")
    if image.width * image.height > max_output_pixels:
        raise InvalidDocumentError("preprocessing input exceeds configured pixel limit")
    params = dict(parameters or {})
    warnings: list[str] = []
    output = image.copy()
    local_mapping = CoordinateMapping.identity(image.width, image.height)

    from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

    if selected is PreprocessingOperation.CROP:
        left, top, right, bottom = _crop_box(params, image.width, image.height)
        output = image.crop((left, top, right, bottom)).copy()
        local_mapping = CoordinateMapping.for_source(
            source_width=image.width,
            source_height=image.height,
            output_width=right - left,
            output_height=bottom - top,
            output_to_source=crop_mapping(left, top, right - left, bottom - top),
        )
        params = {"bbox": [left, top, right, bottom]}
    elif selected is PreprocessingOperation.SCALE:
        scale = _positive_float(params.get("scale", 1.0), "scale")
        output_width = max(1, int(round(image.width * scale)))
        output_height = max(1, int(round(image.height * scale)))
        if output_width * output_height > max_output_pixels:
            raise InvalidDocumentError("scale operation exceeds configured pixel limit")
        output = image.resize((output_width, output_height), Image.Resampling.LANCZOS)
        local_mapping = CoordinateMapping.for_source(
            source_width=image.width,
            source_height=image.height,
            output_width=output_width,
            output_height=output_height,
            output_to_source=scale_mapping(scale),
        )
        params = {"scale": scale}
    elif selected is PreprocessingOperation.GRAYSCALE:
        output = ImageOps.grayscale(image).convert("RGB")
    elif selected is PreprocessingOperation.CONTRAST_ENHANCEMENT:
        factor = _bounded_float(params.get("factor", 1.0), "factor", 0.1, 4.0)
        output = ImageEnhance.Contrast(image).enhance(factor)
        params = {"factor": factor}
    elif selected is PreprocessingOperation.CLAHE:
        output, fallback = _clahe(image)
        if fallback:
            warnings.append("clahe_fallback_global_equalize")
        params = {
            "clip_limit": _bounded_float(params.get("clip_limit", 1.5), "clip_limit", 0.1, 8.0),
            "tile_size": _positive_int(params.get("tile_size", 8), "tile_size"),
            "implementation": "pillow_equalize_fallback" if fallback else "optional_accelerator",
        }
    elif selected is PreprocessingOperation.MILD_DENOISE:
        radius = _bounded_float(params.get("radius", 0.5), "radius", 0.0, 3.0)
        output = image.filter(ImageFilter.GaussianBlur(radius=radius))
        params = {"radius": radius}
    elif selected is PreprocessingOperation.DESKEW:
        angle = params.get("angle_degrees")
        if angle is None and quality is not None:
            angle = quality.skew_angle_degrees
        if angle is None:
            warnings.append("skew_angle_unavailable")
        else:
            angle = _bounded_float(angle, "angle_degrees", -45.0, 45.0)
            max_angle = _bounded_float(params.get("max_angle", 10.0), "max_angle", 0.1, 45.0)
            if abs(angle) > max_angle:
                warnings.append("deskew_angle_out_of_range")
            else:
                correction = -angle
                output = image.rotate(
                    correction,
                    resample=Image.Resampling.BICUBIC,
                    expand=False,
                    fillcolor="white",
                )
                local_mapping = CoordinateMapping.for_source(
                    source_width=image.width,
                    source_height=image.height,
                    output_width=image.width,
                    output_height=image.height,
                    output_to_source=_rotation_mapping(correction, image.width, image.height),
                )
            params = {"angle_degrees": angle, "max_angle": max_angle}
    elif selected is PreprocessingOperation.PERSPECTIVE_CORRECTION:
        quad = _quad(params.get("source_quad"))
        if quad is None:
            warnings.append("perspective_geometry_unavailable")
            params = {"applied": False}
        else:
            output_width = _positive_int(
                params.get("target_width", image.width), "target_width"
            )
            output_height = _positive_int(
                params.get("target_height", image.height), "target_height"
            )
            if output_width * output_height > max_output_pixels:
                raise InvalidDocumentError("perspective operation exceeds configured pixel limit")
            output = image.transform(
                (output_width, output_height),
                Image.Transform.QUAD,
                data=tuple(value for point in quad for value in point),
                resample=Image.Resampling.BICUBIC,
            )
            output_to_source = homography_from_correspondences(
                (
                    (0.0, 0.0),
                    (float(output_width), 0.0),
                    (float(output_width), float(output_height)),
                    (0.0, float(output_height)),
                ),
                quad,
            )
            local_mapping = CoordinateMapping.for_source(
                source_width=image.width,
                source_height=image.height,
                output_width=output_width,
                output_height=output_height,
                output_to_source=output_to_source,
            )
            params = {
                "source_quad": [[x, y] for x, y in quad],
                "target_width": output_width,
                "target_height": output_height,
                "applied": True,
            }
    elif selected is PreprocessingOperation.BACKGROUND_NORMALIZATION:
        radius = _bounded_float(params.get("radius", 17.0), "radius", 1.0, 100.0)
        strength = _bounded_float(params.get("strength", 0.25), "strength", 0.0, 1.0)
        output = _flatten_background(image, radius=radius, strength=strength)
        params = {"radius": radius, "strength": strength}
    elif selected is PreprocessingOperation.SHADOW_REDUCTION:
        radius = _bounded_float(params.get("radius", 31.0), "radius", 2.0, 150.0)
        strength = _bounded_float(params.get("strength", 0.25), "strength", 0.0, 1.0)
        output = _flatten_background(image, radius=radius, strength=strength)
        params = {"radius": radius, "strength": strength}
    elif selected is PreprocessingOperation.ADAPTIVE_THRESHOLD:
        block_size = _odd_int(params.get("block_size", 31), "block_size", 3, 101)
        offset = _bounded_float(params.get("offset", 8.0), "offset", 0.0, 64.0)
        grayscale = ImageOps.grayscale(image)
        local_mean = grayscale.filter(ImageFilter.BoxBlur((block_size - 1) // 2))
        difference = ImageChops.subtract(grayscale, local_mean, scale=1.0, offset=128)
        cutoff = max(0.0, min(255.0, 128.0 - offset))
        output = difference.point(lambda value: 255 if value >= cutoff else 0).convert("RGB")
        params = {"block_size": block_size, "offset": offset}
    elif selected is PreprocessingOperation.GLOBAL_THRESHOLD:
        threshold_value = params.get("threshold")
        if threshold_value is None:
            threshold_value = ImageStat.Stat(ImageOps.grayscale(image)).mean[0]
        threshold = _bounded_float(threshold_value, "threshold", 0.0, 255.0)
        output = ImageOps.grayscale(image).point(
            lambda value: 255 if value >= threshold else 0
        ).convert("RGB")
        params = {"threshold": threshold}
    elif selected is PreprocessingOperation.SAFE_SHARPEN:
        radius = _bounded_float(params.get("radius", 1.0), "radius", 0.1, 3.0)
        percent = _bounded_float(params.get("percent", 80), "percent", 1.0, 200.0)
        threshold = _bounded_float(params.get("threshold", 3), "threshold", 0.0, 32.0)
        output = image.filter(
            ImageFilter.UnsharpMask(radius=radius, percent=int(percent), threshold=int(threshold))
        )
        params = {"radius": radius, "percent": int(percent), "threshold": int(threshold)}
    elif selected is PreprocessingOperation.BORDER_CLEANUP:
        pixels = _positive_int(params.get("pixels", 1), "pixels")
        if pixels > min(image.size) // 2:
            raise InvalidDocumentError("border cleanup width is too large")
        output = image.convert("RGB").copy()
        draw = ImageDraw.Draw(output)
        draw.rectangle((0, 0, image.width - 1, pixels - 1), fill="white")
        draw.rectangle((0, image.height - pixels, image.width - 1, image.height - 1), fill="white")
        draw.rectangle((0, 0, pixels - 1, image.height - 1), fill="white")
        draw.rectangle((image.width - pixels, 0, image.width - 1, image.height - 1), fill="white")
        params = {"pixels": pixels}
    elif selected is PreprocessingOperation.DEWARPING_HOOK:
        warnings.append("dewarping_hook_not_configured")
        params = {"configured": False}

    if output.width <= 0 or output.height <= 0:
        raise InvalidDocumentError(f"{selected.value} produced invalid dimensions")
    if output.width * output.height > max_output_pixels:
        raise InvalidDocumentError(f"{selected.value} exceeds configured pixel limit")
    return AppliedOperation(
        operation=selected,
        parameters=params,
        image=output,
        mapping=local_mapping,
        warnings=tuple(warnings),
    )


def _flatten_background(image, *, radius: float, strength: float):
    from PIL import Image, ImageChops, ImageFilter, ImageOps

    grayscale = ImageOps.grayscale(image)
    background = grayscale.filter(ImageFilter.GaussianBlur(radius=radius))
    flattened = ImageChops.subtract(grayscale, background, scale=1.0, offset=128)
    flattened = ImageOps.autocontrast(flattened, cutoff=1)
    result = Image.blend(grayscale, flattened, strength)
    return result.convert("RGB")


def _clahe(image) -> tuple[Any, bool]:
    from PIL import ImageOps

    # OpenCV/NumPy are optional.  A global equalize fallback is deterministic,
    # bounded, and explicitly recorded so it is never confused with CLAHE.
    return ImageOps.equalize(ImageOps.grayscale(image)).convert("RGB"), True


def _crop_box(
    parameters: Mapping[str, object], width: int, height: int
) -> tuple[int, int, int, int]:
    value = parameters.get("bbox")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise InvalidDocumentError("crop operation requires a four-value bbox")
    try:
        coordinates = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise InvalidDocumentError("crop bbox must contain numeric values") from exc
    if not all(math.isfinite(item) for item in coordinates):
        raise InvalidDocumentError("crop bbox must contain finite values")
    if coordinates[2] < coordinates[0] or coordinates[3] < coordinates[1]:
        raise InvalidDocumentError("crop bbox coordinates must be ordered")
    left = max(0, min(width - 1, int(coordinates[0])))
    top = max(0, min(height - 1, int(coordinates[1])))
    right = max(left + 1, min(width, int(coordinates[2] + 0.999)))
    bottom = max(top + 1, min(height, int(coordinates[3] + 0.999)))
    if right <= left or bottom <= top:
        raise InvalidDocumentError("crop operation has no visible pixels")
    return left, top, right, bottom


def _quad(value: object) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    result: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return None
        try:
            candidate = (float(point[0]), float(point[1]))
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(item) for item in candidate):
            return None
        result.append(candidate)
    return tuple(result)


def _rotation_mapping(angle: float, width: int, height: int):
    from .geometry import rotation_output_to_input

    return rotation_output_to_input(angle, width, height)


def _positive_int(value: object, name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDocumentError(f"{name} must be an integer") from exc
    if result <= 0:
        raise InvalidDocumentError(f"{name} must be positive")
    return result


def _odd_int(value: object, name: str, minimum: int, maximum: int) -> int:
    result = _positive_int(value, name)
    if result < minimum or result > maximum or result % 2 == 0:
        raise InvalidDocumentError(f"{name} must be an odd integer between {minimum} and {maximum}")
    return result


def _positive_float(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDocumentError(f"{name} must be a number") from exc
    if result <= 0:
        raise InvalidDocumentError(f"{name} must be positive")
    return result


def _bounded_float(value: object, name: str, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDocumentError(f"{name} must be a number") from exc
    if not minimum <= result <= maximum:
        raise InvalidDocumentError(f"{name} is outside the supported range")
    return result
