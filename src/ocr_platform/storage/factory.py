"""Explicit artifact-store construction for local and distributed deployments."""

from __future__ import annotations

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError

from .artifacts import LocalArtifactStore
from .ports import ArtifactStore
from .s3 import S3ArtifactStore


def build_artifact_store(settings: Settings) -> ArtifactStore:
    if settings.artifact_store_backend == "local":
        return LocalArtifactStore(settings.storage_root)
    if settings.artifact_store_backend == "s3":
        return S3ArtifactStore(
            bucket=settings.artifact_bucket,
            endpoint_url=settings.s3_endpoint_url,
            prefix=settings.s3_prefix,
            cache_root=settings.cache_path / "s3",
        )
    raise ConfigurationError("unsupported artifact store backend")


__all__ = ["build_artifact_store"]
