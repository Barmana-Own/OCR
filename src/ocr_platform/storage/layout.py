"""Deterministic artifact naming for document workspaces."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactLayout:
    """Namespaced artifact paths beneath ``<document_id>/``."""

    source_name: str = "source/original.bin"
    manifest_name: str = "manifests/processing.json"

    @staticmethod
    def page_directory(page_number: int) -> str:
        if page_number <= 0:
            raise ValueError("page number must be positive")
        return f"pages/page_{page_number:04d}"

    def page_render_name(self, page_number: int, dpi: int) -> str:
        if dpi <= 0:
            raise ValueError("DPI must be positive")
        return f"{self.page_directory(page_number)}/original_render_{dpi}dpi.png"

    def page_derived_name(self, page_number: int, variant: str) -> str:
        if not variant or "/" in variant or "\\" in variant:
            raise ValueError("preprocessing variant must be a single safe name")
        return f"{self.page_directory(page_number)}/derived/{variant}.png"

    def page_crop_name(self, page_number: int, crop_id: str, extension: str = "png") -> str:
        if not crop_id or "/" in crop_id or "\\" in crop_id:
            raise ValueError("crop id must be a single safe name")
        if not extension or "/" in extension or "\\" in extension:
            raise ValueError("extension must be a single safe name")
        return f"{self.page_directory(page_number)}/crops/{crop_id}.{extension.lstrip('.')}"

    def page_review_name(
        self, page_number: int, review_id: str, extension: str = "json"
    ) -> str:
        if not _safe_token(review_id):
            raise ValueError("review id must be a safe single token")
        if not _safe_token(extension):
            raise ValueError("review extension must be a safe single token")
        return f"{self.page_directory(page_number)}/reviews/{review_id}.{extension}"

    def page_preprocessing_name(
        self,
        page_number: int,
        profile: str,
        step_index: int,
        operation: str,
        *,
        region_scale: int = 1,
    ) -> str:
        if not _safe_token(profile) or not _safe_token(operation):
            raise ValueError("preprocessing names must be safe single tokens")
        if step_index <= 0 or region_scale <= 0:
            raise ValueError("preprocessing step and scale must be positive")
        return (
            f"{self.page_directory(page_number)}/derived/"
            f"{profile}-{region_scale}x-{step_index:02d}-{operation}.png"
        )

    def page_preprocessing_manifest_name(
        self, page_number: int, profile: str, *, region_scale: int = 1
    ) -> str:
        if not _safe_token(profile) or region_scale <= 0:
            raise ValueError("preprocessing manifest name is invalid")
        return (
            f"{self.page_directory(page_number)}/derived/"
            f"{profile}-{region_scale}x-manifest.json"
        )


def _safe_token(value: str) -> bool:
    return value not in {".", ".."} and bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
    )

