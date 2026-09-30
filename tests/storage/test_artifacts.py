import pytest

from ocr_platform.errors import ArtifactStorageError
from ocr_platform.storage import ArtifactLayout, LocalArtifactStore, sha256_bytes


def test_local_store_writes_and_reads_immutable_artifacts(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    artifact = store.put_bytes("doc-1", "source.bin", b"evidence")
    assert artifact.uri == "artifact://doc-1/source.bin"
    assert artifact.checksum_sha256 == sha256_bytes(b"evidence")
    assert store.read_bytes("doc-1", "source.bin") == b"evidence"
    with pytest.raises(ArtifactStorageError, match="already exists"):
        store.put_bytes("doc-1", "source.bin", b"changed")


@pytest.mark.parametrize(
    "document_id,artifact_name", [("../escape", "x"), ("doc-1", "../escape"), ("doc/1", "x")]
)
def test_local_store_rejects_traversal(document_id: str, artifact_name: str, tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    with pytest.raises(ArtifactStorageError):
        store.put_bytes(document_id, artifact_name, b"x")


def test_preprocessing_layout_names_are_deterministic_and_safe() -> None:
    layout = ArtifactLayout()

    assert layout.page_preprocessing_name(1, "tiny_text", 2, "grayscale", region_scale=3) == (
        "pages/page_0001/derived/tiny_text-3x-02-grayscale.png"
    )
    assert layout.page_preprocessing_manifest_name(1, "tiny_text", region_scale=3).endswith(
        "tiny_text-3x-manifest.json"
    )
    with pytest.raises(ValueError):
        layout.page_preprocessing_name(1, "../unsafe", 1, "grayscale")
