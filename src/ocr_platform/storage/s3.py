"""Optional S3-compatible artifact-store adapter for durable remote objects."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from ocr_platform.errors import ArtifactStorageError, BackendUnavailableError

from .artifacts import StoredArtifact

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class S3ArtifactStore:
    """Immutable artifact storage using an S3-compatible object API.

    ``cache_root`` is only a bounded local staging area required by the legacy
    ``StoredArtifact.path`` contract; object bytes remain authoritative in S3.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        prefix: str = "ocr",
        cache_root: Path | None = None,
        client=None,
    ) -> None:
        if not bucket or not _SAFE.fullmatch(bucket):
            raise ValueError("S3 bucket name is unsafe or empty")
        normalized_prefix = prefix.replace("\\", "/").strip("/")
        if normalized_prefix and any(
            not _SAFE.fullmatch(part) for part in normalized_prefix.split("/")
        ):
            raise ValueError("S3 prefix contains an unsafe path component")
        self.bucket = bucket
        self.prefix = normalized_prefix
        self.cache_root = (cache_root or Path(tempfile.gettempdir()) / "ocr-s3-cache").resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._endpoint_url = endpoint_url

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise BackendUnavailableError(
                "S3 artifact storage requires the optional 'distributed' extra"
            ) from exc
        self._client = boto3.client("s3", endpoint_url=self._endpoint_url)
        return self._client

    def _document_prefix(self, document_id: str) -> str:
        if not _SAFE.fullmatch(document_id):
            raise ArtifactStorageError("unsafe document id")
        return "/".join(part for part in (self.prefix, document_id) if part)

    def _key(self, document_id: str, artifact_name: str) -> str:
        prefix = self._document_prefix(document_id)
        parts = artifact_name.replace("\\", "/").split("/")
        if not parts or any(not _SAFE.fullmatch(part) for part in parts):
            raise ArtifactStorageError("unsafe artifact name")
        return "/".join((prefix, *parts))

    def _cache_path(self, document_id: str, artifact_name: str) -> Path:
        key = self._key(document_id, artifact_name)
        path = (self.cache_root / hashlib.sha256(key.encode()).hexdigest()).resolve()
        if self.cache_root not in path.parents:
            raise ArtifactStorageError("S3 cache path escapes cache root")
        return path

    def put_bytes(
        self,
        document_id: str,
        artifact_name: str,
        data: bytes,
        *,
        overwrite: bool = False,
    ) -> StoredArtifact:
        client = self._client_or_raise()
        key = self._key(document_id, artifact_name)
        if not overwrite and self.exists(document_id, artifact_name):
            raise ArtifactStorageError("artifact already exists")
        try:
            client.put_object(Bucket=self.bucket, Key=key, Body=data)
        except Exception as exc:
            raise ArtifactStorageError("unable to write S3 artifact") from exc
        return self._stored(document_id, artifact_name, data)

    def get(self, document_id: str, artifact_name: str) -> StoredArtifact:
        data = self.read_bytes(document_id, artifact_name)
        return self._stored(document_id, artifact_name, data)

    def read_bytes(self, document_id: str, artifact_name: str) -> bytes:
        client = self._client_or_raise()
        try:
            response = client.get_object(
                Bucket=self.bucket,
                Key=self._key(document_id, artifact_name),
            )
            return response["Body"].read()
        except Exception as exc:
            raise ArtifactStorageError("unable to read S3 artifact") from exc

    def read_uri(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ArtifactStorageError("S3 artifact URI does not belong to this store")
        key = uri[len(prefix) :]
        document_prefix = f"{self.prefix}/" if self.prefix else ""
        if document_prefix and not key.startswith(document_prefix):
            raise ArtifactStorageError("S3 artifact URI has an invalid prefix")
        relative = key[len(document_prefix) :] if document_prefix else key
        document_id, separator, artifact_name = relative.partition("/")
        if not separator or not document_id or not artifact_name:
            raise ArtifactStorageError("invalid S3 artifact URI")
        return self.read_bytes(document_id, artifact_name)

    def exists(self, document_id: str, artifact_name: str) -> bool:
        client = self._client_or_raise()
        try:
            client.head_object(Bucket=self.bucket, Key=self._key(document_id, artifact_name))
            return True
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise ArtifactStorageError("unable to inspect S3 artifact") from exc

    def delete_document(self, document_id: str) -> int:
        client = self._client_or_raise()
        prefix = f"{self._document_prefix(document_id)}/"
        try:
            deleted = 0
            continuation_token: str | None = None
            while True:
                request = {"Bucket": self.bucket, "Prefix": prefix}
                if continuation_token:
                    request["ContinuationToken"] = continuation_token
                response = client.list_objects_v2(**request)
                objects = [
                    {"Key": item["Key"]}
                    for item in response.get("Contents", [])
                ]
                if objects:
                    client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                    deleted += len(objects)
                if not response.get("IsTruncated"):
                    break
                continuation_token = response.get("NextContinuationToken")
                if not continuation_token:
                    raise ArtifactStorageError("S3 pagination response was incomplete")
            return deleted
        except Exception as exc:
            raise ArtifactStorageError("unable to delete S3 document artifacts") from exc

    def _stored(self, document_id: str, artifact_name: str, data: bytes) -> StoredArtifact:
        path = self._cache_path(document_id, artifact_name)
        path.write_bytes(data)
        checksum = hashlib.sha256(data).hexdigest()
        return StoredArtifact(
            uri=f"s3://{self.bucket}/{self._key(document_id, artifact_name)}",
            path=path,
            checksum_sha256=checksum,
            byte_size=len(data),
        )


__all__ = ["S3ArtifactStore"]
