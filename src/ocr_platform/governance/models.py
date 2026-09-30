"""Typed contracts for sensitive-document retention and review audit history."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetentionClass(StrEnum):
    """Durable-data classes with independent retention windows."""

    TEMPORARY_PROCESSING = "temporary_processing"
    ORIGINAL_SOURCE = "original_source"
    DERIVED_PAGE_IMAGES = "derived_page_images"
    VERIFIED_DATASET_ARTIFACTS = "verified_dataset_artifacts"


class RetentionPolicy(BaseModel):
    """Validated retention windows expressed in seconds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temporary_seconds: int = Field(default=86_400, ge=1)
    source_seconds: int = Field(default=30 * 86_400, ge=1)
    derived_seconds: int = Field(default=30 * 86_400, ge=1)
    verified_dataset_seconds: int = Field(default=365 * 86_400, ge=1)

    def seconds_for(self, retention_class: RetentionClass) -> int:
        selected = RetentionClass(retention_class)
        return {
            RetentionClass.TEMPORARY_PROCESSING: self.temporary_seconds,
            RetentionClass.ORIGINAL_SOURCE: self.source_seconds,
            RetentionClass.DERIVED_PAGE_IMAGES: self.derived_seconds,
            RetentionClass.VERIFIED_DATASET_ARTIFACTS: self.verified_dataset_seconds,
        }[selected]

    def to_payload(self) -> dict[str, int]:
        return {
            "temporary_seconds": self.temporary_seconds,
            "source_seconds": self.source_seconds,
            "derived_seconds": self.derived_seconds,
            "verified_dataset_seconds": self.verified_dataset_seconds,
        }


class ReviewAction(StrEnum):
    """Auditable human-review decisions."""

    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    MARKED_UNCERTAIN = "marked_uncertain"


class ReviewFieldChange(BaseModel):
    """One immutable before/after value captured by a review decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str = Field(min_length=1, max_length=128)
    previous_value: str | None = Field(default=None, max_length=100_000)
    new_value: str | None = Field(default=None, max_length=100_000)

    @field_validator("field_name")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        if not value[0].isalpha() or any(
            not (char.isalnum() or char in "._-") for char in value
        ):
            raise ValueError("review field name is unsafe")
        return value


class ReviewAuditEvent(BaseModel):
    """Append-only review decision and field-change provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=64)
    reviewer_id: str = Field(min_length=1, max_length=255)
    action: ReviewAction
    reason: str = Field(min_length=1, max_length=2048)
    changed_fields: tuple[ReviewFieldChange, ...] = ()
    previous_status: str | None = Field(default=None, max_length=64)
    new_status: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("target_type")
    @classmethod
    def validate_target_type(cls, value: str) -> str:
        if not value[0].isalpha() or any(
            not (char.isalnum() or char in "_-") for char in value
        ):
            raise ValueError("review target type is unsafe")
        return value
