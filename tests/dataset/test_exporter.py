from pathlib import Path

from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.dataset import DatasetExporter
from ocr_platform.pipeline import DocumentPipeline
from tests.integration.test_pipeline import DeterministicBackend


def test_dataset_export_is_versioned_and_reusable(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (300, 150), "white").save(source_path, format="PNG")
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")
    pipeline = DocumentPipeline(settings, backends=(DeterministicBackend(),))
    document = pipeline.process_path(
        source_path, filename="source.png", declared_content_type="image/png"
    )
    exporter = DatasetExporter(pipeline.store)

    first = exporter.export(document, tmp_path / "exports")
    second = exporter.export(document, tmp_path / "exports")

    assert first.root == second.root
    assert (first.root / "document.json").is_file()
    assert (first.root / "document.txt").is_file()
    assert (first.root / "document.md").is_file()
    assert first.manifest["processing_checksum"] == document.processing_checksum
    assert (first.root / "page-images").is_dir()
    assert list((first.root / "page-images").glob("*.png"))
    assert (first.root / "line-crops").is_dir()
    assert list((first.root / "labels").glob("*.json"))
