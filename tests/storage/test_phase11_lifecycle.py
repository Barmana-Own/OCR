from pathlib import Path

import pytest

from ocr_platform.errors import ArtifactStorageError
from ocr_platform.storage import LocalArtifactStore


def test_document_artifacts_can_be_deleted_without_touching_another_document(
    tmp_path: Path,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    store.put_bytes("doc-a", "uploads/source.bin", b"source")
    store.put_bytes("doc-a", "pages/page.png", b"page")
    store.put_bytes("doc-b", "uploads/source.bin", b"other")

    deleted_files = store.delete_document("doc-a")

    assert deleted_files == 2
    assert not (tmp_path / "artifacts" / "doc-a").exists()
    assert store.read_bytes("doc-b", "uploads/source.bin") == b"other"


def test_document_artifact_deletion_rejects_unsafe_ids(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStorageError, match="unsafe"):
        store.delete_document("../outside")
