"""Reader-neutral, typed ingestion records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from ocr_platform.domain import (
    CoordinateSpace,
    PageType,
    ProcessingStatus,
    ProcessingWarning,
    SourceMetadata,
)


@dataclass(frozen=True, slots=True)
class NativeTextLine:
    text: str
    bbox: tuple[float, float, float, float]
    block_index: int
    line_index: int


@dataclass(frozen=True, slots=True)
class NativeTextEvidence:
    """Evidence used to classify an embedded PDF text layer."""

    character_count: int
    line_count: int
    text_coverage: float
    plausibility_score: float
    suspicious_ratio: float
    has_text_objects: bool
    reliable: bool
    reason: str


@dataclass(frozen=True, slots=True)
class PageQualityMetadata:
    """Small, deterministic quality signals available before OCR."""

    pixel_count: int | None = None
    mean_luminance: float | None = None
    contrast: float | None = None
    sharpness: float | None = None
    blur_score: float | None = None
    skew_angle_degrees: float | None = None
    perspective_distortion_score: float | None = None
    background_variation: float | None = None
    estimated_text_scale: float | None = None
    compression_artifact_score: float | None = None
    text_coverage: float = 0.0
    image_coverage: float = 0.0
    plausibility_score: float | None = None
    suspicious_text_ratio: float | None = None
    exif_orientation: int | None = None
    quality_flags: tuple[str, ...] = ()

    @property
    def brightness(self) -> float | None:
        return self.mean_luminance

    def as_dict(self) -> dict[str, object]:
        return {
            "pixel_count": self.pixel_count,
            "mean_luminance": self.mean_luminance,
            "contrast": self.contrast,
            "brightness": self.mean_luminance,
            "sharpness": self.sharpness,
            "blur_score": self.blur_score,
            "skew_angle_degrees": self.skew_angle_degrees,
            "perspective_distortion_score": self.perspective_distortion_score,
            "background_variation": self.background_variation,
            "estimated_text_scale": self.estimated_text_scale,
            "compression_artifact_score": self.compression_artifact_score,
            "text_coverage": self.text_coverage,
            "image_coverage": self.image_coverage,
            "plausibility_score": self.plausibility_score,
            "suspicious_text_ratio": self.suspicious_text_ratio,
            "exif_orientation": self.exif_orientation,
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Content-addressed reference to a source or derived artifact."""

    uri: str
    checksum_sha256: str
    byte_size: int
    media_type: str
    kind: str
    width: int | None = None
    height: int | None = None
    dpi: int | None = None


@dataclass(frozen=True, slots=True)
class PageInput:
    page_number: int
    width: float
    height: float
    coordinate_space: CoordinateSpace
    page_type: PageType
    source_uri: str
    native_text_reliable: bool
    native_text_reason: str
    native_lines: tuple[NativeTextLine, ...] = ()
    image_regions: tuple[tuple[float, float, float, float], ...] = ()
    source_dpi: float | None = None
    image_format: str | None = None
    rotation: int = 0
    unrotated_width: float | None = None
    unrotated_height: float | None = None
    native_text_evidence: NativeTextEvidence | None = None
    quality: PageQualityMetadata | None = None
    page_id: str | None = None
    render_artifact: ArtifactReference | None = None

    @property
    def needs_ocr(self) -> bool:
        return not self.native_text_reliable or bool(self.image_regions)

    @property
    def tiny_text(self) -> bool:
        return bool(
            self.quality
            and any(
                flag in {"tiny_text", "tiny_text_suspected"}
                for flag in self.quality.quality_flags
            )
        )


@dataclass(frozen=True, slots=True)
class RenderedPage:
    page_number: int
    width: int
    height: int
    dpi: int
    image_format: str
    image_bytes: bytes
    source_uri: str
    rotation: int = 0
    quality: PageQualityMetadata | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Output of source inspection and bounded page rendering."""

    document_id: str
    source: SourceMetadata
    pages: tuple[PageInput, ...]
    source_artifact: ArtifactReference | None = None
    warnings: tuple[ProcessingWarning, ...] = ()
    processing_status: ProcessingStatus = ProcessingStatus.COMPLETED

    @property
    def page_count(self) -> int:
        return len(self.pages)


DocumentIngestionResult = IngestionResult


@dataclass(frozen=True, slots=True)
class DocumentInput:
    """Backward-compatible lightweight input record used by older callers."""

    document_id: str
    path: str
    content_type: str
    source_uri: str
    pages: tuple[PageInput, ...]


class BinaryReader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream

