"""Canonical, backend-neutral OCR and document-intelligence evidence schema.

The models in this module are the durable contract between ingestion, layout,
OCR/HTR adapters, verification, and dataset export. Raw evidence is retained
separately from normalized presentation text and every geometry-bearing object
carries provenance through its parent page/document.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonNegativeFloat = Annotated[float, Field(ge=0)]
Confidence = Annotated[float, Field(ge=0, le=1)]
PositiveFloat = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CoordinateSpace(StrEnum):
    """Coordinate space used by geometry and provenance.

    Pixel coordinates are measured from the top-left origin of the referenced
    page image. PDF points use the PDF page's top-left logical reference. The
    parent page records the reference dimensions used for validation and
    downstream mapping.
    """

    SOURCE_PIXEL = "source_pixel"
    RENDERED_PIXEL = "rendered_pixel"
    PDF_POINT = "pdf_point"


class PageType(StrEnum):
    NATIVE_TEXT = "native_text"
    SCANNED = "scanned"
    IMAGE = "image"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class BlockType(StrEnum):
    TITLE = "title"
    PARAGRAPH = "paragraph"
    TEXT_LINE_GROUP = "text_line_group"
    PRINTED_TEXT = "printed_text"
    HANDWRITING = "handwriting"
    TABLE = "table"
    FORM = "form"
    FORMULA = "formula"
    IMAGE = "image"
    FIGURE = "figure"
    CAPTION = "caption"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    SIDEBAR = "sidebar"
    LIST = "list"
    MULTI_COLUMN = "multi_column"
    TINY_TEXT = "tiny_text"
    UNKNOWN = "unknown"


class TextType(StrEnum):
    PRINTED = "printed"
    HANDWRITTEN = "handwritten"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ExtractionMethod(StrEnum):
    NATIVE_PDF_TEXT = "native_pdf_text"
    OCR = "ocr"
    HANDWRITING_RECOGNITION = "handwriting_recognition"
    LAYOUT = "layout"
    TABLE_EXTRACTION = "table_extraction"
    MANUAL_REVIEW = "manual_review"


class VerificationStatus(StrEnum):
    ACCEPTED = "accepted"
    VERIFIED = "verified"
    UNCERTAIN = "uncertain"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    FAILED = "failed"


class ProcessingStatus(StrEnum):
    """Job/execution status, intentionally separate from OCR certainty."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class WarningSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReviewFlag(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    DISAGREEMENT = "disagreement"
    TINY_TEXT = "tiny_text"
    MISSING_BACKEND = "missing_backend"
    NATIVE_TEXT_UNRELIABLE = "native_text_unreliable"
    INVALID_GEOMETRY = "invalid_geometry"
    LANGUAGE_UNCERTAIN = "language_uncertain"
    CONFIDENCE_SCALE_MISMATCH = "confidence_scale_mismatch"
    BACKEND_FAILURE = "backend_failure"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    TABLE_STRUCTURE_UNCERTAIN = "table_structure_uncertain"
    INDEPENDENT_EVIDENCE_INSUFFICIENT = "independent_evidence_insufficient"
    MANUAL_REVIEW = "manual_review"


class VerificationReason(StrEnum):
    """Stable explanations for candidate selection and review decisions."""

    LOW_PRIMARY_CONFIDENCE = "low_primary_confidence"
    BACKEND_DISAGREEMENT = "backend_disagreement"
    NORMALIZED_DISAGREEMENT = "normalized_disagreement"
    DIGIT_DISAGREEMENT = "digit_disagreement"
    PUNCTUATION_DIFFERENCE = "punctuation_difference"
    WHITESPACE_DIFFERENCE = "whitespace_difference"
    TINY_TEXT = "tiny_text"
    EMPTY_TEXT = "empty_text"
    SHORT_TEXT = "short_text"
    SUSPICIOUS_CHARACTERS = "suspicious_characters"
    LANGUAGE_SCRIPT_MISMATCH = "language_script_mismatch"
    EXPECTED_FORMAT_MISMATCH = "expected_format_mismatch"
    LOW_IMAGE_QUALITY = "low_image_quality"
    CONFIDENCE_SCALE_MISMATCH = "confidence_scale_mismatch"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INSUFFICIENT_INDEPENDENT_EVIDENCE = "insufficient_independent_evidence"
    RETRY_EXHAUSTED = "retry_exhausted"
    CONSENSUS_ACROSS_VARIANTS = "consensus_across_variants"
    CONSENSUS_ACROSS_BACKENDS = "consensus_across_backends"
    BACKEND_FAILURE = "backend_failure"
    STORAGE_FAILURE = "storage_failure"


class PolygonPoint(BaseModel):
    """A non-negative point in the parent object's coordinate space."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: NonNegativeFloat
    y: NonNegativeFloat


type Polygon = list[PolygonPoint]


class BoundingBox(BaseModel):
    """Axis-aligned ``[x0, y0, x1, y1]`` geometry.

    Coordinates are non-negative pixels or PDF points, depending on the
    associated :class:`CoordinateSpace`. Page bounds are checked by the
    enclosing ``PageResult`` when reference dimensions are available.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    x0: NonNegativeFloat
    y0: NonNegativeFloat
    x1: NonNegativeFloat
    y1: NonNegativeFloat

    @model_validator(mode="after")
    def validate_order(self) -> BoundingBox:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bounding box coordinates must be ordered")
        return self

    @property
    def x2(self) -> float:
        """Compatibility alias for the right edge used by some consumers."""

        return self.x1

    @property
    def y2(self) -> float:
        """Compatibility alias for the bottom edge used by some consumers."""

        return self.y1

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    def validate_within(self, width: float, height: float) -> BoundingBox:
        if width <= 0 or height <= 0:
            raise ValueError("geometry reference dimensions must be positive")
        if self.x1 > width or self.y1 > height:
            raise ValueError("bounding box exceeds page reference dimensions")
        return self


class SourceMetadata(BaseModel):
    """Immutable source-file identity and ingestion metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=127)
    byte_size: int = Field(ge=0)
    checksum_sha256: Sha256
    source_uri: str = Field(min_length=1)
    source_created_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("filename")
    @classmethod
    def reject_control_chars(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("filename contains control characters")
        return value

    @property
    def sha256(self) -> str:
        """Convenience alias for callers that use the shorter checksum name."""

        return self.checksum_sha256


class ExtractionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    method: ExtractionMethod
    backend: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    model_version: str = Field(min_length=1, max_length=128)
    dpi: PositiveFloat | None = None
    region_scale: PositiveFloat = 1.0
    preprocess_variant: str = Field(min_length=1, max_length=256)
    confidence_scale: str = Field(default="backend_specific", min_length=1, max_length=128)
    backend_family: str = Field(default="unknown", min_length=1, max_length=128)
    configuration_hash: Sha256 | None = None
    runtime_metadata: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1, max_length=128)
    page_number: PositiveInt
    source_uri: str | None = None
    crop_uri: str | None = None
    coordinate_space: CoordinateSpace


class OCRCandidate(BaseModel):
    """One backend/preprocessing candidate retained for verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    raw_text: str
    normalized_text: str
    confidence: Confidence | None = None
    extraction: ExtractionMetadata
    source: Provenance | None = None
    reason: str | None = Field(default=None, max_length=512)
    reason_codes: list[VerificationReason] = Field(default_factory=list)
    tiny_text: bool = False


class WordResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    raw_text: str
    normalized_text: str
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    confidence: Confidence | None = None
    reading_order: int = Field(ge=0)


