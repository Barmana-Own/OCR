"""Conservative, rule-driven semantic extraction with source evidence links."""

from __future__ import annotations

import re

from ocr_platform.domain import (
    Document,
    DocumentIntelligenceResult,
    EvidenceLink,
    ExtractedField,
    FieldSchema,
)

from .models import DocumentIntelligenceSchema


class DocumentIntelligenceEngine:
    """Extract only values explicitly described by a caller-provided schema."""

    model = "schema-rules"
    model_version = "1.0.0"

    def extract(
        self,
        document: Document,
        schema: DocumentIntelligenceSchema,
    ) -> DocumentIntelligenceResult:
        fields: list[ExtractedField] = []
        warnings: list[str] = []
        for field_schema in schema.fields:
            extracted = self._extract_field(document, field_schema)
            if extracted is None:
                if field_schema.required:
                    warnings.append(f"required field not found: {field_schema.name}")
                continue
            fields.append(extracted)
        return DocumentIntelligenceResult(
            schema_version=schema.schema_version,
            document_id=document.id,
            fields=fields,
            warnings=warnings,
        )

    def _extract_field(self, document: Document, schema: FieldSchema) -> ExtractedField | None:
        pattern = re.compile(schema.pattern, re.UNICODE) if schema.pattern else None
        for page in document.pages:
            for block in sorted(page.blocks, key=lambda item: item.reading_order):
                if schema.block_types and block.block_type not in schema.block_types:
                    continue
                evidence_items = [
                    (block.id, line.id, None, line.raw_text, line.normalized_text, line.bbox, line)
                    for line in block.lines
                ]
                evidence_items.extend(
                    (block.id, None, cell.id, cell.raw_text, cell.normalized_text, cell.bbox, cell)
                    for cell in block.table_cells
                )
                for (
                    block_id,
                    line_id,
                    cell_id,
                    raw_text,
                    normalized_text,
                    bbox,
                    source,
                ) in evidence_items:
                    match = (
                        pattern.search(raw_text)
                        if pattern
                        else _label_value_match(schema.name, raw_text)
                    )
                    if match is None:
                        continue
                    value = match.group(1) if match.lastindex else match.group(0)
                    status = source.verification_status
                    evidence = EvidenceLink(
                        document_id=document.id,
                        page_number=page.page_number,
                        source_uri=source.source.source_uri,
                        block_id=block_id,
                        line_id=line_id,
                        cell_id=cell_id,
                        bbox=bbox,
                        raw_text=raw_text,
                        normalized_text=normalized_text,
                        verification_status=status,
                    )
                    return ExtractedField(
                        name=schema.name,
                        raw_value=value,
                        normalized_value=value,
                        value_type=schema.value_type,
                        confidence=source.confidence,
                        verification_status=status,
                        needs_review=source.needs_review,
                        evidence=[evidence],
                        extraction_method="schema_rule",
                        model=self.model,
                        model_version=self.model_version,
                        reason_codes=list(source.reason_codes),
                    )
        return None


def _label_value_match(name: str, text: str):
    """Use a deliberately narrow ``label: value`` convention when no regex is given."""

    label = re.escape(name.replace("_", " "))
    return re.search(rf"{label}\s*[:：-]\s*(\S(?:.*\S)?)$", text, re.IGNORECASE)


__all__ = ["DocumentIntelligenceEngine"]
