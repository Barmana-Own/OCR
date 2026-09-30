"""Immutable, traversal-safe local artifact storage."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ocr_platform.errors import ArtifactStorageError

if TYPE_CHECKING:
    from .ports import ArtifactStore

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactStorageError("unable to read source artifact") from exc
    return digest.hexdigest()


def _safe_component(value: str, label: str) -> str:
    if not _SAFE_COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise ArtifactStorageError(f"unsafe {label}")
    return value


def _safe_artifact_parts(value: str) -> tuple[str, ...]:
    if not value or value.startswith(("/", "\\")) or ":" in value:
        raise ArtifactStorageError("unsafe artifact name")
    components = tuple(value.replace("\\", "/").split("/"))
    if not components or any(not component for component in components):
        raise ArtifactStorageError("unsafe artifact name")
    return tuple(_safe_component(component, "artifact name") for component in components)


def _is_reparse_or_symlink(path: Path, metadata: os.stat_result | None = None) -> bool:
    metadata = path.lstat() if metadata is None else metadata
    selected_mode = metadata.st_mode
    if stat.S_ISLNK(selected_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & 0x400)


def _count_and_validate_private_tree(root: Path) -> int:
    """Validate a private tree before deletion and return its regular-file count."""

    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise ArtifactStorageError("unable to inspect private artifact tree") from exc
    if _is_reparse_or_symlink(root, root_metadata) or not stat.S_ISDIR(
        root_metadata.st_mode
    ):
        raise ArtifactStorageError("private artifact tree is not a regular directory")

    files = 0
    directories = [root]
    try:
        while directories:
            directory = directories.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    entry_path = Path(entry.path)
                    metadata = entry.stat(follow_symlinks=False)
                    if _is_reparse_or_symlink(entry_path, metadata):
                        raise ArtifactStorageError(
                            "private artifact tree contains a link or reparse point"
                        )
                    if stat.S_ISDIR(metadata.st_mode):
                        directories.append(entry_path)
                    elif stat.S_ISREG(metadata.st_mode):
                        files += 1
                    else:
                        raise ArtifactStorageError(
                            "private artifact tree contains an unsupported file type"
                        )
    except ArtifactStorageError:
        raise
    except OSError as exc:
        raise ArtifactStorageError("unable to inspect private artifact tree") from exc
    return files


def safe_delete_private_tree(root: Path, child_name: str, *, label: str) -> int:
    """Delete one validated private child tree without following links."""

    safe_name = _safe_component(child_name, f"{label} name")
    resolved_root = root.resolve()
    child = resolved_root / safe_name
    if child.resolve(strict=False).parent != resolved_root:
        raise ArtifactStorageError(f"{label} path escapes its root")
    file_count = _count_and_validate_private_tree(child)
    if file_count == 0 and not child.exists():
        return 0
    try:
        metadata = child.lstat()
        if _is_reparse_or_symlink(child, metadata):
            raise ArtifactStorageError(f"{label} tree contains a link or reparse point")
        shutil.rmtree(child)
    except ArtifactStorageError:
        raise
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise ArtifactStorageError(f"unable to delete {label}") from exc
    return file_count


@dataclass(frozen=True)
class StoredArtifact:
    uri: str
    path: Path
    checksum_sha256: str
    byte_size: int


def parse_artifact_uri(uri: str) -> tuple[str, str]:
    prefix = "artifact://"
    if not uri.startswith(prefix):
        raise ArtifactStorageError("invalid artifact URI")
    remainder = uri[len(prefix) :]
    document_id, separator, artifact_name = remainder.partition("/")
    if not separator or not document_id or not artifact_name:
        raise ArtifactStorageError("invalid artifact URI")
    _safe_component(document_id, "document id")
    _safe_artifact_parts(artifact_name)
    return document_id, artifact_name.replace("\\", "/")


def read_artifact_uri(store: ArtifactStore, uri: str) -> bytes:
    document_id, artifact_name = parse_artifact_uri(uri)
    return store.read_bytes(document_id, artifact_name)


class LocalArtifactStore:
    """Stores sources and derived artifacts beneath one configured root.

    Artifact names may contain safe forward-slash-separated directories. Every
    component is validated, writes are atomic, and the original source remains
    a separate immutable artifact from derived page/crop outputs.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, document_id: str, artifact_name: str) -> Path:
        safe_document_id = _safe_component(document_id, "document id")
        safe_parts = _safe_artifact_parts(artifact_name)
        path = (self.root / safe_document_id / Path(*safe_parts)).resolve()
        if self.root not in path.parents:
            raise ArtifactStorageError("artifact path escapes storage root")
        return path

    def put_bytes(
        self, document_id: str, artifact_name: str, data: bytes, *, overwrite: bool = False
    ) -> StoredArtifact:
        path = self._resolve(document_id, artifact_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite:
            raise ArtifactStorageError("artifact already exists")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".write-", delete=False
            ) as handle:
                handle.write(data)
                temporary_path = Path(handle.name)
            os.replace(temporary_path, path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ArtifactStorageError("unable to write artifact") from exc
        return StoredArtifact(
            uri=f"artifact://{document_id}/{artifact_name.replace(chr(92), '/')}",
            path=path,
            checksum_sha256=sha256_bytes(data),
            byte_size=len(data),
        )

    def get(self, document_id: str, artifact_name: str) -> StoredArtifact:
        path = self._resolve(document_id, artifact_name)
        normalized_name = artifact_name.replace(chr(92), "/")
        if not path.is_file():
            raise ArtifactStorageError("artifact does not exist")
        try:
            return StoredArtifact(
                uri=f"artifact://{document_id}/{normalized_name}",
                path=path,
                checksum_sha256=sha256_file(path),
                byte_size=path.stat().st_size,
            )
        except OSError as exc:
            raise ArtifactStorageError("unable to inspect artifact") from exc

    def read_bytes(self, document_id: str, artifact_name: str) -> bytes:
        path = self.get(document_id, artifact_name).path
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ArtifactStorageError("unable to read artifact") from exc

    def exists(self, document_id: str, artifact_name: str) -> bool:
        return self._resolve(document_id, artifact_name).is_file()

    def delete_document(self, document_id: str) -> int:
        """Delete all private artifacts for one document and return file count."""

        return safe_delete_private_tree(
            self.root,
            document_id,
            label="document artifact",
        )
