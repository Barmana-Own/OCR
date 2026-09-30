"""Provider-neutral artifact storage contract."""

from __future__ import annotations

from typing import Protocol

from .artifacts import StoredArtifact


class ArtifactStore(Protocol):
    """Immutable artifact operations required by application services."""

    def put_bytes(
        self,
        document_id: str,
        artifact_name: str,
        data: bytes,
        *,
        overwrite: bool = False,
    ) -> StoredArtifact: ...

    def get(self, document_id: str, artifact_name: str) -> StoredArtifact: ...

    def read_bytes(self, document_id: str, artifact_name: str) -> bytes: ...

    def exists(self, document_id: str, artifact_name: str) -> bool: ...

    def delete_document(self, document_id: str) -> int: ...
