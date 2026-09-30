"""Strict, provider-neutral contracts for benchmark references and predictions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

from ocr_platform.domain.models import BoundingBox, PolygonPoint, VerificationStatus


class BenchmarkCategory(StrEnum):
    """Required benchmark slices kept separate in every report."""

    CLEAN_PERSIAN = "clean_persian"
    CLEAN_ENGLISH = "clean_english"
    MIXED_PERSIAN_ENGLISH = "mixed_persian_english"
    LOW_QUALITY_SCAN = "low_quality_scan"
    PHONE_PHOTO = "phone_photo"
    SKEWED_PERSPECTIVE = "skewed_perspective"
    TINY_TEXT = "tiny_text"
    HANDWRITTEN_PERSIAN = "handwritten_persian"
    FORM_CARD = "form_card"
    TABLE = "table"
    MULTI_COLUMN = "multi_column"
    NATIVE_TEXT_PDF = "native_text_pdf"
    MIXED_NATIVE_SCANNED_PDF = "mixed_native_scanned_pdf"


class TinyTextStage(StrEnum):
    """Ordered tiny-text evidence stages used for recovery evaluation."""

    FIRST_PASS = "first_pass"
    HIGH_DPI = "high_dpi"
    CROP_UPSCALED = "crop_upscaled"
    VERIFIED_FINAL = "verified_final"


def _parse_bbox(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise ValueError("bbox lists must contain four coordinates")
        return BoundingBox(x0=value[0], y0=value[1], x1=value[2], y1=value[3])
    return value


class BenchmarkBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


class GroundTruthLine(BenchmarkBaseModel):
    id: str = Field(min_length=1, max_length=160)
    raw_text: str
    normalized_text: str | None = None
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    reading_order: NonNegativeInt
    tiny_text: bool = False
    review_label: VerificationStatus | None = None

    _bbox_input = field_validator("bbox", mode="before")(_parse_bbox)


class GroundTruthTableCell(BenchmarkBaseModel):
    id: str = Field(min_length=1, max_length=160)
    row: NonNegativeInt
    column: NonNegativeInt
    raw_text: str
    normalized_text: str | None = None
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    reading_order: NonNegativeInt = 0
    review_label: VerificationStatus | None = None

    _bbox_input = field_validator("bbox", mode="before")(_parse_bbox)


class GroundTruthPage(BenchmarkBaseModel):
    page_number: PositiveInt
    width: PositiveFloat
    height: PositiveFloat
    page_text: str = ""
    lines: list[GroundTruthLine] = Field(default_factory=list)
    table_cells: list[GroundTruthTableCell] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_geometry(self) -> GroundTruthPage:
        line_ids = [line.id for line in self.lines]
        cell_ids = [cell.id for cell in self.table_cells]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("ground-truth line IDs must be unique within a page")
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("ground-truth table-cell IDs must be unique within a page")
        for item in (*self.lines, *self.table_cells):
            item.bbox.validate_within(self.width, self.height)
            if item.polygon and any(
                point.x > self.width or point.y > self.height for point in item.polygon
            ):
                raise ValueError("polygon exceeds page reference dimensions")
        return self


class GroundTruthDocument(BenchmarkBaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    category: BenchmarkCategory
    source_uri: str = Field(min_length=1, max_length=2048)
    pages: list[GroundTruthPage] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_page_numbers(self) -> GroundTruthDocument:
        actual = [page.page_number for page in self.pages]
        if actual != list(range(1, len(actual) + 1)):
            raise ValueError("ground-truth page numbers must be ordered and contiguous")
        return self


class GroundTruthDataset(BenchmarkBaseModel):
    schema_version: str = Field(min_length=1, max_length=32)
    dataset_version: str = Field(min_length=1, max_length=64)
    documents: list[GroundTruthDocument] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_document_ids(self) -> GroundTruthDataset:
        ids = [document.document_id for document in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("ground-truth document IDs must be unique")
        return self


class BenchmarkDocumentReference(BenchmarkBaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    category: BenchmarkCategory


class BenchmarkManifest(BenchmarkBaseModel):
    schema_version: str = Field(min_length=1, max_length=32)
    dataset_version: str = Field(min_length=1, max_length=64)
    ground_truth_source: str = Field(default="stored", min_length=1, max_length=64)
    ground_truth_uri: str = Field(min_length=1, max_length=2048)
    prediction_uris: dict[str, str] = Field(min_length=1)
    documents: list[BenchmarkDocumentReference] = Field(min_length=1)
    quality_gates_uri: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def reject_duplicate_references(self) -> BenchmarkManifest:
        document_ids = [item.document_id for item in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("manifest document IDs must be unique")
        prediction_names = list(self.prediction_uris)
        if len(prediction_names) != len(set(prediction_names)):
            raise ValueError("prediction set names must be unique")
        return self


class BackendCandidate(BenchmarkBaseModel):
    backend: str = Field(min_length=1, max_length=128)
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    model: str | None = Field(default=None, max_length=256)
    model_version: str | None = Field(default=None, max_length=128)


class TinyTextStageCandidate(BenchmarkBaseModel):
    stage: TinyTextStage
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    backend: str = Field(default="unknown", min_length=1, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    model_version: str | None = Field(default=None, max_length=128)


class PredictionLine(BenchmarkBaseModel):
    id: str = Field(min_length=1, max_length=160)
    raw_text: str
    normalized_text: str | None = None
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    reading_order: NonNegativeInt = 0
    verification_status: VerificationStatus = VerificationStatus.ACCEPTED
    confidence: float | None = Field(default=None, ge=0, le=1)
    backend: str = Field(default="unknown", min_length=1, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    model_version: str | None = Field(default=None, max_length=128)
    configuration_hash: str | None = Field(default=None, max_length=128)
    preprocess_variant: str | None = Field(default=None, max_length=256)
    dpi: PositiveFloat | None = None
    region_scale: PositiveFloat = 1.0
    tiny_text: bool = False
    sent_to_verification: bool = False
    candidates: list[BackendCandidate] = Field(default_factory=list)
    tiny_text_stages: list[TinyTextStageCandidate] = Field(default_factory=list)

    _bbox_input = field_validator("bbox", mode="before")(_parse_bbox)


class PredictionTableCell(BenchmarkBaseModel):
    id: str = Field(min_length=1, max_length=160)
    row: NonNegativeInt
    column: NonNegativeInt
    raw_text: str
    normalized_text: str | None = None
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    verification_status: VerificationStatus = VerificationStatus.ACCEPTED
    confidence: float | None = Field(default=None, ge=0, le=1)
    backend: str = Field(default="unknown", min_length=1, max_length=128)
    candidates: list[BackendCandidate] = Field(default_factory=list)

    _bbox_input = field_validator("bbox", mode="before")(_parse_bbox)


class PredictionPage(BenchmarkBaseModel):
    page_number: PositiveInt
    page_text: str = ""
    lines: list[PredictionLine] = Field(default_factory=list)
    table_cells: list[PredictionTableCell] = Field(default_factory=list)


class PredictionDocument(BenchmarkBaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    category: BenchmarkCategory
    pages: list[PredictionPage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_page_numbers(self) -> PredictionDocument:
        actual = [page.page_number for page in self.pages]
        if actual != list(range(1, len(actual) + 1)):
            raise ValueError("prediction page numbers must be ordered and contiguous")
        return self


class PredictionDataset(BenchmarkBaseModel):
    schema_version: str = Field(min_length=1, max_length=32)
    dataset_version: str = Field(min_length=1, max_length=64)
    documents: list[PredictionDocument] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_document_ids(self) -> PredictionDataset:
        ids = [document.document_id for document in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("prediction document IDs must be unique")
        return self


class TinyTextMetrics(BenchmarkBaseModel):
    count: NonNegativeInt = 0
    first_pass_cer: float | None = Field(default=None, ge=0)
    high_dpi_cer: float | None = Field(default=None, ge=0)
    crop_upscaled_cer: float | None = Field(default=None, ge=0)
    verified_final_cer: float | None = Field(default=None, ge=0)
    recovery_improvement: float | None = None


class CategoryMetrics(BenchmarkBaseModel):
    category: str = Field(min_length=1, max_length=64)
    document_count: NonNegativeInt = 0
    page_count: NonNegativeInt = 0
    reference_line_count: NonNegativeInt = 0
    predicted_line_count: NonNegativeInt = 0
    matched_line_count: NonNegativeInt = 0
    reference_table_cell_count: NonNegativeInt = 0
    predicted_table_cell_count: NonNegativeInt = 0
    page_cer: float = Field(default=0.0, ge=0)
    page_wer: float = Field(default=0.0, ge=0)
    cer: float = Field(default=0.0, ge=0)
    wer: float = Field(default=0.0, ge=0)
    exact_line_accuracy: float = Field(default=0.0, ge=0, le=1)
    line_detection_precision: float = Field(default=0.0, ge=0, le=1)
    line_detection_recall: float = Field(default=0.0, ge=0, le=1)
    reading_order_accuracy: float = Field(default=0.0, ge=0, le=1)
    table_cell_accuracy: float = Field(default=0.0, ge=0, le=1)
    accepted_automatically_rate: float = Field(default=0.0, ge=0, le=1)
    verification_rate: float = Field(default=0.0, ge=0, le=1)
    human_review_rate: float = Field(default=0.0, ge=0, le=1)
    backend_disagreement_rate: float = Field(default=0.0, ge=0, le=1)
    tiny_text: TinyTextMetrics = Field(default_factory=TinyTextMetrics)


class BenchmarkMetrics(BenchmarkBaseModel):
    categories: list[CategoryMetrics] = Field(default_factory=list)
    overall: CategoryMetrics | None = None


class QualityGateRule(BenchmarkBaseModel):
    name: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    category: str = Field(default="overall", min_length=1, max_length=64)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_bound(self) -> QualityGateRule:
        if (self.minimum is None) == (self.maximum is None):
            raise ValueError("quality gate must define exactly one of minimum or maximum")
        return self


class QualityGateConfig(BenchmarkBaseModel):
    schema_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    gates: list[QualityGateRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_names(self) -> QualityGateConfig:
        names = [gate.name for gate in self.gates]
        if len(names) != len(set(names)):
            raise ValueError("quality gate names must be unique")
        return self


class QualityGateResult(BenchmarkBaseModel):
    name: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    actual: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    passed: bool
    reason: str = Field(min_length=1, max_length=512)


class QualityGateEvaluation(BenchmarkBaseModel):
    passed: bool
    results: list[QualityGateResult] = Field(default_factory=list)


class MetricComparison(BenchmarkBaseModel):
    category: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=128)
    baseline: float
    current: float
    delta: float
    regression: bool


class BenchmarkComparison(BenchmarkBaseModel):
    baseline_report: str | None = Field(default=None, max_length=2048)
    tolerance: float = Field(default=0.0, ge=0)
    has_regressions: bool = False
    metrics: list[MetricComparison] = Field(default_factory=list)


class BenchmarkReport(BenchmarkBaseModel):
    report_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    schema_version: str = Field(min_length=1, max_length=32)
    dataset_version: str = Field(min_length=1, max_length=64)
    dataset_hash: str = Field(min_length=64, max_length=64)
    prediction_set: str = Field(min_length=1, max_length=128)
    variant: str = Field(min_length=1, max_length=128)
    mode: str = Field(min_length=1, max_length=32)
    generated_at: datetime
    configuration_hash: str = Field(min_length=64, max_length=64)
    model_versions: list[str] = Field(default_factory=list)
    hardware: dict[str, str] = Field(default_factory=dict)
    metrics: BenchmarkMetrics
    quality_gates: QualityGateEvaluation = Field(
        default_factory=lambda: QualityGateEvaluation(passed=True)
    )
    comparison: BenchmarkComparison | None = None
    warnings: list[str] = Field(default_factory=list)