class VerificationRecord(BaseModel):
    """A persisted verification/retry attempt for one extracted region."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    candidate_id: str | None = Field(default=None, max_length=128)
    status: VerificationStatus
    raw_text: str
    normalized_text: str
    confidence: Confidence | None = None
    extraction: ExtractionMetadata
    difference_from_previous: float | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=512)
    reason_codes: list[VerificationReason] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewCorrection(BaseModel):
    """Append-only human correction; the original OCR value remains immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=64)
    reviewer_id: str = Field(min_length=1, max_length=255)
    previous_corrected_text: str | None = None
    corrected_text: str = Field(max_length=100_000)
    raw_text_unchanged: str
    reason: str = Field(min_length=1, max_length=2048)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TableCellResult(BaseModel):
    """Canonical structured evidence for one extracted table cell."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    raw_text: str
    normalized_text: str
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    confidence: Confidence | None = None
    language: str = Field(default="und", min_length=2, max_length=32)
    script: str = Field(default="Unknown", min_length=1, max_length=64)
    text_type: TextType = TextType.UNKNOWN
    reading_order: int = Field(ge=0)
    needs_review: bool = False
    verification_status: VerificationStatus = VerificationStatus.ACCEPTED
    selected_candidate_id: str | None = Field(default=None, max_length=128)
    source: Provenance
    extraction: ExtractionMetadata
    uncertainty_flags: list[ReviewFlag] = Field(default_factory=list)
    reason_codes: list[VerificationReason] = Field(default_factory=list)
    verification_history: list[VerificationRecord] = Field(default_factory=list)
    review_artifact_uri: str | None = Field(default=None, max_length=2048)
    candidates: list[OCRCandidate] = Field(default_factory=list)
    corrected_text: str | None = Field(default=None, max_length=100_000)
    correction_history: list[ReviewCorrection] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_review_state(self) -> TableCellResult:
        if self.uncertainty_flags and not self.needs_review:
            self.needs_review = True
        if self.verification_status in {
            VerificationStatus.UNCERTAIN,
            VerificationStatus.HUMAN_REVIEW_REQUIRED,
            VerificationStatus.FAILED,
        }:
            self.needs_review = True
        if self.needs_review and self.verification_status == VerificationStatus.ACCEPTED:
            self.verification_status = VerificationStatus.HUMAN_REVIEW_REQUIRED
        return self


class LineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    raw_text: str
    normalized_text: str
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    confidence: Confidence | None = None
    language: str = Field(default="und", min_length=2, max_length=32)
    script: str = Field(default="Unknown", min_length=1, max_length=64)
    text_type: TextType = TextType.UNKNOWN
    reading_order: int = Field(ge=0)
    tiny_text: bool = False
    needs_review: bool = False
    source: Provenance
    extraction: ExtractionMetadata
    verification_status: VerificationStatus = VerificationStatus.ACCEPTED
    selected_candidate_id: str | None = Field(default=None, max_length=128)
    uncertainty_flags: list[ReviewFlag] = Field(default_factory=list)
    reason_codes: list[VerificationReason] = Field(default_factory=list)
    verification_history: list[VerificationRecord] = Field(default_factory=list)
    candidates: list[OCRCandidate] = Field(default_factory=list)
    words: list[WordResult] = Field(default_factory=list)
    review_artifact_uri: str | None = Field(default=None, max_length=2048)
    corrected_text: str | None = Field(default=None, max_length=100_000)
    correction_history: list[ReviewCorrection] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_review_state(self) -> LineResult:
        if self.tiny_text and ReviewFlag.TINY_TEXT not in self.uncertainty_flags:
            self.uncertainty_flags.append(ReviewFlag.TINY_TEXT)
        if self.uncertainty_flags and not self.needs_review:
            self.needs_review = True
        if self.verification_status in {
            VerificationStatus.UNCERTAIN,
            VerificationStatus.HUMAN_REVIEW_REQUIRED,
            VerificationStatus.FAILED,
        }:
            self.needs_review = True
        if self.needs_review and self.verification_status == VerificationStatus.ACCEPTED:
            self.verification_status = VerificationStatus.HUMAN_REVIEW_REQUIRED
        return self


class BlockResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    block_type: BlockType
    bbox: BoundingBox
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=3)
    reading_order: int = Field(ge=0)
    confidence: Confidence | None = None
    source: Provenance
    lines: list[LineResult] = Field(default_factory=list)
    needs_review: bool = False
    uncertainty_flags: list[ReviewFlag] = Field(default_factory=list)
    table_cells: list[TableCellResult] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.ACCEPTED
    reason_codes: list[VerificationReason] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_review_state(self) -> BlockResult:
        if self.uncertainty_flags and not self.needs_review:
            self.needs_review = True
        if self.verification_status in {
            VerificationStatus.UNCERTAIN,
            VerificationStatus.HUMAN_REVIEW_REQUIRED,
            VerificationStatus.FAILED,
        }:
            self.needs_review = True
        if self.needs_review and self.verification_status == VerificationStatus.ACCEPTED:
            self.verification_status = VerificationStatus.HUMAN_REVIEW_REQUIRED
        return self


class PageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: PositiveInt
    width: PositiveFloat
    height: PositiveFloat
    coordinate_space: CoordinateSpace
    page_type: PageType
    source_uri: str = Field(min_length=1)
    id: str | None = Field(default=None, min_length=1, max_length=160)
    rendered_uri: str | None = None
    source_dpi: PositiveFloat | None = None
    rendered_width: PositiveFloat | None = None
    rendered_height: PositiveFloat | None = None
    blocks: list[BlockResult] = Field(default_factory=list)
    native_text_reliable: bool = False
    native_text_reason: str | None = None
    page_flags: list[ReviewFlag] = Field(default_factory=list)

    def _dimensions_for(self, coordinate_space: CoordinateSpace) -> tuple[float, float] | None:
        if coordinate_space == self.coordinate_space:
            return self.width, self.height
        if coordinate_space == CoordinateSpace.RENDERED_PIXEL:
            if self.rendered_width is not None and self.rendered_height is not None:
                return self.rendered_width, self.rendered_height
            return None
        return None

    @staticmethod
    def _validate_polygon_within(
        polygon: list[PolygonPoint] | None, width: float, height: float
    ) -> None:
        if polygon is None:
            return
        if any(point.x > width or point.y > height for point in polygon):
            raise ValueError("polygon exceeds page reference dimensions")

    @model_validator(mode="after")
    def validate_geometry_and_provenance(self) -> PageResult:
        for block in self.blocks:
            if block.source.page_number != self.page_number:
                raise ValueError("block provenance page does not match page")
            block_dimensions = self._dimensions_for(block.source.coordinate_space)
            if block_dimensions is not None:
                block.bbox.validate_within(*block_dimensions)
                self._validate_polygon_within(block.polygon, *block_dimensions)
            for line in block.lines:
                if line.source.page_number != self.page_number:
                    raise ValueError("line provenance page does not match page")
                line_dimensions = self._dimensions_for(line.source.coordinate_space)
                if line_dimensions is not None:
                    line.bbox.validate_within(*line_dimensions)
                    self._validate_polygon_within(line.polygon, *line_dimensions)
                for word in line.words:
                    word_dimensions = self._dimensions_for(line.source.coordinate_space)
                    if word_dimensions is not None:
                        word.bbox.validate_within(*word_dimensions)
                        self._validate_polygon_within(word.polygon, *word_dimensions)
            for cell in block.table_cells:
                if cell.source.page_number != self.page_number:
                    raise ValueError("table cell provenance page does not match page")
                cell_dimensions = self._dimensions_for(cell.source.coordinate_space)
                if cell_dimensions is not None:
                    cell.bbox.validate_within(*cell_dimensions)
                    self._validate_polygon_within(cell.polygon, *cell_dimensions)
        return self


class QualityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: VerificationStatus
    confidence_mean: float | None = Field(default=None, ge=0, le=1)
    confidence_min: float | None = Field(default=None, ge=0, le=1)
    disagreement_rate: float | None = Field(default=None, ge=0, le=1)
    review_line_count: int = Field(default=0, ge=0)
    notes: list[str] = Field(default_factory=list)


class ProcessingWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2048)
    severity: WarningSeverity = WarningSeverity.WARNING
    phase: str = Field(min_length=1, max_length=128)
    retryable: bool = False
    document_id: str | None = Field(default=None, max_length=128)
    page_number: PositiveInt | None = None
    block_id: str | None = Field(default=None, max_length=128)
    line_id: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ManifestArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=128)
    uri: str = Field(min_length=1, max_length=2048)
    checksum_sha256: Sha256 | None = None


class ProcessingManifest(BaseModel):
    """Versioned processing/export manifest metadata.

    The canonical document remains the authoritative evidence record. These
    optional fields let storage adapters and dataset exporters expose source,
    normalization, model, status-count, and artifact inventory without
    weakening the compact manifest contract used by earlier phases.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    manifest_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    document_id: str = Field(min_length=1, max_length=128)
    pipeline_version: str = Field(min_length=1, max_length=32)
    schema_version: str = Field(min_length=1, max_length=32)
    source_checksum: Sha256
    processing_checksum: Sha256
    configuration_hash: Sha256
    formats: list[str] = Field(default_factory=list)
    artifacts: list[ManifestArtifact] = Field(default_factory=list)
    exporter_version: str | None = Field(default=None, min_length=1, max_length=32)
    source_filename: str | None = Field(default=None, min_length=1, max_length=255)
    source_content_type: str | None = Field(default=None, min_length=1, max_length=127)
    source_byte_size: int | None = Field(default=None, ge=0)
    source_sha256: Sha256 | None = None
    normalization_policy: dict[str, str | bool] = Field(default_factory=dict)
    page_count: int = Field(default=0, ge=0)
    processing_started_at: datetime | None = None
    processing_finished_at: datetime | None = None
    processing_time_seconds: float | None = Field(default=None, ge=0)
    ocr_backends: list[dict[str, str]] = Field(default_factory=list)
    model_identifiers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    line_counts: dict[str, int] = Field(default_factory=dict)
    table_cell_counts: dict[str, int] = Field(default_factory=dict)
    export_policy: str | None = Field(default=None, min_length=1, max_length=64)
    artifact_references: list[ManifestArtifact] = Field(default_factory=list)
    generated_at: datetime | None = None


