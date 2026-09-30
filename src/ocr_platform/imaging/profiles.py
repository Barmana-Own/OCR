"""Named, provider-neutral preprocessing profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ocr_platform.errors import InvalidDocumentError


class PreprocessingOperation(StrEnum):
    CROP = "crop"
    SCALE = "scale"
    GRAYSCALE = "grayscale"
    CONTRAST_ENHANCEMENT = "contrast_enhancement"
    CLAHE = "clahe"
    MILD_DENOISE = "mild_denoise"
    DESKEW = "deskew"
    PERSPECTIVE_CORRECTION = "perspective_correction"
    BACKGROUND_NORMALIZATION = "background_normalization"
    SHADOW_REDUCTION = "shadow_reduction"
    ADAPTIVE_THRESHOLD = "adaptive_threshold"
    GLOBAL_THRESHOLD = "global_threshold"
    SAFE_SHARPEN = "safe_sharpen"
    BORDER_CLEANUP = "border_cleanup"
    DEWARPING_HOOK = "dewarping_hook"


@dataclass(frozen=True, slots=True)
class PreprocessingStep:
    operation: PreprocessingOperation
    parameters: tuple[tuple[str, object], ...] = ()

    def parameter_dict(self) -> dict[str, object]:
        return dict(self.parameters)

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation.value,
            "parameters": self.parameter_dict(),
        }


@dataclass(frozen=True, slots=True)
class PreprocessingProfile:
    name: str
    steps: tuple[PreprocessingStep, ...]
    description: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [step.as_dict() for step in self.steps],
        }


def _step(operation: PreprocessingOperation, **parameters: object) -> PreprocessingStep:
    return PreprocessingStep(operation, tuple(sorted(parameters.items())))


def builtin_profiles() -> dict[str, PreprocessingProfile]:
    """Return fresh built-in profiles so callers cannot mutate shared state."""

    return {
        "clean_print": PreprocessingProfile(
            name="clean_print",
            description="Conservative cleanup for clear printed pages.",
            steps=(
                _step(PreprocessingOperation.GRAYSCALE),
                _step(PreprocessingOperation.CONTRAST_ENHANCEMENT, factor=1.08),
                _step(PreprocessingOperation.MILD_DENOISE, radius=0.4),
                _step(PreprocessingOperation.SAFE_SHARPEN, radius=1.0, percent=80, threshold=3),
            ),
        ),
        "mobile_photo": PreprocessingProfile(
            name="mobile_photo",
            description="Illumination and skew cleanup for camera captures.",
            steps=(
                _step(PreprocessingOperation.GRAYSCALE),
                _step(PreprocessingOperation.BACKGROUND_NORMALIZATION, radius=21, strength=0.35),
                _step(PreprocessingOperation.SHADOW_REDUCTION, radius=31, strength=0.25),
                _step(PreprocessingOperation.CONTRAST_ENHANCEMENT, factor=1.08),
                _step(PreprocessingOperation.DESKEW, max_angle=8.0),
                _step(PreprocessingOperation.PERSPECTIVE_CORRECTION),
            ),
        ),
        "low_contrast": PreprocessingProfile(
            name="low_contrast",
            description="Local contrast and thresholding for faint scans.",
            steps=(
                _step(PreprocessingOperation.GRAYSCALE),
                _step(PreprocessingOperation.CLAHE, clip_limit=1.5, tile_size=8),
                _step(PreprocessingOperation.BACKGROUND_NORMALIZATION, radius=17, strength=0.25),
                _step(PreprocessingOperation.ADAPTIVE_THRESHOLD, block_size=31, offset=8),
            ),
        ),
        "tiny_text": PreprocessingProfile(
            name="tiny_text",
            description="Conservative high-frequency preservation for small text crops.",
            steps=(
                _step(PreprocessingOperation.GRAYSCALE),
                _step(PreprocessingOperation.CONTRAST_ENHANCEMENT, factor=1.12),
                _step(PreprocessingOperation.SAFE_SHARPEN, radius=1.0, percent=100, threshold=3),
            ),
        ),
        "handwriting": PreprocessingProfile(
            name="handwriting",
            description="Low-aggression cleanup that preserves strokes and joins.",
            steps=(
                _step(PreprocessingOperation.GRAYSCALE),
                _step(PreprocessingOperation.CONTRAST_ENHANCEMENT, factor=1.05),
                _step(PreprocessingOperation.MILD_DENOISE, radius=0.35),
                _step(PreprocessingOperation.BACKGROUND_NORMALIZATION, radius=21, strength=0.20),
            ),
        ),
        "binary_scan": PreprocessingProfile(
            name="binary_scan",
            description="Border cleanup and adaptive binarization for clean scans.",
            steps=(
                _step(PreprocessingOperation.GRAYSCALE),
                _step(PreprocessingOperation.BORDER_CLEANUP, pixels=2),
                _step(PreprocessingOperation.ADAPTIVE_THRESHOLD, block_size=31, offset=6),
            ),
        ),
    }


def get_profile(name: str, *, enabled: tuple[str, ...] | None = None) -> PreprocessingProfile:
    if not name:
        raise InvalidDocumentError("preprocessing profile must be named")
    if enabled is not None and name not in enabled:
        raise InvalidDocumentError(f"preprocessing profile is disabled: {name}")
    profile = builtin_profiles().get(name)
    if profile is None:
        raise InvalidDocumentError(f"unknown preprocessing profile: {name}")
    return profile


def builtin_profile_names() -> tuple[str, ...]:
    return tuple(builtin_profiles())
