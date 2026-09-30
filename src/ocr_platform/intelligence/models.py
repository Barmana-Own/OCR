"""Schema contracts for deterministic semantic extraction."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_platform.domain import FieldSchema


class DocumentIntelligenceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    fields: list[FieldSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_field_names(self) -> DocumentIntelligenceSchema:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("document intelligence field names must be unique")
        return self


__all__ = ["DocumentIntelligenceSchema"]
