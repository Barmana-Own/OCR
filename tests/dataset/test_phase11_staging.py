from pathlib import Path

import pytest
from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.dataset import DatasetExporter
from ocr_platform.errors import ArtifactStorageError
from ocr_platform.pipeline import DocumentPipeline
from ocr_platform.storage import LocalArtifactStore
from tests.integration.test_pipeline import DeterministicBackend


def _document(tmp_path: Path):
    source_path = tmp_path / "source.png"
    Image.new("RGB", (300, 150), "white").save(source_path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    return DocumentPipeline(settings, backends=(DeterministicBackend(),)).process_path(
        source_path,
        filename="source.png",
        declared_content_type="image/png",
    )


def test_export_staging_is_separate_from_durable_exports_and_cleaned(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    staging = tmp_path / "temporary-export-staging"
    exporter = DatasetExporter(
        LocalArtifactStore(tmp_path / "artifacts"),
        temporary_workspace=staging,
    )
    exported = exporter.export(document, tmp_path / "exports", formats=("json",))

    assert exported.root.is_dir()
    assert staging.is_dir()
    assert not list(staging.glob(".export-*"))


def test_failed_export_cleans_private_staging_directory(tmp_path: Path) -> None:
    document = _document(tmp_path)
    broken_page = document.pages[0].model_copy(
        update={"rendered_uri": f"artifact://{document.id}/pages/missing.png"}
    )
    broken_document = document.model_copy(update={"pages": [broken_page]})
    staging = tmp_path / "temporary-export-staging"
    exporter = DatasetExporter(
        LocalArtifactStore(tmp_path / "artifacts"),
        temporary_workspace=staging,
    )

    with pytest.raises(ArtifactStorageError):
        exporter.export(
            broken_document,
            tmp_path / "exports",
            formats=("pages",),
        )

    assert not list(staging.glob(".export-*"))
