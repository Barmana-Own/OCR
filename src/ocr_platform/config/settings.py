"""Validated environment-backed configuration with safe production defaults."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from ocr_platform.errors import ConfigurationError
from ocr_platform.governance import RetentionPolicy
from ocr_platform.normalization import (
    DigitPolicy,
    LineBreakPolicy,
    NormalizationConfig,
    UnicodeNormalizationForm,
    WhitespacePolicy,
    ZeroWidthPolicy,
)
from ocr_platform.utils.hashes import stable_hash

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PAGES = 500
DEFAULT_MAX_RENDER_PIXELS = 50_000_000
DEFAULT_MAX_CROP_PIXELS = 12_000_000
DEFAULT_MAX_PAGE_WIDTH = 50_000
DEFAULT_MAX_PAGE_HEIGHT = 50_000
DEFAULT_DEFAULT_DPI = 300
DEFAULT_HIGH_QUALITY_DPI = 450
DEFAULT_TINY_TEXT_DPI = 600
DEFAULT_REGION_SCALE_CANDIDATES = (2, 3, 4)
DEFAULT_MAX_REGION_SCALE = 4
DEFAULT_MAX_RETRIES = 2
DEFAULT_WORKER_COUNT = 2
DEFAULT_MAX_QUEUED_JOBS = 100
DEFAULT_DEVICE = "auto"
DEFAULT_MODEL_LOAD_MODE = "lazy"
DEFAULT_GPU_INFERENCE_CONCURRENCY = 1
DEFAULT_MAX_PAGES_IN_FLIGHT = 1
DEFAULT_MODE_MAX_RETRIES = (
    ("fast", 0),
    ("balanced", DEFAULT_MAX_RETRIES),
    ("accurate", max(DEFAULT_MAX_RETRIES + 1, 3)),
)
DEFAULT_CONFIDENCE_THRESHOLD = 0.85
DEFAULT_VERIFICATION_THRESHOLD = 0.92
DEFAULT_VERIFICATION_MAX_CANDIDATES = 6
DEFAULT_VERIFICATION_MIN_CONSENSUS_CANDIDATES = 2
DEFAULT_VERIFICATION_REQUIRE_CONSENSUS = True
DEFAULT_VERIFICATION_ALLOW_CONSENSUS_OVERRIDE = True
DEFAULT_VERIFICATION_REQUIRE_INDEPENDENT_CONSENSUS = True
DEFAULT_VERIFICATION_MIN_INDEPENDENT_BACKEND_FAMILIES = 2
DEFAULT_VERIFICATION_MIN_TEXT_LENGTH = 1
DEFAULT_VERIFICATION_MAX_SUSPICIOUS_CHAR_RATE = 0.10
DEFAULT_VERIFICATION_MIN_IMAGE_QUALITY = 0.20
DEFAULT_VERIFICATION_ENABLE_HIGH_QUALITY_RETRY = True
DEFAULT_MODE_HIGH_QUALITY_RETRY = (
    ("fast", False),
    ("balanced", DEFAULT_VERIFICATION_ENABLE_HIGH_QUALITY_RETRY),
    ("accurate", True),
)
DEFAULT_BACKEND_CONFIDENCE_THRESHOLDS: tuple[tuple[str, float], ...] = ()
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 300
DEFAULT_ARTIFACT_BUCKET = "ocr-artifacts"
DEFAULT_ARTIFACT_STORE_BACKEND = "local"
DEFAULT_METADATA_BACKEND = "file"
DEFAULT_QUEUE_BACKEND = "local"
DEFAULT_S3_PREFIX = "ocr"
DEFAULT_POSTGRES_SCHEMA = "public"
DEFAULT_REDIS_QUEUE_NAME = "ocr:jobs"
DEFAULT_OCR_BACKENDS = ("tesseract",)
DEFAULT_OCR_LANGUAGES = ("fas", "eng")
DEFAULT_OCR_BACKEND_TIMEOUT_SECONDS = 120
DEFAULT_LAYOUT_BACKEND = "heuristic"
DEFAULT_LAYOUT_MAX_PIXELS = 4_000_000
DEFAULT_LAYOUT_MAX_REGIONS = 512
DEFAULT_LAYOUT_MIN_CONFIDENCE = 0.35
DEFAULT_HANDWRITING_BACKEND = "unavailable"
DEFAULT_HANDWRITING_MODEL_PATH = Path("var/models/htr")
DEFAULT_TABLE_BACKEND = "unavailable"
DEFAULT_TEXT_CONTENT_TYPES = (
    "text/plain",
    "text/csv",
    "application/json",
    "text/html",
)
DEFAULT_NATIVE_TEXT_MIN_CHARACTERS = 5
DEFAULT_NATIVE_TEXT_MIN_COVERAGE = 0.00001
DEFAULT_NATIVE_TEXT_MAX_SUSPICIOUS_RATIO = 0.20
DEFAULT_NATIVE_TEXT_MIN_PLAUSIBILITY = 0.50
DEFAULT_TINY_TEXT_LINE_HEIGHT_POINTS = 7.0
DEFAULT_TINY_TEXT_PIXEL_HEIGHT_THRESHOLD = 12.0
DEFAULT_PREPROCESSING_PROFILES = (
    "clean_print",
    "mobile_photo",
    "low_contrast",
    "tiny_text",
    "handwriting",
    "binary_scan",
)
DEFAULT_PREPROCESSING_PROFILE = "clean_print"
DEFAULT_MAX_PREPROCESSING_VARIANTS = 8
DEFAULT_RETENTION_TEMPORARY_SECONDS = 86_400
DEFAULT_RETENTION_SOURCE_SECONDS = 30 * 86_400
DEFAULT_RETENTION_DERIVED_SECONDS = 30 * 86_400
DEFAULT_RETENTION_VERIFIED_DATASET_SECONDS = 365 * 86_400
DEFAULT_EXPORT_STAGING_WORKSPACE = Path("var/tmp/exports")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_int_tuple(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    values: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError as exc:
            raise ConfigurationError(f"{name} must contain comma-separated integers") from exc
    return tuple(values)


def _env_mode_ints(
    name: str, default: tuple[tuple[str, int], ...]
) -> tuple[tuple[str, int], ...]:
    value = os.getenv(name)
    if value is None:
        return default
    entries: list[tuple[str, int]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        mode, separator, raw_value = item.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", mode.strip()):
            raise ConfigurationError(f"{name} must contain mode:value entries")
        try:
            parsed = int(raw_value.strip())
        except ValueError as exc:
            raise ConfigurationError(f"{name} values must be integers") from exc
        entries.append((mode.strip(), parsed))
    return tuple(entries)


def _env_mode_bools(
    name: str, default: tuple[tuple[str, bool], ...]
) -> tuple[tuple[str, bool], ...]:
    value = os.getenv(name)
    if value is None:
        return default
    entries: list[tuple[str, bool]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        mode, separator, raw_value = item.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", mode.strip()):
            raise ConfigurationError(f"{name} must contain mode:boolean entries")
        normalized = raw_value.strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ConfigurationError(f"{name} values must be booleans")
        entries.append((mode.strip(), normalized in {"true", "1", "yes", "on"}))
    return tuple(entries)


def _env_thresholds(
    name: str, default: tuple[tuple[str, float], ...]
) -> tuple[tuple[str, float], ...]:
    value = os.getenv(name)
    if value is None:
        return default
    thresholds: list[tuple[str, float]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        backend, separator, raw_threshold = item.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", backend.strip()):
            raise ConfigurationError(f"{name} must contain backend:threshold entries")
        try:
            threshold = float(raw_threshold.strip())
        except ValueError as exc:
            raise ConfigurationError(f"{name} thresholds must be numbers") from exc
        thresholds.append((backend.strip(), threshold))
    return tuple(thresholds)


def _normalization_from_env() -> NormalizationConfig:
    try:
            return NormalizationConfig(
                policy_version=os.getenv("OCR_NORMALIZATION_POLICY_VERSION", "1.0.0").strip(),
                unicode_form=UnicodeNormalizationForm(
                    os.getenv("OCR_NORMALIZATION_UNICODE_FORM", "NFC").strip().upper()
                ),
            normalize_character_variants=_env_bool(
                "OCR_NORMALIZATION_CHARACTER_VARIANTS", True
            ),
            digit_policy=DigitPolicy(
                os.getenv("OCR_NORMALIZATION_DIGIT_POLICY", "persian").strip().lower()
            ),
            remove_tatweel=_env_bool("OCR_NORMALIZATION_REMOVE_TATWEEL", False),
            whitespace_policy=WhitespacePolicy(
                os.getenv("OCR_NORMALIZATION_WHITESPACE_POLICY", "trim").strip().lower()
            ),
            line_break_policy=LineBreakPolicy(
                os.getenv("OCR_NORMALIZATION_LINE_BREAK_POLICY", "preserve").strip().lower()
            ),
            zero_width_policy=ZeroWidthPolicy(
                os.getenv("OCR_NORMALIZATION_ZERO_WIDTH_POLICY", "preserve").strip().lower()
            ),
            trim_line_edges=_env_bool("OCR_NORMALIZATION_TRIM_LINE_EDGES", True),
        )
    except ValueError as exc:
        message = str(exc)
        field_hint = next(
            (
                label
                for enum_name, label in (
                    ("DigitPolicy", "digit policy"),
                    ("UnicodeNormalizationForm", "Unicode normalization form"),
                    ("WhitespacePolicy", "whitespace policy"),
                    ("LineBreakPolicy", "line-break policy"),
                    ("ZeroWidthPolicy", "zero-width policy"),
                )
                if enum_name in message
            ),
            "normalization policy",
        )
        raise ConfigurationError(
            f"normalization configuration is invalid for {field_hint}: {message}"
        ) from exc


def _retention_policy_from_env() -> RetentionPolicy:
    try:
        return RetentionPolicy(
            temporary_seconds=_env_int(
                "OCR_RETENTION_TEMPORARY_SECONDS", DEFAULT_RETENTION_TEMPORARY_SECONDS
            ),
            source_seconds=_env_int(
                "OCR_RETENTION_SOURCE_SECONDS", DEFAULT_RETENTION_SOURCE_SECONDS
            ),
            derived_seconds=_env_int(
                "OCR_RETENTION_DERIVED_SECONDS", DEFAULT_RETENTION_DERIVED_SECONDS
            ),
            verified_dataset_seconds=_env_int(
                "OCR_RETENTION_VERIFIED_DATASET_SECONDS",
                DEFAULT_RETENTION_VERIFIED_DATASET_SECONDS,
            ),
        )
    except ValidationError as exc:
        raise ConfigurationError("retention windows must be positive integers") from exc


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    pipeline_version: str = "0.1.0"
    schema_version: str = "1.0.0"
    storage_root: Path = Path("var/artifacts")
    temporary_workspace: Path = Path("var/tmp")
    export_staging_workspace: Path = DEFAULT_EXPORT_STAGING_WORKSPACE
    model_path: Path = Path("var/models")
    cache_path: Path = Path("var/cache")
    artifact_bucket: str = DEFAULT_ARTIFACT_BUCKET
    artifact_store_backend: str = DEFAULT_ARTIFACT_STORE_BACKEND
    s3_endpoint_url: str | None = None
    s3_prefix: str = DEFAULT_S3_PREFIX
    metadata_backend: str = DEFAULT_METADATA_BACKEND
    postgres_dsn: str | None = None
    postgres_schema: str = DEFAULT_POSTGRES_SCHEMA
    queue_backend: str = DEFAULT_QUEUE_BACKEND
    redis_url: str | None = None
    redis_queue_name: str = DEFAULT_REDIS_QUEUE_NAME
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_pages: int = DEFAULT_MAX_PAGES
    max_render_pixels: int = DEFAULT_MAX_RENDER_PIXELS
    max_crop_pixels: int = DEFAULT_MAX_CROP_PIXELS
    max_page_width: int = DEFAULT_MAX_PAGE_WIDTH
    max_page_height: int = DEFAULT_MAX_PAGE_HEIGHT
    default_dpi: int = DEFAULT_DEFAULT_DPI
    high_quality_dpi: int = DEFAULT_HIGH_QUALITY_DPI
    tiny_text_dpi: int = DEFAULT_TINY_TEXT_DPI
    region_scale_candidates: tuple[int, ...] = DEFAULT_REGION_SCALE_CANDIDATES
    max_region_scale: int = DEFAULT_MAX_REGION_SCALE
    max_retries: int = DEFAULT_MAX_RETRIES
    worker_count: int = DEFAULT_WORKER_COUNT
    max_queued_jobs: int = DEFAULT_MAX_QUEUED_JOBS
    device: str = DEFAULT_DEVICE
    model_load_mode: str = DEFAULT_MODEL_LOAD_MODE
    gpu_inference_concurrency: int = DEFAULT_GPU_INFERENCE_CONCURRENCY
    max_pages_in_flight: int = DEFAULT_MAX_PAGES_IN_FLIGHT
    mode_max_retries: tuple[tuple[str, int], ...] = DEFAULT_MODE_MAX_RETRIES
    mode_enable_high_quality_retry: tuple[tuple[str, bool], ...] = (
        ("fast", False),
        ("balanced", DEFAULT_VERIFICATION_ENABLE_HIGH_QUALITY_RETRY),
        ("accurate", True),
    )
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    verification_threshold: float = DEFAULT_VERIFICATION_THRESHOLD
    verification_max_candidates: int = DEFAULT_VERIFICATION_MAX_CANDIDATES
    verification_min_consensus_candidates: int = DEFAULT_VERIFICATION_MIN_CONSENSUS_CANDIDATES
    verification_require_consensus_for_verified: bool = DEFAULT_VERIFICATION_REQUIRE_CONSENSUS
    verification_allow_consensus_override_low_confidence: bool = (
        DEFAULT_VERIFICATION_ALLOW_CONSENSUS_OVERRIDE
    )
    verification_require_independent_backend_consensus: bool = (
        DEFAULT_VERIFICATION_REQUIRE_INDEPENDENT_CONSENSUS
    )
    verification_min_independent_backend_families: int = (
        DEFAULT_VERIFICATION_MIN_INDEPENDENT_BACKEND_FAMILIES
    )
    verification_min_text_length: int = DEFAULT_VERIFICATION_MIN_TEXT_LENGTH
    verification_max_suspicious_char_rate: float = DEFAULT_VERIFICATION_MAX_SUSPICIOUS_CHAR_RATE
    verification_min_image_quality: float = DEFAULT_VERIFICATION_MIN_IMAGE_QUALITY
    verification_enable_high_quality_retry: bool = DEFAULT_VERIFICATION_ENABLE_HIGH_QUALITY_RETRY
    backend_confidence_thresholds: tuple[tuple[str, float], ...] = (
        DEFAULT_BACKEND_CONFIDENCE_THRESHOLDS
    )
    processing_timeout_seconds: int = DEFAULT_PROCESSING_TIMEOUT_SECONDS
    native_text_min_characters: int = DEFAULT_NATIVE_TEXT_MIN_CHARACTERS
    native_text_min_coverage: float = DEFAULT_NATIVE_TEXT_MIN_COVERAGE
    native_text_max_suspicious_ratio: float = DEFAULT_NATIVE_TEXT_MAX_SUSPICIOUS_RATIO
    native_text_min_plausibility: float = DEFAULT_NATIVE_TEXT_MIN_PLAUSIBILITY
    tiny_text_line_height_points: float = DEFAULT_TINY_TEXT_LINE_HEIGHT_POINTS
    tiny_text_pixel_height_threshold: float = DEFAULT_TINY_TEXT_PIXEL_HEIGHT_THRESHOLD
    preprocessing_profiles: tuple[str, ...] = DEFAULT_PREPROCESSING_PROFILES
    default_preprocessing_profile: str = DEFAULT_PREPROCESSING_PROFILE
    max_preprocessing_variants: int = DEFAULT_MAX_PREPROCESSING_VARIANTS
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    retention_policy: RetentionPolicy = field(default_factory=RetentionPolicy)
    enabled_ocr_backends: tuple[str, ...] = DEFAULT_OCR_BACKENDS
    ocr_languages: tuple[str, ...] = DEFAULT_OCR_LANGUAGES
    ocr_backend_timeout_seconds: int = DEFAULT_OCR_BACKEND_TIMEOUT_SECONDS
    layout_backend: str = DEFAULT_LAYOUT_BACKEND
    layout_max_pixels: int = DEFAULT_LAYOUT_MAX_PIXELS
    layout_max_regions: int = DEFAULT_LAYOUT_MAX_REGIONS
    layout_min_confidence: float = DEFAULT_LAYOUT_MIN_CONFIDENCE
    handwriting_backend: str = DEFAULT_HANDWRITING_BACKEND
    handwriting_model_path: Path = DEFAULT_HANDWRITING_MODEL_PATH
    table_backend: str = DEFAULT_TABLE_BACKEND
    require_auth: bool = False
    allow_sensitive_debug_logging: bool = False
    api_keys: tuple[str, ...] = field(default_factory=tuple)
    allowed_content_types: tuple[str, ...] = (
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        *DEFAULT_TEXT_CONTENT_TYPES,
    )

    def __post_init__(self) -> None:
        if self.environment not in {"development", "test", "staging", "production"}:
            raise ConfigurationError(
                "OCR_ENVIRONMENT must be development, test, staging, or production"
            )
        if not self.pipeline_version or not self.schema_version:
            raise ConfigurationError("pipeline and schema versions must not be empty")
        if not isinstance(self.normalization, NormalizationConfig):
            raise ConfigurationError("normalization must be a NormalizationConfig")
        if not isinstance(self.retention_policy, RetentionPolicy):
            raise ConfigurationError("retention_policy must be a RetentionPolicy")
        if self.max_upload_bytes <= 0 or self.max_pages <= 0:
            raise ConfigurationError("upload and page limits must be positive")
        if (
            self.max_render_pixels <= 0
            or self.max_crop_pixels <= 0
            or self.max_page_width <= 0
            or self.max_page_height <= 0
        ):
            raise ConfigurationError("pixel limits must be positive")
        if self.processing_timeout_seconds <= 0:
            raise ConfigurationError("processing timeout must be positive")
        if self.ocr_backend_timeout_seconds <= 0:
            raise ConfigurationError("OCR backend timeout must be positive")
        if not self.ocr_languages or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", language)
            for language in self.ocr_languages
        ):
            raise ConfigurationError("OCR language names must be safe and non-empty")
        if (
            self.default_dpi <= 0
            or self.high_quality_dpi <= 0
            or self.tiny_text_dpi <= 0
            or self.high_quality_dpi < self.default_dpi
        ):
            raise ConfigurationError("DPI configuration is invalid")
        if self.max_retries < 0:
            raise ConfigurationError("max retries cannot be negative")
        if self.worker_count <= 0 or self.max_queued_jobs <= 0:
            raise ConfigurationError("worker and queued-job limits must be positive")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ConfigurationError("device must be auto, cpu, or cuda")
        if self.model_load_mode not in {"lazy", "startup"}:
            raise ConfigurationError("model load mode must be lazy or startup")
        if self.gpu_inference_concurrency <= 0 or self.max_pages_in_flight <= 0:
            raise ConfigurationError("inference and page concurrency must be positive")
        expected_modes = {"fast", "balanced", "accurate"}
        retry_modes = dict(self.mode_max_retries)
        high_quality_modes = dict(self.mode_enable_high_quality_retry)
        if set(retry_modes) != expected_modes or len(retry_modes) != len(self.mode_max_retries):
            raise ConfigurationError(
                "mode retry policy must define fast, balanced, and accurate once"
            )
        if set(high_quality_modes) != expected_modes or len(high_quality_modes) != len(
            self.mode_enable_high_quality_retry
        ):
            raise ConfigurationError(
                "mode high-quality policy must define fast, balanced, and accurate once"
            )
        if any(value < 0 for value in retry_modes.values()):
            raise ConfigurationError("mode retries cannot be negative")
        if self.tiny_text_dpi < self.high_quality_dpi:
            raise ConfigurationError("tiny-text DPI cannot be below high-quality DPI")
        if not 0 < self.confidence_threshold <= 1:
            raise ConfigurationError("confidence threshold must be between 0 and 1")
        if not 0 < self.verification_threshold <= 1:
            raise ConfigurationError("verification threshold must be between 0 and 1")
        if self.verification_threshold < self.confidence_threshold:
            raise ConfigurationError(
                "verification threshold cannot be below confidence threshold"
            )
        if self.verification_max_candidates <= 0:
            raise ConfigurationError("maximum verification candidates must be positive")
        if self.verification_min_consensus_candidates <= 0:
            raise ConfigurationError("consensus candidates must be positive")
        if self.verification_min_consensus_candidates > self.verification_max_candidates:
            raise ConfigurationError(
                "consensus candidates cannot exceed maximum verification candidates"
            )
        if self.verification_min_independent_backend_families <= 0:
            raise ConfigurationError(
                "minimum independent evidence identities must be positive"
            )
        if self.verification_min_text_length <= 0:
            raise ConfigurationError("minimum verification text length must be positive")
        if not 0 <= self.verification_max_suspicious_char_rate <= 1:
            raise ConfigurationError("verification suspicious ratio must be between 0 and 1")
        if not 0 <= self.verification_min_image_quality <= 1:
            raise ConfigurationError("verification image quality must be between 0 and 1")
        threshold_backends = [backend for backend, _ in self.backend_confidence_thresholds]
        if len(threshold_backends) != len(set(threshold_backends)):
            raise ConfigurationError("backend confidence thresholds must be unique")
        for backend, threshold in self.backend_confidence_thresholds:
            if not backend or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", backend):
                raise ConfigurationError("backend confidence threshold names must be safe")
            if not 0 <= threshold <= 1:
                raise ConfigurationError("backend confidence thresholds must be between 0 and 1")
        if self.native_text_min_characters <= 0:
            raise ConfigurationError("native text minimum characters must be positive")
        if not 0 <= self.native_text_min_coverage <= 1:
            raise ConfigurationError("native text coverage threshold must be between 0 and 1")
        if not 0 <= self.native_text_max_suspicious_ratio <= 1:
            raise ConfigurationError("native text suspicious ratio must be between 0 and 1")
        if not 0 <= self.native_text_min_plausibility <= 1:
            raise ConfigurationError("native text plausibility threshold must be between 0 and 1")
        if self.tiny_text_line_height_points <= 0:
            raise ConfigurationError("tiny text line height must be positive")
        if self.tiny_text_pixel_height_threshold <= 0:
            raise ConfigurationError("tiny text pixel height threshold must be positive")
        if self.layout_max_pixels <= 0 or self.layout_max_regions <= 0:
            raise ConfigurationError("layout resource limits must be positive")
        if not 0 <= self.layout_min_confidence <= 1:
            raise ConfigurationError("layout confidence threshold must be between 0 and 1")
        if not self.preprocessing_profiles:
            raise ConfigurationError("at least one preprocessing profile is required")
        if any(
            not profile or re.search(r"[\\/\x00-\x1f]", profile)
            for profile in self.preprocessing_profiles
        ):
            raise ConfigurationError("preprocessing profile names must be safe and non-empty")
        if self.default_preprocessing_profile not in self.preprocessing_profiles:
            raise ConfigurationError("default preprocessing profile must be enabled")
        if self.max_preprocessing_variants <= 0:
            raise ConfigurationError("maximum preprocessing variants must be positive")
        if not 1 <= self.max_region_scale <= 4:
            raise ConfigurationError("region scale must be between 1 and 4")
        if not self.region_scale_candidates:
            raise ConfigurationError("at least one region scale candidate is required")
        if tuple(sorted(set(self.region_scale_candidates))) != self.region_scale_candidates:
            raise ConfigurationError("region scale candidates must be sorted and unique")
        if any(
            scale < 2 or scale > self.max_region_scale
            for scale in self.region_scale_candidates
        ):
            raise ConfigurationError(
                "region scale candidates must be between 2 and max region scale"
            )
        if not self.artifact_bucket or re.search(r"[\\/\x00-\x1f]", self.artifact_bucket):
            raise ConfigurationError("artifact bucket must be a safe non-empty name")
        if self.artifact_store_backend not in {"local", "s3"}:
            raise ConfigurationError("artifact store backend must be local or s3")
        if self.metadata_backend not in {"file", "postgres"}:
            raise ConfigurationError("metadata backend must be file or postgres")
        if self.queue_backend not in {"local", "redis"}:
            raise ConfigurationError("queue backend must be local or redis")
        if self.metadata_backend == "postgres" and not (self.postgres_dsn or "").strip():
            raise ConfigurationError("PostgreSQL metadata backend requires OCR_POSTGRES_DSN")
        if self.queue_backend == "redis" and not (self.redis_url or "").strip():
            raise ConfigurationError("Redis queue backend requires OCR_REDIS_URL")
        if not self.s3_prefix or any(
            not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", part)
            for part in self.s3_prefix.replace("\\", "/").split("/")
        ):
            raise ConfigurationError("S3 prefix must contain safe path components")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.postgres_schema):
            raise ConfigurationError("PostgreSQL schema name is unsafe")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", self.redis_queue_name):
            raise ConfigurationError("Redis queue name is unsafe")
        backend_values = (
            *self.enabled_ocr_backends,
            self.layout_backend,
            self.handwriting_backend,
            self.table_backend,
        )
        if any(
            not backend or re.search(r"[\x00-\x1f]", backend) for backend in backend_values
        ):
            raise ConfigurationError(
                "backend names must be non-empty and contain no control characters"
            )
        if self.environment in {"staging", "production"} and not self.require_auth:
            raise ConfigurationError("staging and production require OCR_REQUIRE_AUTH=true")
        if self.environment in {"staging", "production"} and not self.api_keys:
            raise ConfigurationError("staging and production authentication requires OCR_API_KEYS")
        if self.environment in {"staging", "production"} and self.allow_sensitive_debug_logging:
            raise ConfigurationError(
                "sensitive debug logging is allowed only in development or test"
            )

    @property
    def configuration_payload(self) -> dict[str, object]:
        """Return the reproducibility payload without secrets or machine paths."""

        return {
            "environment": self.environment,
            "pipeline_version": self.pipeline_version,
            "schema_version": self.schema_version,
            "artifact_store_backend": self.artifact_store_backend,
            "artifact_bucket": self.artifact_bucket,
            "s3_prefix": self.s3_prefix,
            "metadata_backend": self.metadata_backend,
            "postgres_schema": self.postgres_schema,
            "queue_backend": self.queue_backend,
            "redis_queue_name": self.redis_queue_name,
            "max_upload_bytes": self.max_upload_bytes,
            "max_pages": self.max_pages,
            "max_render_pixels": self.max_render_pixels,
            "max_crop_pixels": self.max_crop_pixels,
            "max_page_width": self.max_page_width,
            "max_page_height": self.max_page_height,
            "default_dpi": self.default_dpi,
            "high_quality_dpi": self.high_quality_dpi,
            "tiny_text_dpi": self.tiny_text_dpi,
            "region_scale_candidates": self.region_scale_candidates,
            "max_region_scale": self.max_region_scale,
            "max_retries": self.max_retries,
            "device": self.device,
            "model_load_mode": self.model_load_mode,
            "gpu_inference_concurrency": self.gpu_inference_concurrency,
            "max_pages_in_flight": self.max_pages_in_flight,
            "mode_max_retries": self.mode_max_retries,
            "mode_enable_high_quality_retry": self.mode_enable_high_quality_retry,
            "confidence_threshold": self.confidence_threshold,
            "verification_threshold": self.verification_threshold,
            "verification_max_candidates": self.verification_max_candidates,
            "verification_min_consensus_candidates": self.verification_min_consensus_candidates,
            "verification_require_consensus_for_verified": (
                self.verification_require_consensus_for_verified
            ),
            "verification_allow_consensus_override_low_confidence": (
                self.verification_allow_consensus_override_low_confidence
            ),
            "verification_require_independent_backend_consensus": (
                self.verification_require_independent_backend_consensus
            ),
            "verification_min_independent_backend_families": (
                self.verification_min_independent_backend_families
            ),
            "verification_min_text_length": self.verification_min_text_length,
            "verification_max_suspicious_char_rate": self.verification_max_suspicious_char_rate,
            "verification_min_image_quality": self.verification_min_image_quality,
            "verification_enable_high_quality_retry": self.verification_enable_high_quality_retry,
            "backend_confidence_thresholds": self.backend_confidence_thresholds,
            "processing_timeout_seconds": self.processing_timeout_seconds,
            "native_text_min_characters": self.native_text_min_characters,
            "native_text_min_coverage": self.native_text_min_coverage,
            "native_text_max_suspicious_ratio": self.native_text_max_suspicious_ratio,
            "native_text_min_plausibility": self.native_text_min_plausibility,
            "tiny_text_line_height_points": self.tiny_text_line_height_points,
            "tiny_text_pixel_height_threshold": self.tiny_text_pixel_height_threshold,
            "preprocessing_profiles": self.preprocessing_profiles,
            "default_preprocessing_profile": self.default_preprocessing_profile,
            "max_preprocessing_variants": self.max_preprocessing_variants,
            "normalization": self.normalization.to_payload(),
            "retention_policy": self.retention_policy.to_payload(),
            "enabled_ocr_backends": self.enabled_ocr_backends,
            "ocr_languages": self.ocr_languages,
            "ocr_backend_timeout_seconds": self.ocr_backend_timeout_seconds,
            "layout_backend": self.layout_backend,
            "layout_max_pixels": self.layout_max_pixels,
            "layout_max_regions": self.layout_max_regions,
            "layout_min_confidence": self.layout_min_confidence,
            "handwriting_backend": self.handwriting_backend,
            "handwriting_model_path": str(self.handwriting_model_path),
            "table_backend": self.table_backend,
            "require_auth": self.require_auth,
            "allow_sensitive_debug_logging": self.allow_sensitive_debug_logging,
            "allowed_content_types": self.allowed_content_types,
        }

    @property
    def configuration_hash(self) -> str:
        return stable_hash(self.configuration_payload)

    @classmethod
    def from_env(cls) -> Settings:
        environment = os.getenv("OCR_ENVIRONMENT", "development").strip().lower()
        require_auth_default = environment in {"staging", "production"}
        raw_keys = os.getenv("OCR_API_KEYS", "")
        api_keys = tuple(key.strip() for key in raw_keys.split(";") if key.strip())
        storage_root = Path(os.getenv("OCR_STORAGE_ROOT", "var/artifacts")).resolve()
        return cls(
            environment=environment,
            pipeline_version=os.getenv("OCR_PIPELINE_VERSION", "0.1.0"),
            schema_version=os.getenv("OCR_SCHEMA_VERSION", "1.0.0"),
            storage_root=storage_root,
            temporary_workspace=Path(os.getenv("OCR_TEMPORARY_WORKSPACE", "var/tmp")),
            export_staging_workspace=Path(
                os.getenv("OCR_EXPORT_STAGING_WORKSPACE", str(DEFAULT_EXPORT_STAGING_WORKSPACE))
            ),
            model_path=Path(os.getenv("OCR_MODEL_PATH", "var/models")),
            cache_path=Path(os.getenv("OCR_CACHE_PATH", "var/cache")),
            artifact_bucket=os.getenv("OCR_ARTIFACT_BUCKET", DEFAULT_ARTIFACT_BUCKET).strip(),
            artifact_store_backend=os.getenv(
                "OCR_ARTIFACT_STORE_BACKEND", DEFAULT_ARTIFACT_STORE_BACKEND
            ).strip().lower(),
            s3_endpoint_url=(os.getenv("OCR_S3_ENDPOINT_URL", "").strip() or None),
            s3_prefix=os.getenv("OCR_S3_PREFIX", DEFAULT_S3_PREFIX).strip(),
            metadata_backend=os.getenv(
                "OCR_METADATA_BACKEND", DEFAULT_METADATA_BACKEND
            ).strip().lower(),
            postgres_dsn=(os.getenv("OCR_POSTGRES_DSN", "").strip() or None),
            postgres_schema=os.getenv("OCR_POSTGRES_SCHEMA", DEFAULT_POSTGRES_SCHEMA).strip(),
            queue_backend=os.getenv("OCR_QUEUE_BACKEND", DEFAULT_QUEUE_BACKEND).strip().lower(),
            redis_url=(os.getenv("OCR_REDIS_URL", "").strip() or None),
            redis_queue_name=os.getenv(
                "OCR_REDIS_QUEUE_NAME", DEFAULT_REDIS_QUEUE_NAME
            ).strip(),
            max_upload_bytes=_env_int("OCR_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
            max_pages=_env_int("OCR_MAX_PAGES", DEFAULT_MAX_PAGES),
            max_render_pixels=_env_int("OCR_MAX_RENDER_PIXELS", DEFAULT_MAX_RENDER_PIXELS),
            max_crop_pixels=_env_int("OCR_MAX_CROP_PIXELS", DEFAULT_MAX_CROP_PIXELS),
            max_page_width=_env_int("OCR_MAX_PAGE_WIDTH", DEFAULT_MAX_PAGE_WIDTH),
            max_page_height=_env_int("OCR_MAX_PAGE_HEIGHT", DEFAULT_MAX_PAGE_HEIGHT),
            default_dpi=_env_int("OCR_DEFAULT_DPI", DEFAULT_DEFAULT_DPI),
            high_quality_dpi=_env_int("OCR_HIGH_QUALITY_DPI", DEFAULT_HIGH_QUALITY_DPI),
            tiny_text_dpi=_env_int("OCR_TINY_TEXT_DPI", DEFAULT_TINY_TEXT_DPI),
            region_scale_candidates=_env_int_tuple(
                "OCR_REGION_SCALE_CANDIDATES", DEFAULT_REGION_SCALE_CANDIDATES
            ),
            max_region_scale=_env_int("OCR_MAX_REGION_SCALE", DEFAULT_MAX_REGION_SCALE),
            max_retries=_env_int("OCR_MAX_RETRIES", DEFAULT_MAX_RETRIES),
            worker_count=_env_int("OCR_WORKER_COUNT", DEFAULT_WORKER_COUNT),
            max_queued_jobs=_env_int("OCR_MAX_QUEUED_JOBS", DEFAULT_MAX_QUEUED_JOBS),
            device=os.getenv("OCR_DEVICE", DEFAULT_DEVICE).strip().lower(),
            model_load_mode=os.getenv(
                "OCR_MODEL_LOAD_MODE", DEFAULT_MODEL_LOAD_MODE
            ).strip().lower(),
            gpu_inference_concurrency=_env_int(
                "OCR_GPU_INFERENCE_CONCURRENCY", DEFAULT_GPU_INFERENCE_CONCURRENCY
            ),
            max_pages_in_flight=_env_int(
                "OCR_MAX_PAGES_IN_FLIGHT", DEFAULT_MAX_PAGES_IN_FLIGHT
            ),
            mode_max_retries=_env_mode_ints(
                "OCR_MODE_MAX_RETRIES", DEFAULT_MODE_MAX_RETRIES
            ),
            mode_enable_high_quality_retry=_env_mode_bools(
                "OCR_MODE_HIGH_QUALITY_RETRY", DEFAULT_MODE_HIGH_QUALITY_RETRY
            ),
            confidence_threshold=_env_float(
                "OCR_CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD
            ),
            verification_threshold=_env_float(
                "OCR_VERIFICATION_THRESHOLD", DEFAULT_VERIFICATION_THRESHOLD
            ),
            verification_max_candidates=_env_int(
                "OCR_VERIFICATION_MAX_CANDIDATES", DEFAULT_VERIFICATION_MAX_CANDIDATES
            ),
            verification_min_consensus_candidates=_env_int(
                "OCR_VERIFICATION_MIN_CONSENSUS_CANDIDATES",
                DEFAULT_VERIFICATION_MIN_CONSENSUS_CANDIDATES,
            ),
            verification_require_consensus_for_verified=_env_bool(
                "OCR_VERIFICATION_REQUIRE_CONSENSUS", DEFAULT_VERIFICATION_REQUIRE_CONSENSUS
            ),
            verification_allow_consensus_override_low_confidence=_env_bool(
                "OCR_VERIFICATION_ALLOW_CONSENSUS_OVERRIDE",
                DEFAULT_VERIFICATION_ALLOW_CONSENSUS_OVERRIDE,
            ),
            verification_require_independent_backend_consensus=_env_bool(
                "OCR_VERIFICATION_REQUIRE_INDEPENDENT_CONSENSUS",
                DEFAULT_VERIFICATION_REQUIRE_INDEPENDENT_CONSENSUS,
            ),
            verification_min_independent_backend_families=_env_int(
                "OCR_VERIFICATION_MIN_INDEPENDENT_BACKEND_FAMILIES",
                DEFAULT_VERIFICATION_MIN_INDEPENDENT_BACKEND_FAMILIES,
            ),
            verification_min_text_length=_env_int(
                "OCR_VERIFICATION_MIN_TEXT_LENGTH", DEFAULT_VERIFICATION_MIN_TEXT_LENGTH
            ),
            verification_max_suspicious_char_rate=_env_float(
                "OCR_VERIFICATION_MAX_SUSPICIOUS_CHAR_RATE",
                DEFAULT_VERIFICATION_MAX_SUSPICIOUS_CHAR_RATE,
            ),
            verification_min_image_quality=_env_float(
                "OCR_VERIFICATION_MIN_IMAGE_QUALITY", DEFAULT_VERIFICATION_MIN_IMAGE_QUALITY
            ),
            verification_enable_high_quality_retry=_env_bool(
                "OCR_VERIFICATION_ENABLE_HIGH_QUALITY_RETRY",
                DEFAULT_VERIFICATION_ENABLE_HIGH_QUALITY_RETRY,
            ),
            backend_confidence_thresholds=_env_thresholds(
                "OCR_BACKEND_CONFIDENCE_THRESHOLDS", DEFAULT_BACKEND_CONFIDENCE_THRESHOLDS
            ),
            processing_timeout_seconds=_env_int(
                "OCR_PROCESSING_TIMEOUT_SECONDS", DEFAULT_PROCESSING_TIMEOUT_SECONDS
            ),
            native_text_min_characters=_env_int(
                "OCR_NATIVE_TEXT_MIN_CHARACTERS", DEFAULT_NATIVE_TEXT_MIN_CHARACTERS
            ),
            native_text_min_coverage=_env_float(
                "OCR_NATIVE_TEXT_MIN_COVERAGE", DEFAULT_NATIVE_TEXT_MIN_COVERAGE
            ),
            native_text_max_suspicious_ratio=_env_float(
                "OCR_NATIVE_TEXT_MAX_SUSPICIOUS_RATIO", DEFAULT_NATIVE_TEXT_MAX_SUSPICIOUS_RATIO
            ),
            native_text_min_plausibility=_env_float(
                "OCR_NATIVE_TEXT_MIN_PLAUSIBILITY", DEFAULT_NATIVE_TEXT_MIN_PLAUSIBILITY
            ),
            tiny_text_line_height_points=_env_float(
                "OCR_TINY_TEXT_LINE_HEIGHT_POINTS", DEFAULT_TINY_TEXT_LINE_HEIGHT_POINTS
            ),
            tiny_text_pixel_height_threshold=_env_float(
                "OCR_TINY_TEXT_PIXEL_HEIGHT_THRESHOLD", DEFAULT_TINY_TEXT_PIXEL_HEIGHT_THRESHOLD
            ),
            preprocessing_profiles=_env_csv(
                "OCR_PREPROCESSING_PROFILES", DEFAULT_PREPROCESSING_PROFILES
            ),
            default_preprocessing_profile=os.getenv(
                "OCR_DEFAULT_PREPROCESSING_PROFILE", DEFAULT_PREPROCESSING_PROFILE
            ).strip(),
            max_preprocessing_variants=_env_int(
                "OCR_MAX_PREPROCESSING_VARIANTS", DEFAULT_MAX_PREPROCESSING_VARIANTS
            ),
            normalization=_normalization_from_env(),
            retention_policy=_retention_policy_from_env(),
            enabled_ocr_backends=_env_csv("OCR_ENABLED_OCR_BACKENDS", DEFAULT_OCR_BACKENDS),
            ocr_languages=_env_csv("OCR_LANGUAGES", DEFAULT_OCR_LANGUAGES),
            ocr_backend_timeout_seconds=_env_int(
                "OCR_BACKEND_TIMEOUT_SECONDS", DEFAULT_OCR_BACKEND_TIMEOUT_SECONDS
            ),
            layout_backend=os.getenv("OCR_LAYOUT_BACKEND", DEFAULT_LAYOUT_BACKEND).strip(),
            layout_max_pixels=_env_int("OCR_LAYOUT_MAX_PIXELS", DEFAULT_LAYOUT_MAX_PIXELS),
            layout_max_regions=_env_int("OCR_LAYOUT_MAX_REGIONS", DEFAULT_LAYOUT_MAX_REGIONS),
            layout_min_confidence=_env_float(
                "OCR_LAYOUT_MIN_CONFIDENCE", DEFAULT_LAYOUT_MIN_CONFIDENCE
            ),
            handwriting_backend=os.getenv(
                "OCR_HANDWRITING_BACKEND", DEFAULT_HANDWRITING_BACKEND
            ).strip(),
            handwriting_model_path=Path(
                os.getenv("OCR_HANDWRITING_MODEL_PATH", str(DEFAULT_HANDWRITING_MODEL_PATH))
            ),
            table_backend=os.getenv("OCR_TABLE_BACKEND", DEFAULT_TABLE_BACKEND).strip(),
            require_auth=_env_bool("OCR_REQUIRE_AUTH", require_auth_default),
            allow_sensitive_debug_logging=_env_bool(
                "OCR_ALLOW_SENSITIVE_DEBUG_LOGGING", False
            ),
            api_keys=api_keys,
            allowed_content_types=_env_csv(
                "OCR_ALLOWED_CONTENT_TYPES",
                (
                    "application/pdf",
                    "image/jpeg",
                    "image/png",
                    "image/tiff",
                    "image/webp",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "application/vnd.ms-excel",
                    *DEFAULT_TEXT_CONTENT_TYPES,
                ),
            ),
        )


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings.from_env()
    return _SETTINGS






