from __future__ import annotations

from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.dataset import DatasetExporter, DatasetExportPolicy
from ocr_platform.domain import SemanticFieldType, VerificationStatus
from ocr_platform.governance import ReviewCorrectionService
from ocr_platform.intelligence import DocumentIntelligenceEngine, DocumentIntelligenceSchema
from ocr_platform.pipeline import DocumentPipeline
from tests.integration.test_pipeline import DeterministicBackend


def _document(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (400, 200), "white").save(source, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    return DocumentPipeline(settings, backends=(DeterministicBackend(),)).process_path(
        source,
        filename="source.png",
        declared_content_type="image/png",
    )


def test_schema_driven_intelligence_keeps_source_evidence(tmp_path: Path) -> None:
    document = _document(tmp_path)
    schema = DocumentIntelligenceSchema(
        name="contract-fields",
        fields=[
            {
                "name": "contract_number",
                "value_type": SemanticFieldType.IDENTIFIER,
                "pattern": r"شماره قرارداد\s+([۰-۹١-٩0-9]+)",
                "required": True,
            }
        ],
    )
    result = DocumentIntelligenceEngine().extract(document, schema)
    assert result.document_id == document.id
    assert result.fields[0].raw_value == "١٢٣٤٥"
    assert result.fields[0].evidence[0].line_id == document.pages[0].blocks[0].lines[0].id
    assert result.fields[0].evidence[0].raw_text == "شماره قرارداد ١٢٣٤٥"
    assert result.fields[0].needs_review is True


def test_human_correction_is_an_append_only_revision_and_export_uses_effective_text(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    line = document.pages[0].blocks[0].lines[0]
    revised = ReviewCorrectionService().correct(
        document,
        target_id=line.id,
        corrected_text="شماره قرارداد ۱۲۳۴۵",
        reviewer_id="reviewer-1",
        reason="verified against the source crop",
    )
    corrected = revised.pages[0].blocks[0].lines[0]
    assert corrected.raw_text == line.raw_text
    assert corrected.corrected_text == "شماره قرارداد ۱۲۳۴۵"
    assert len(corrected.correction_history) == 1
    assert corrected.correction_history[0].raw_text_unchanged == line.raw_text
    assert corrected.verification_status is VerificationStatus.VERIFIED
    assert corrected.needs_review is False
    exported = DatasetExporter(
        DocumentPipeline(
            Settings(environment="test", storage_root=tmp_path / "artifacts"),
            backends=(DeterministicBackend(),),
        ).store
    ).export(
        revised,
        tmp_path / "exports",
        formats=("txt",),
        policy=DatasetExportPolicy.STRICT_VERIFIED_ONLY,
    )
    assert "شماره قرارداد ۱۲۳۴۵" in (exported.root / "document.txt").read_text(
        encoding="utf-8"
    )
