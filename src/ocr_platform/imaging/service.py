"""Artifact-aware preprocessing orchestration and tiny-text escalation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from ocr_platform.config import Settings
from ocr_platform.errors import ArtifactStorageError, InvalidDocumentError, StorageFailureError
from ocr_platform.storage import ArtifactLayout, ArtifactStore, LocalArtifactStore

from .geometry import CoordinateMapping
from .operations import AppliedOperation, apply_operation
from .profiles import PreprocessingProfile, get_profile
from .quality import ImageQualityAnalyzer, ImageQualityMetrics
from .tiny_text import TinyTextDecision, TinyTextPlanner


@dataclass(frozen=True, slots=True)
class ImageArtifact:
    """Reference to an image participating in a preprocessing transformation."""

    uri: str
    checksum_sha256: str
    byte_size: int
    media_type: str
    kind: str
    width: int
    height: int
    dpi: int | None = None
    region_scale: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "checksum_sha256": self.checksum_sha256,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "dpi": self.dpi,
            "region_scale": self.region_scale,
        }


@dataclass(frozen=True, slots=True)
class PreprocessingStepResult:
    name: str
    parameters: dict[str, object]
    image_bytes: bytes
    width: int
    height: int
    mapping_to_source: CoordinateMapping
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "parameters": self.parameters,
            "width": self.width,
            "height": self.height,
            "mapping_to_source": self.mapping_to_source.as_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class InMemoryPreprocessingResult:
    profile: PreprocessingProfile
    image_bytes: bytes
    source_width: int
    source_height: int
    width: int
    height: int
    dpi: int | None
    region_scale: int
    mapping_to_source: CoordinateMapping
    input_quality: ImageQualityMetrics
    steps: tuple[PreprocessingStepResult, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TransformationMetadata:
    id: str
    name: str
    parameters: dict[str, object]
    input_artifact: ImageArtifact
    output_artifact: ImageArtifact
    mapping_to_source: CoordinateMapping
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "parameters": self.parameters,
            "input_artifact": self.input_artifact.as_dict(),
            "output_artifact": self.output_artifact.as_dict(),
            "mapping_to_source": self.mapping_to_source.as_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class PreprocessingResult:
    document_id: str
    page_number: int
    profile_name: str
    input_artifact: ImageArtifact
    final_artifact: ImageArtifact
    transformations: tuple[TransformationMetadata, ...]
    mapping_to_source: CoordinateMapping
    input_quality: ImageQualityMetrics
    output_quality: ImageQualityMetrics
    manifest_uri: str
    dpi: int | None
    region_scale: int
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "page_number": self.page_number,
            "profile_name": self.profile_name,
            "input_artifact": self.input_artifact.as_dict(),
            "final_artifact": self.final_artifact.as_dict(),
            "transformations": [item.as_dict() for item in self.transformations],
            "mapping_to_source": self.mapping_to_source.as_dict(),
            "input_quality": self.input_quality.as_dict(),
            "output_quality": self.output_quality.as_dict(),
            "manifest_uri": self.manifest_uri,
            "dpi": self.dpi,
            "region_scale": self.region_scale,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class TinyTextRecoveryResult:
    decision: TinyTextDecision
    variants: tuple[PreprocessingResult, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.as_dict(),
            "variants": [variant.as_dict() for variant in self.variants],
        }


class PreprocessingEngine:
    """Run profiles in memory while retaining every intermediate output."""

    def __init__(self, settings: Settings, *, analyzer: ImageQualityAnalyzer | None = None) -> None:
        self.settings = settings
        self.analyzer = analyzer or ImageQualityAnalyzer()

    def run(
        self,
        image_bytes: bytes,
        *,
        profile_name: str | None = None,
        crop_bbox: tuple[float, float, float, float] | None = None,
        region_scale: int = 1,
        dpi: int | None = None,
        page_reference_size: tuple[float, float] | None = None,
        source_coordinate_space: str = "rendered_pixel",
        page_coordinate_space: str = "rendered_pixel",
        max_output_pixels: int | None = None,
        input_quality: ImageQualityMetrics | None = None,
    ) -> InMemoryPreprocessingResult:
        profile = get_profile(
            profile_name or self.settings.default_preprocessing_profile,
            enabled=self.settings.preprocessing_profiles,
        )
        if not 1 <= region_scale <= self.settings.max_region_scale:
            raise InvalidDocumentError("region scale exceeds configured limit")
        try:
            from PIL import Image

            with Image.open(BytesIO(image_bytes)) as opened:
                if opened.width * opened.height > self.settings.max_render_pixels:
                    raise InvalidDocumentError("preprocessing input exceeds configured pixel limit")
                opened.load()
                image = opened.convert("RGB").copy()
        except InvalidDocumentError:
            raise
        except Exception as exc:
            raise InvalidDocumentError("preprocessing image could not be decoded") from exc
        source_width, source_height = image.size
        output_limit = max_output_pixels or (
            self.settings.max_crop_pixels
            if crop_bbox is not None
            else self.settings.max_render_pixels
        )
        quality = input_quality or self.analyzer.analyze(image)
        cumulative = CoordinateMapping.identity(
            source_width,
            source_height,
            page_reference_size=page_reference_size,
            source_coordinate_space=source_coordinate_space,
            page_coordinate_space=page_coordinate_space,
        )
        steps: list[PreprocessingStepResult] = []
        current = image
        if crop_bbox is not None:
            current, cumulative = self._apply(
                current,
                cumulative,
                steps,
                "crop",
                {"bbox": list(crop_bbox)},
                quality=quality,
                max_output_pixels=output_limit,
            )
        if region_scale > 1:
            current, cumulative = self._apply(
                current,
                cumulative,
                steps,
                "scale",
                {"scale": region_scale},
                quality=quality,
                max_output_pixels=output_limit,
            )
        for profile_step in profile.steps:
            current, cumulative = self._apply(
                current,
                cumulative,
                steps,
                profile_step.operation.value,
                profile_step.parameter_dict(),
                quality=quality,
                max_output_pixels=output_limit,
            )
        output_bytes = _encode_png(current)
        warnings = tuple(flag for step in steps for flag in step.warnings)
        return InMemoryPreprocessingResult(
            profile=profile,
            image_bytes=output_bytes,
            source_width=source_width,
            source_height=source_height,
            width=current.width,
            height=current.height,
            dpi=dpi,
            region_scale=region_scale,
            mapping_to_source=cumulative,
            input_quality=quality,
            steps=tuple(steps),
            warnings=warnings,
        )

    @staticmethod
    def _apply(
        current: Any,
        cumulative: CoordinateMapping,
        steps: list[PreprocessingStepResult],
        name: str,
        parameters: dict[str, object],
        *,
        quality: ImageQualityMetrics,
        max_output_pixels: int,
    ) -> tuple[Any, CoordinateMapping]:
        applied: AppliedOperation = apply_operation(
            current,
            name,
            parameters=parameters,
            quality=quality,
            max_output_pixels=max_output_pixels,
        )
        next_mapping = cumulative.compose(applied.mapping)
        steps.append(
            PreprocessingStepResult(
                name=applied.operation.value,
                parameters=applied.parameters,
                image_bytes=_encode_png(applied.image),
                width=applied.image.width,
                height=applied.image.height,
                mapping_to_source=next_mapping,
                warnings=applied.warnings,
            )
        )
        return applied.image, next_mapping


class PreprocessingService:
    """Persist immutable outputs and transformation metadata through a store."""

    def __init__(
        self,
        settings: Settings,
        *,
        artifact_store: ArtifactStore | None = None,
        layout: ArtifactLayout | None = None,
        engine: PreprocessingEngine | None = None,
        analyzer: ImageQualityAnalyzer | None = None,
    ) -> None:
        self.settings = settings
        self.store = artifact_store or LocalArtifactStore(settings.storage_root)
        self.layout = layout or ArtifactLayout()
        self.analyzer = analyzer or ImageQualityAnalyzer()
        self.engine = engine or PreprocessingEngine(settings, analyzer=self.analyzer)

    def preprocess(
        self,
        document_id: str,
        page_number: int,
        image_bytes: bytes,
        *,
        input_artifact_uri: str = "memory://input",
        input_artifact_checksum: str | None = None,
        input_artifact_kind: str = "page_render",
        input_media_type: str = "image/png",
        profile_name: str | None = None,
        crop_bbox: tuple[float, float, float, float] | None = None,
        region_scale: int = 1,
        dpi: int | None = None,
        page_reference_size: tuple[float, float] | None = None,
        source_coordinate_space: str = "rendered_pixel",
        page_coordinate_space: str = "rendered_pixel",
        max_output_pixels: int | None = None,
    ) -> PreprocessingResult:
        if page_number <= 0:
            raise InvalidDocumentError("page number must be positive")
        if not input_artifact_uri:
            raise InvalidDocumentError("input artifact URI must be provided")
        in_memory = self.engine.run(
            image_bytes,
            profile_name=profile_name,
            crop_bbox=crop_bbox,
            region_scale=region_scale,
            dpi=dpi,
            page_reference_size=page_reference_size,
            source_coordinate_space=source_coordinate_space,
            page_coordinate_space=page_coordinate_space,
            max_output_pixels=max_output_pixels,
        )
        selected_profile = in_memory.profile.name
        input_artifact = ImageArtifact(
            uri=input_artifact_uri,
            checksum_sha256=_validated_checksum(image_bytes, input_artifact_checksum),
            byte_size=len(image_bytes),
            media_type=input_media_type,
            kind=input_artifact_kind,
            width=in_memory.source_width,
            height=in_memory.source_height,
            dpi=dpi,
            region_scale=1,
        )
        transformations: list[TransformationMetadata] = []
        previous = input_artifact
        for index, step in enumerate(in_memory.steps, start=1):
            artifact_name = self.layout.page_preprocessing_name(
                page_number,
                f"{selected_profile}",
                index,
                step.name,
                region_scale=region_scale,
            )
            stored = self._put_immutable(document_id, artifact_name, step.image_bytes)
            output = ImageArtifact(
                uri=stored.uri,
                checksum_sha256=stored.checksum_sha256,
                byte_size=stored.byte_size,
                media_type="image/png",
                kind="preprocessed_image",
                width=step.width,
                height=step.height,
                dpi=dpi,
                region_scale=region_scale,
            )
            transformations.append(
                TransformationMetadata(
                    id=(
                        f"{document_id}-page-{page_number:04d}-"
                        f"{selected_profile}-{region_scale}x-{index:02d}"
                    ),
                    name=step.name,
                    parameters=step.parameters,
                    input_artifact=previous,
                    output_artifact=output,
                    mapping_to_source=step.mapping_to_source,
                    warnings=step.warnings,
                )
            )
            previous = output
        if not transformations:
            raise InvalidDocumentError("preprocessing profile produced no transformations")
        final_artifact = transformations[-1].output_artifact
        output_quality = self.analyzer.analyze(in_memory.image_bytes)
        warnings = tuple(dict.fromkeys(in_memory.warnings))
        manifest_payload = {
            "schema_version": self.settings.schema_version,
            "pipeline_version": self.settings.pipeline_version,
            "configuration_hash": self.settings.configuration_hash,
            "document_id": document_id,
            "page_number": page_number,
            "profile": in_memory.profile.as_dict(),
            "input_artifact": input_artifact.as_dict(),
            "final_artifact": final_artifact.as_dict(),
            "transformations": [item.as_dict() for item in transformations],
            "mapping_to_source": in_memory.mapping_to_source.as_dict(),
            "input_quality": in_memory.input_quality.as_dict(),
            "output_quality": output_quality.as_dict(),
            "dpi": dpi,
            "region_scale": region_scale,
            "warnings": list(warnings),
        }
        manifest_name = self.layout.page_preprocessing_manifest_name(
            page_number, selected_profile, region_scale=region_scale
        )
        manifest_bytes = json.dumps(
            manifest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        manifest = self._put_immutable(document_id, manifest_name, manifest_bytes)
        return PreprocessingResult(
            document_id=document_id,
            page_number=page_number,
            profile_name=selected_profile,
            input_artifact=input_artifact,
            final_artifact=final_artifact,
            transformations=tuple(transformations),
            mapping_to_source=in_memory.mapping_to_source,
            input_quality=in_memory.input_quality,
            output_quality=output_quality,
            manifest_uri=manifest.uri,
            dpi=dpi,
            region_scale=region_scale,
            warnings=warnings,
        )

    def recover_tiny_text(
        self,
        document_id: str,
        page_number: int,
        image_bytes: bytes,
        *,
        region_bbox: tuple[float, float, float, float],
        input_artifact_uri: str = "memory://input",
        input_artifact_checksum: str | None = None,
        current_dpi: int | None = None,
        estimated_line_height_px: float | None = None,
        detector_box_height_px: float | None = None,
        first_pass_failed: bool = False,
        text_dense_region: bool = False,
        page_reference_size: tuple[float, float] | None = None,
        source_coordinate_space: str = "rendered_pixel",
        page_coordinate_space: str = "rendered_pixel",
    ) -> TinyTextRecoveryResult:
        metrics = self.analyzer.analyze(image_bytes)
        planner = TinyTextPlanner(
            pixel_height_threshold=self.settings.tiny_text_pixel_height_threshold,
            max_region_scale=self.settings.max_region_scale,
        )
        decision = planner.detect(
            estimated_line_height_px=(
                estimated_line_height_px
                if estimated_line_height_px is not None
                else metrics.estimated_text_scale
            ),
            detector_box_height_px=detector_box_height_px,
            first_pass_failed=first_pass_failed,
            text_dense_region=text_dense_region,
            current_dpi=current_dpi or self.settings.default_dpi,
            high_quality_dpi=self.settings.high_quality_dpi,
            tiny_text_dpi=self.settings.tiny_text_dpi,
            region_scales=self.settings.region_scale_candidates,
        )
        if not decision.is_tiny:
            return TinyTextRecoveryResult(decision=decision, variants=())
        variants: list[PreprocessingResult] = []
        for scale in decision.region_scales[: self.settings.max_preprocessing_variants]:
            variants.append(
                self.preprocess(
                    document_id,
                    page_number,
                    image_bytes,
                    input_artifact_uri=input_artifact_uri,
                    input_artifact_checksum=input_artifact_checksum,
                    profile_name="tiny_text",
                    crop_bbox=region_bbox,
                    region_scale=scale,
                    dpi=decision.recommended_dpi,
                    page_reference_size=page_reference_size,
                    source_coordinate_space=source_coordinate_space,
                    page_coordinate_space=page_coordinate_space,
                    max_output_pixels=self.settings.max_crop_pixels,
                )
            )
        return TinyTextRecoveryResult(decision=decision, variants=tuple(variants))

    def _put_immutable(self, document_id: str, artifact_name: str, data: bytes):
        try:
            return self.store.put_bytes(document_id, artifact_name, data)
        except ArtifactStorageError as exc:
            if self.store.exists(document_id, artifact_name):
                existing = self.store.get(document_id, artifact_name)
                if existing.checksum_sha256 == hashlib.sha256(data).hexdigest():
                    return existing
                raise StorageFailureError(
                    "derived artifact path already contains different bytes"
                ) from exc
            raise StorageFailureError("derived artifact could not be stored") from exc


def _encode_png(image: Any) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _validated_checksum(image_bytes: bytes, supplied: str | None) -> str:
    calculated = hashlib.sha256(image_bytes).hexdigest()
    if supplied is not None and supplied != calculated:
        raise InvalidDocumentError("input artifact checksum does not match image bytes")
    return calculated