class SemanticFieldType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    IDENTIFIER = "identifier"
    EMAIL = "email"
    URL = "url"


class EvidenceLink(BaseModel):
    """Traceable source span used by a semantic extraction result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1, max_length=128)
    page_number: PositiveInt
    source_uri: str | None = None
    block_id: str | None = Field(default=None, max_length=128)
    line_id: str | None = Field(default=None, max_length=128)
    cell_id: str | None = Field(default=None, max_length=128)
    bbox: BoundingBox
    raw_text: str
    normalized_text: str
    verification_status: VerificationStatus = VerificationStatus.ACCEPTED

    @model_validator(mode="after")
    def require_span_identity(self) -> EvidenceLink:
        if self.line_id is None and self.cell_id is None:
            raise ValueError("semantic evidence must reference a line or table cell")
        return self


class FieldSchema(BaseModel):
    """Explicit, non-generative schema constraint for one business field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    value_type: SemanticFieldType = SemanticFieldType.TEXT
    pattern: str | None = Field(default=None, max_length=512)
    required: bool = False
    block_types: list[BlockType] = Field(default_factory=list)

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str | None) -> str | None:
        if value is not None:
            import re

            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError("field schema pattern must be valid regex") from exc
        return value


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    name: str = Field(min_length=1, max_length=128)
    raw_value: str
    normalized_value: str
    value_type: SemanticFieldType
    confidence: Confidence | None = None
    verification_status: VerificationStatus
    needs_review: bool = False
    evidence: list[EvidenceLink] = Field(min_length=1)
    extraction_method: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    model_version: str = Field(min_length=1, max_length=128)
    reason_codes: list[VerificationReason] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_review_state(self) -> ExtractedField:
        evidence_unverified = any(
            item.verification_status != VerificationStatus.VERIFIED
            for item in self.evidence
        )
        if self.needs_review or evidence_unverified:
            object.__setattr__(self, "needs_review", True)
        if self.needs_review and self.verification_status == VerificationStatus.ACCEPTED:
            object.__setattr__(
                self,
                "verification_status",
                VerificationStatus.HUMAN_REVIEW_REQUIRED,
            )
        return self


class EntityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    entity_type: str = Field(min_length=1, max_length=128)
    fields: list[ExtractedField] = Field(default_factory=list)
    evidence: list[EvidenceLink] = Field(default_factory=list)


class DocumentIntelligenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    document_id: str = Field(min_length=1, max_length=128)
    fields: list[ExtractedField] = Field(default_factory=list)
    entities: list[EntityResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    pipeline_version: str = Field(min_length=1, max_length=32)
    source: SourceMetadata
    configuration_hash: Sha256
    normalization_policy: dict[str, str | bool] = Field(default_factory=dict)
    processing_checksum: Sha256
    processing_started_at: datetime
    processing_finished_at: datetime | None = None
    pages: list[PageResult] = Field(default_factory=list)
    processing_status: ProcessingStatus = ProcessingStatus.COMPLETED
    status: VerificationStatus = VerificationStatus.ACCEPTED
    quality: QualityAssessment | None = None
    processing_warnings: list[ProcessingWarning] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    intelligence: DocumentIntelligenceResult | None = None

    @model_validator(mode="after")
    def validate_page_numbers(self) -> DocumentResult:
        expected = list(range(1, len(self.pages) + 1))
        actual = [page.page_number for page in self.pages]
        if actual and actual != expected:
            raise ValueError("document pages must be ordered and contiguous")
        return self

    def canonical_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


# Compatibility names used by the existing ingestion/pipeline implementation.
DocumentSource = SourceMetadata
Word = WordResult
VerificationAttempt = VerificationRecord
Line = LineResult
Block = BlockResult
Page = PageResult
Document = DocumentResult



