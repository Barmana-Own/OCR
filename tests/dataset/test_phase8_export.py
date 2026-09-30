import json
from pathlib import Path

import pytest
from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.dataset import DatasetExporter, DatasetExportPolicy
from ocr_platform.domain import ProcessingManifest, VerificationStatus
from ocr_platform.errors import ArtifactStorageError
from ocr_platform.normalization import DigitPolicy, NormalizationConfig
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.storage import LocalArtifactStore
from tests.integration.test_phase7_review_artifacts import DisagreeingBackend
from tests.integration.test_pipeline import DeterministicBackend
from tests.integration.test_retry_pipeline import LowConfidenceRetryBackend


def _source(tmp_path: Path, name: str = "source.png") -> Path:
    path = tmp_path / name
    Image.new("RGB", (400, 200), "white").save(path, format="PNG")
    return path


def test_default_export_excludes_review_lines_and_manifest_records_counts(
    tmp_path: Path,
) -> None:
    source_path = _source(tmp_path)
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=1)
    document = DocumentPipeline(settings, backends=(DisagreeingBackend(),)).process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )

    exported = DatasetExporter(DocumentPipeline(settings, backends=()).store).export(
        document,
        tmp_path / "exports",
    )

    assert exported.manifest["export_policy"] == "accepted_verified"
    assert exported.manifest["counts"]["human_review_required"] == 1
    assert exported.manifest["counts"]["exported_lines"] == 0
    assert not list((exported.root / "line-crops").glob("*.png"))
    assert (exported.root / "pages" / "page_0001" / "page.json").is_file()
    canonical = json.loads((exported.root / "document.json").read_text(encoding="utf-8"))
    assert canonical["pages"][0]["blocks"][0]["lines"][0]["raw_text"] == "شماره ۱۲۴"


def test_all_with_status_exports_review_crop_with_explicit_partition_and_mapping(
    tmp_path: Path,
) -> None:
    source_path = _source(tmp_path)
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=1)
    pipeline = DocumentPipeline(settings, backends=(DisagreeingBackend(),))
    document = pipeline.process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )

    exported = DatasetExporter(pipeline.store).export(
        document,
        tmp_path / "exports",
        policy=DatasetExportPolicy.ALL_WITH_STATUS,
    )

    crop_paths = list((exported.root / "pages" / "page_0001" / "lines").rglob("*.png"))
    assert len(crop_paths) == 1
    assert "human_review_required" in crop_paths[0].parts
    label_path = crop_paths[0].with_suffix(".json")
    label = json.loads(label_path.read_text(encoding="utf-8"))
    line = document.pages[0].blocks[0].lines[0]
    assert label["raw_text"] == line.raw_text
    assert label["normalized_text"] == line.normalized_text
    assert label["verification_status"] == "human_review_required"
    assert label["crop"]["page_bbox"] == line.bbox.as_list()
    assert label["crop"]["pixel_bbox"] == [10, 10, 80, 28]
    assert label["page_image_path"] == "pages/page_0001/image.png"


def test_strict_verified_only_exports_verified_retry_result(tmp_path: Path) -> None:
    source_path = _source(tmp_path)
    backend = LowConfidenceRetryBackend()
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts", max_retries=1)
    pipeline = DocumentPipeline(settings, backends=(backend,))
    document = pipeline.process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )

    exported = DatasetExporter(pipeline.store).export(
        document,
        tmp_path / "exports",
        policy=DatasetExportPolicy.STRICT_VERIFIED_ONLY,
    )

    assert document.pages[0].blocks[0].lines[0].verification_status is VerificationStatus.VERIFIED
    assert exported.manifest["counts"]["verified"] == 1
    assert exported.manifest["counts"]["exported_lines"] == 1
    assert list((exported.root / "pages" / "page_0001" / "lines" / "verified").glob("*.png"))


def test_manifest_contains_source_normalization_and_backend_provenance(tmp_path: Path) -> None:
    source_path = _source(tmp_path)
    settings = Settings(
        environment="test",
        storage_root=tmp_path / "artifacts",
        normalization=NormalizationConfig(digit_policy=DigitPolicy.ASCII),
    )
    pipeline = DocumentPipeline(settings, backends=(DeterministicBackend(),))
    document = pipeline.process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )

    exported = DatasetExporter(pipeline.store).export(document, tmp_path / "exports")
    manifest = exported.manifest

    assert manifest["source_filename"] == "source.png"
    assert manifest["source_sha256"] == document.source.checksum_sha256
    assert manifest["page_count"] == 1
    assert manifest["normalization_policy"] == settings.normalization.to_payload()
    assert manifest["ocr_backends"] == [
        {
            "backend": "test-backend",
            "model": "deterministic-test",
            "model_version": "1",
            "method": "ocr",
            "confidence_scale": "test-0-1",
        }
    ]
    assert manifest["processing_time_seconds"] is not None
    assert manifest["counts"]["accepted"] == 1
    assert manifest["artifacts"] == sorted(manifest["artifacts"], key=lambda item: item["path"])


def test_policy_and_format_identity_are_deterministic_for_page_only_exports(
    tmp_path: Path,
) -> None:
    source_path = _source(tmp_path)
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    pipeline = DocumentPipeline(settings, backends=(DeterministicBackend(),))
    document = pipeline.process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )
    exporter = DatasetExporter(pipeline.store)

    accepted = exporter.export(
        document,
        tmp_path / "exports",
        formats=("pages",),
        policy=DatasetExportPolicy.ACCEPTED_VERIFIED,
    )
    strict = exporter.export(
        document,
        tmp_path / "exports",
        formats=("pages",),
        policy=DatasetExportPolicy.STRICT_VERIFIED_ONLY,
    )

    assert accepted.root != strict.root
    assert accepted.manifest["artifacts"] == sorted(
        accepted.manifest["artifacts"], key=lambda item: item["path"]
    )
    assert any(
        item["path"] == "pages/page_0001/image.png" for item in accepted.manifest["artifacts"]
    )
    assert any(
        item["path"] == "pages/page_0001/page.json" for item in accepted.manifest["artifacts"]
    )


def test_typed_processing_manifest_preserves_phase8_provenance_fields() -> None:
    manifest = ProcessingManifest(
        document_id="doc-1",
        pipeline_version="0.1.0",
        schema_version="1.0.0",
        source_checksum="a" * 64,
        processing_checksum="b" * 64,
        configuration_hash="c" * 64,
        exporter_version="2.0.0",
        source_filename="source.png",
        source_content_type="image/png",
        source_byte_size=12,
        source_sha256="a" * 64,
        normalization_policy={"digit_policy": "persian"},
        page_count=1,
        ocr_backends=[
            {
                "backend": "test-backend",
                "model": "test-model",
                "model_version": "1",
                "method": "ocr",
                "confidence_scale": "test-0-1",
            }
        ],
        counts={"accepted": 1},
        export_policy="accepted_verified",
    )

    payload = manifest.model_dump(mode="json")
    assert payload["normalization_policy"]["digit_policy"] == "persian"
    assert payload["ocr_backends"][0]["model_version"] == "1"
    assert payload["counts"] == {"accepted": 1}


def test_exporter_rejects_traversal_artifact_uris(tmp_path: Path) -> None:
    exporter = DatasetExporter(LocalArtifactStore(tmp_path / "artifacts"))

    with pytest.raises(ArtifactStorageError, match="invalid artifact URI"):
        exporter._read_artifact_uri("artifact://doc-1/../source/original.bin")
