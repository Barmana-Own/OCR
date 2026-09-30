"""Bounded image preparation for region OCR and verification retries."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from ocr_platform.domain import PolygonPoint
from ocr_platform.errors import InvalidDocumentError

from .geometry import CoordinateMapping
from .operations import apply_operation
from .profiles import get_profile


@dataclass(frozen=True)
class PreparedImage:
    """Image bytes plus the transform needed to restore OCR geometry."""

    image_bytes: bytes
    width: int
    height: int
    offset_x: int
    offset_y: int
    scale: int
    variant: str
    mapping: CoordinateMapping | None = None
    profile_name: str | None = None


def prepare_image(
    image_bytes: bytes,
    *,
    region_bbox: tuple[float, float, float, float],
    page_width: int,
    page_height: int,
    variant: str,
    max_crop_pixels: int,
    max_region_scale: int,
    profile_name: str | None = None,
    enabled_profiles: tuple[str, ...] | None = None,
) -> PreparedImage:
    """Crop, optionally scale, and safely preprocess an OCR region.

    Coordinates are expressed in the rendered page pixel space. Every transform
    is bounded and records enough metadata to map backend geometry back to that
    page space.
    """
    if page_width <= 0 or page_height <= 0:
        raise InvalidDocumentError("prepared image dimensions must be positive")
    scale = _scale_for_variant(variant, max_region_scale)
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            if image.width != page_width or image.height != page_height:
                raise InvalidDocumentError("rendered image dimensions do not match page metadata")
            left, top, right, bottom = _clip_bbox(
                region_bbox,
                width=page_width,
                height=page_height,
            )
            cropped = image.crop((left, top, right, bottom)).convert("RGB")
            if variant == "grayscale":
                cropped = ImageOps.grayscale(cropped).convert("RGB")
            elif variant == "contrast":
                grayscale = ImageOps.grayscale(cropped)
                cropped = ImageOps.autocontrast(grayscale).convert("RGB")
            elif variant == "threshold":
                grayscale = ImageOps.grayscale(cropped)
                cropped = grayscale.point(lambda value: 255 if value >= 180 else 0).convert("RGB")
            elif variant == "sharpen":
                cropped = cropped.filter(
                    ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3)
                )
            elif variant == "brightness":
                cropped = ImageEnhance.Brightness(cropped).enhance(1.15)
            elif variant not in {
                "source-render",
                "region-scale-2",
                "region-scale-3",
                "region-scale-4",
            }:
                raise InvalidDocumentError(f"unsupported preprocess variant: {variant}")
            if scale > 1:
                resized_width = cropped.width * scale
                resized_height = cropped.height * scale
                if resized_width * resized_height > max_crop_pixels:
                    raise InvalidDocumentError("region scale exceeds configured crop pixel limit")
                cropped = cropped.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
            mapping = CoordinateMapping.for_source(
                source_width=page_width,
                source_height=page_height,
                output_width=cropped.width,
                output_height=cropped.height,
                output_to_source=(
                    1.0 / scale,
                    0.0,
                    float(left),
                    0.0,
                    1.0 / scale,
                    float(top),
                    0.0,
                    0.0,
                    1.0,
                ),
            )
            if profile_name is not None:
                profile = get_profile(profile_name, enabled=enabled_profiles)
                for step in profile.steps:
                    applied = apply_operation(
                        cropped,
                        step.operation,
                        parameters=step.parameter_dict(),
                        max_output_pixels=max_crop_pixels,
                    )
                    cropped = applied.image
                    mapping = mapping.compose(applied.mapping)
            buffer = BytesIO()
            cropped.save(buffer, format="PNG", optimize=False)
            return PreparedImage(
                image_bytes=buffer.getvalue(),
                width=cropped.width,
                height=cropped.height,
                offset_x=left,
                offset_y=top,
                scale=scale,
                variant=variant,
                mapping=mapping,
                profile_name=profile_name,
            )
    except InvalidDocumentError:
        raise
    except Exception as exc:
        raise InvalidDocumentError("OCR image preparation failed") from exc


def map_bbox_to_page(
    bbox: tuple[float, float, float, float], prepared: PreparedImage
) -> tuple[float, float, float, float]:
    """Map a backend bbox from prepared-image pixels to rendered page pixels."""
    if prepared.mapping is not None:
        return prepared.mapping.map_bbox_to_source(bbox)
    scale = float(prepared.scale)
    return (
        prepared.offset_x + bbox[0] / scale,
        prepared.offset_y + bbox[1] / scale,
        prepared.offset_x + bbox[2] / scale,
        prepared.offset_y + bbox[3] / scale,
    )


def map_polygon_to_page(
    polygon: tuple[PolygonPoint, ...] | None,
    prepared: PreparedImage,
) -> tuple[PolygonPoint, ...] | None:
    if polygon is None:
        return None
    if prepared.mapping is not None:
        mapped = prepared.mapping.map_polygon_to_source(
            tuple((point.x, point.y) for point in polygon)
        )
        return tuple(PolygonPoint(x=x, y=y) for x, y in mapped)
    scale = float(prepared.scale)
    return tuple(
        PolygonPoint(
            x=prepared.offset_x + point.x / scale,
            y=prepared.offset_y + point.y / scale,
        )
        for point in polygon
    )


def _clip_bbox(
    bbox: tuple[float, float, float, float], *, width: int, height: int
) -> tuple[int, int, int, int]:
    left = max(0, min(width - 1, int(bbox[0])))
    top = max(0, min(height - 1, int(bbox[1])))
    right = max(left + 1, min(width, int(bbox[2] + 0.999)))
    bottom = max(top + 1, min(height, int(bbox[3] + 0.999)))
    if right <= left or bottom <= top:
        raise InvalidDocumentError("OCR region has no visible pixels")
    return left, top, right, bottom


def _scale_for_variant(variant: str, max_region_scale: int) -> int:
    if variant in {"region-scale-2", "region-scale-3", "region-scale-4"}:
        scale = int(variant.rsplit("-", 1)[1])
        if scale > max_region_scale:
            raise InvalidDocumentError("region scale exceeds configured limit")
        return scale
    return 1
