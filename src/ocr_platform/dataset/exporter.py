"""Deterministic canonical and training-artifact exports.

The exporter deliberately keeps the canonical document complete while applying
an explicit eligibility policy to human-consumable text and crop artifacts.
That prevents uncertain recognition from being silently promoted to labels.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from ocr_platform.domain import (
    CoordinateSpace,
    Document,
    Line,
    Page,
    ReviewFlag,
    TableCellResult,
    VerificationReason,
    VerificationStatus,
)
from ocr_platform.errors import ArtifactStorageError, InvalidDocumentError
from ocr_platform.storage import ArtifactStore, sha256_bytes, sha256_file

_ALLOWED_FORMATS = frozenset({"json", "txt", "md", "pages", "crops"})
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REVIEW_STATUSES = frozenset(
    {
        VerificationStatus.UNCERTAIN,
        VerificationStatus.HUMAN_REVIEW_REQUIRED,
        VerificationStatus.FAILED,
    }
)
_BLOCKING_EXPORT_FLAGS = frozenset(
    set(ReviewFlag)
    - {ReviewFlag.LOW_CONFIDENCE, ReviewFlag.TINY_TEXT}
)
_BLOCKING_EXPORT_REASONS = frozenset(
    {
        VerificationReason.BACKEND_DISAGREEMENT,
        VerificationReason.NORMALIZED_DISAGREEMENT,
        VerificationReason.DIGIT_DISAGREEMENT,
        VerificationReason.PUNCTUATION_DIFFERENCE,
        VerificationReason.CONFIDENCE_SCALE_MISMATCH,
        VerificationReason.EMPTY_TEXT,
        VerificationReason.SHORT_TEXT,
        VerificationReason.SUSPICIOUS_CHARACTERS,
        VerificationReason.LANGUAGE_SCRIPT_MISMATCH,
        VerificationReason.EXPECTED_FORMAT_MISMATCH,
        VerificationReason.LOW_IMAGE_QUALITY,
        VerificationReason.RETRY_EXHAUSTED,
        VerificationReason.BACKEND_FAILURE,
        VerificationReason.STORAGE_FAILURE,
    }
)


class DatasetExportPolicy(StrEnum):
    """Controls which recognition records are eligible for derived labels."""

    STRICT_VERIFIED_ONLY = "strict_verified_only"
    ACCEPTED_VERIFIED = "accepted_verified"
    ALL_WITH_STATUS = "all_with_status"


# Short alias for callers that prefer the generic name.
ExportPolicy = DatasetExportPolicy


@dataclass(frozen=True)
class DatasetExport:
    root: Path
    manifest_path: Path
    manifest: dict[str, object]
    policy: DatasetExportPolicy = DatasetExportPolicy.ACCEPTED_VERIFIED


class DatasetExporter:
    """Write a versioned export through a provider-neutral artifact store."""

    exporter_version = "2.0.0"

    def __init__(
        self,
        store: ArtifactStore,
        *,
        temporary_workspace: Path | None = None,
    ) -> None:
        self.store = store
        self.temporary_workspace = temporary_workspace

    def export(
        self,
        document: Document,
        destination: Path,
        *,
        formats: Iterable[str] = ("json", "txt", "md", "pages", "crops"),
        policy: DatasetExportPolicy | str = DatasetExportPolicy.ACCEPTED_VERIFIED,
    ) -> DatasetExport:
        selected_formats = tuple(dict.fromkeys(formats))
        unknown = set(selected_formats) - _ALLOWED_FORMATS
        if unknown:
            raise InvalidDocumentError(f"unsupported export format: {sorted(unknown)}")
        try:
            selected_policy = DatasetExportPolicy(policy)
        except ValueError as exc:
            raise InvalidDocumentError(f"unsupported export policy: {policy}") from exc
        if not _SAFE_COMPONENT.fullmatch(document.id) or document.id in {".", ".."}:
            raise InvalidDocumentError("document id is unsafe for dataset export")

        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        target = (
            destination
            / document.id
            / f"export-{document.processing_checksum[:16]}-{selected_policy.value}"
        )
        manifest_path = target / "manifest.json"
        if target.exists():
            if not manifest_path.is_file():
                raise ArtifactStorageError("existing export is missing its manifest")
            try:
                existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ArtifactStorageError("existing export has an invalid manifest") from exc
            existing_formats = set(existing_manifest.get("formats", ()))
            if existing_manifest.get("export_policy") != selected_policy.value:
                raise ArtifactStorageError("existing export uses a different export policy")
            if not set(selected_formats).issubset(existing_formats):
                raise ArtifactStorageError("existing export does not contain all requested formats")
            return DatasetExport(target, manifest_path, existing_manifest, selected_policy)

        staging_root = (
            self.temporary_workspace
            if self.temporary_workspace is not None
            else destination.parent / ".export-staging"
        ).resolve()
        if staging_root.anchor.lower() != destination.anchor.lower():
            staging_root = destination.parent / ".export-staging"
        if (
            staging_root == destination
            or staging_root in destination.parents
            or destination in staging_root.parents
        ):
            raise ArtifactStorageError(
                "export staging workspace must be outside durable export output"
            )
        try:
            staging_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactStorageError("unable to create export staging workspace") from exc
        temporary = Path(tempfile.mkdtemp(prefix=".export-", dir=staging_root))
        try:
            files: list[Path] = []
            if "json" in selected_formats:
                files.append(self._write_json(temporary, document))
            if "txt" in selected_formats:
                files.append(self._write_text(temporary, document, selected_policy))
            if "md" in selected_formats:
                files.append(self._write_markdown(temporary, document, selected_policy))
            if "pages" in selected_formats:
                files.extend(self._write_pages(temporary, document, selected_policy))
            if "crops" in selected_formats:
                files.extend(self._write_crops(temporary, document, selected_policy))
            files = self._unique_paths(files)
            manifest = self._manifest(
                document, selected_formats, selected_policy, files, temporary
            )
            manifest_file = temporary / "manifest.json"
            manifest_file.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, target)
            return DatasetExport(target, target / "manifest.json", manifest, selected_policy)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _unique_paths(files: list[Path]) -> list[Path]:
        unique: dict[Path, Path] = {}
        for path in files:
            unique[path.resolve()] = path
        return sorted(unique.values(), key=lambda item: str(item).replace(os.sep, "/"))

    @staticmethod
    def _write_json(root: Path, document: Document) -> Path:
        path = root / "document.json"
        path.write_text(
            json.dumps(document.canonical_dict(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def _write_text(
        cls,
        root: Path,
        document: Document,
        policy: DatasetExportPolicy,
    ) -> Path:
        path = root / "document.txt"
        page_text: list[str] = []
        for page in document.pages:
            entries: list[str] = []
            for block in sorted(page.blocks, key=lambda item: item.reading_order):
                if block.table_cells:
                    rows: dict[int, list[str]] = {}
                    for cell in sorted(block.table_cells, key=lambda item: (item.row, item.column)):
                        if cls._eligible(cell, policy):
                            rows.setdefault(cell.row, []).append(
                                cls._text_for_export(
                                    cell.raw_text,
                                    cell.verification_status,
                                    policy,
                                    corrected_text=cell.corrected_text,
                                    needs_review=cell.needs_review,
                                )
                            )
                    entries.extend(" | ".join(rows[row]) for row in sorted(rows))
                    continue
                for line in sorted(block.lines, key=lambda item: item.reading_order):
                    if cls._eligible(line, policy):
                        entries.append(
                            cls._text_for_export(
                                line.raw_text,
                                line.verification_status,
                                policy,
                                corrected_text=line.corrected_text,
                                needs_review=line.needs_review,
                            )
                        )
            page_text.append("\n".join(entries))
        path.write_text("\f\n".join(page_text) + "\n", encoding="utf-8")
        return path

    @classmethod
    def _write_markdown(
        cls,
        root: Path,
        document: Document,
        policy: DatasetExportPolicy,
    ) -> Path:
        path = root / "document.md"
        content = [f"# Document {document.id}", "", f"- Status: {document.status.value}", ""]
        for page in document.pages:
            content.extend([f"## Page {page.page_number}", ""])
            for block in sorted(page.blocks, key=lambda item: item.reading_order):
                content.extend([f"### Block {block.id} ({block.block_type.value})", ""])
                if block.table_cells:
                    content.extend(
                        ["| Row | Column | Text | Status |", "| ---: | ---: | --- | --- |"]
                    )
                    for cell in sorted(block.table_cells, key=lambda item: (item.row, item.column)):
                        if cls._eligible(cell, policy):
                            text = cls._escape_markdown(
                                cell.corrected_text or cell.raw_text
                            )
                            if policy is DatasetExportPolicy.ALL_WITH_STATUS:
                                status_label = cls._status_label(
                                    cell.verification_status,
                                    cell.needs_review,
                                )
                                text = f"[{status_label}] {text}"
                            content.append(
                                f"| {cell.row} | {cell.column} | {text} | "
                                f"{cell.verification_status.value} |"
                            )
                    content.append("")
                    continue
                for line in sorted(block.lines, key=lambda item: item.reading_order):
                    if cls._eligible(line, policy):
                        text = cls._escape_markdown(line.corrected_text or line.raw_text)
                        if policy is DatasetExportPolicy.ALL_WITH_STATUS:
                            status_label = cls._status_label(
                                line.verification_status,
                                line.needs_review,
                            )
                            text = f"[{status_label}] {text}"
                        content.append(
                            f"- {line.reading_order} [{line.verification_status.value}] {text}"
                        )
                content.append("")
        path.write_text("\n".join(content).rstrip() + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _escape_markdown(value: str) -> str:
        return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")

    @staticmethod
    def _text_for_export(
        raw_text: str,
        status: VerificationStatus,
        policy: DatasetExportPolicy,
        *,
        corrected_text: str | None = None,
        needs_review: bool = False,
    ) -> str:
        text = corrected_text or raw_text
        if policy is DatasetExportPolicy.ALL_WITH_STATUS:
            return f"[{DatasetExporter._status_label(status, needs_review)}] {text}"
        return text

    @staticmethod
    def _status_label(status: VerificationStatus, needs_review: bool) -> str:
        return f"{status.value};review" if needs_review else status.value

    @staticmethod
    def _eligible(
        item: Line | TableCellResult | VerificationStatus,
        policy: DatasetExportPolicy,
        needs_review: bool | None = None,
        reason_codes: Iterable[VerificationReason] = (),
    ) -> bool:
        if isinstance(item, VerificationStatus):
            status = item
            item_needs_review = bool(needs_review)
            item_flags: Iterable[ReviewFlag] = ()
            item_reason_codes = tuple(reason_codes)
        else:
            status = item.verification_status
            item_needs_review = item.needs_review if needs_review is None else (
                item.needs_review or needs_review
            )
            item_flags = item.uncertainty_flags
            item_reason_codes = tuple(item.reason_codes)

        if policy is DatasetExportPolicy.ALL_WITH_STATUS:
            return True
        if item_needs_review or status in _REVIEW_STATUSES:
            return False
        if DatasetExporter._has_blocking_uncertainty(
            status,
            item_flags,
            item_reason_codes,
        ):
            return False
        if policy is DatasetExportPolicy.STRICT_VERIFIED_ONLY:
            return status is VerificationStatus.VERIFIED
        if policy is DatasetExportPolicy.ACCEPTED_VERIFIED:
            return status in {VerificationStatus.ACCEPTED, VerificationStatus.VERIFIED}
        return False

    @staticmethod
    def _has_blocking_uncertainty(
        status: VerificationStatus,
        flags: Iterable[ReviewFlag],
        reason_codes: Iterable[VerificationReason],
    ) -> bool:
        normalized_flags = set(flags)
        normalized_reasons = set(reason_codes)
        independent = VerificationReason.INDEPENDENT_BACKEND_CONSENSUS in normalized_reasons
        if normalized_flags & _BLOCKING_EXPORT_FLAGS:
            return True
        if normalized_flags & {ReviewFlag.LOW_CONFIDENCE, ReviewFlag.TINY_TEXT} and not (
            status is VerificationStatus.VERIFIED and independent
        ):
            return True
        if normalized_reasons & _BLOCKING_EXPORT_REASONS:
            return True
        if normalized_reasons & {
            VerificationReason.LOW_PRIMARY_CONFIDENCE,
            VerificationReason.TINY_TEXT,
        } and not (status is VerificationStatus.VERIFIED and independent):
            return True
        return status is VerificationStatus.VERIFIED and bool(
            normalized_reasons.intersection(
                {
                    VerificationReason.INSUFFICIENT_INDEPENDENT_EVIDENCE,
                    VerificationReason.CORRELATED_EVIDENCE_ONLY,
                    VerificationReason.INSUFFICIENT_EVIDENCE,
                }
            )
        )

    def _write_pages(
        self,
        root: Path,
        document: Document,
        policy: DatasetExportPolicy,
    ) -> list[Path]:
        page_root = root / "page-images"
        page_root.mkdir(parents=True, exist_ok=True)
        outputs: list[Path] = []
        for page in document.pages:
            outputs.extend(self._write_structured_page(root, document, page, policy))
            if page.rendered_uri:
                image_bytes = self._read_artifact_uri(page.rendered_uri)
                page_path = page_root / f"page-{page.page_number:04d}.png"
                page_path.write_bytes(image_bytes)
                outputs.append(page_path)
        return outputs

    def _write_structured_page(
        self,
        root: Path,
        document: Document,
        page: Page,
        policy: DatasetExportPolicy,
    ) -> list[Path]:
        page_number = page.page_number
        page_directory = root / "pages" / f"page_{page_number:04d}"
        page_directory.mkdir(parents=True, exist_ok=True)
        image_path = page_directory / "image.png"
        outputs: list[Path] = []
        image_metadata: dict[str, object] | None = None
        if page.rendered_uri:
            image_bytes = self._read_artifact_uri(page.rendered_uri)
            image_path.write_bytes(image_bytes)
            outputs.append(image_path)
            image_metadata = {
                "path": image_path.relative_to(root).as_posix(),
                "artifact_uri": page.rendered_uri,
                "checksum_sha256": sha256_bytes(image_bytes),
                "bytes": len(image_bytes),
                "width": page.rendered_width,
                "height": page.rendered_height,
                "coordinate_space": CoordinateSpace.RENDERED_PIXEL.value,
            }
        page_manifest = page_directory / "page.json"
        page_payload = page.model_dump(mode="json")
        if policy is not DatasetExportPolicy.ALL_WITH_STATUS:
            for block_payload, block in zip(page_payload["blocks"], page.blocks, strict=True):
                block_payload["lines"] = [
                    line_payload
                    for line_payload, line in zip(
                        block_payload["lines"], block.lines, strict=True
                    )
                    if self._eligible(line, policy)
                ]
                block_payload["table_cells"] = [
                    cell_payload
                    for cell_payload, cell in zip(
                        block_payload["table_cells"], block.table_cells, strict=True
                    )
                    if self._eligible(cell, policy)
                ]
        page_manifest.write_text(
            json.dumps(
                {
                    "document_id": document.id,
                    "page_number": page_number,
                    "page": page_payload,
                    "image": image_metadata,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        outputs.append(page_manifest)
        return outputs

    def _write_crops(
        self,
        root: Path,
        document: Document,
        policy: DatasetExportPolicy,
    ) -> list[Path]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise ArtifactStorageError("Pillow is required for crop export") from exc
        crop_root = root / "line-crops"
        label_root = root / "labels"
        crop_root.mkdir(parents=True, exist_ok=True)
        label_root.mkdir(parents=True, exist_ok=True)
        outputs: list[Path] = []
        for page in document.pages:
            if not page.rendered_uri:
                continue
            structured_outputs = self._write_structured_page(root, document, page, policy)
            outputs.extend(structured_outputs)
            image_bytes = self._read_artifact_uri(page.rendered_uri)
            try:
                from io import BytesIO

                image = Image.open(BytesIO(image_bytes)).convert("RGB")
            except Exception as exc:
                raise ArtifactStorageError("rendered page could not be decoded for crops") from exc
            for block in page.blocks:
                for line in block.lines:
                    if not self._eligible(line, policy):
                        continue
                    if line.source.coordinate_space != CoordinateSpace.RENDERED_PIXEL:
                        continue
                    box = self._pixel_box(line.bbox.as_list(), image.width, image.height)
                    if box[2] <= box[0] or box[3] <= box[1]:
                        continue
                    status_directory = (
                        root
                        / "pages"
                        / f"page_{page.page_number:04d}"
                        / "lines"
                        / line.verification_status.value
                    )
                    status_directory.mkdir(parents=True, exist_ok=True)
                    safe_line_id = self._safe_line_id(line.id)
                    crop_path = status_directory / f"{safe_line_id}.png"
                    image.crop(box).save(crop_path, format="PNG", optimize=False)
                    label = self._line_label(document, page, line, box, crop_path, root)
                    structured_label_path = crop_path.with_suffix(".json")
                    self._write_label(structured_label_path, label)
                    outputs.extend([crop_path, structured_label_path])

                    legacy_stem = self._legacy_line_stem(line.id, page.page_number, crop_root)
                    legacy_crop_path = crop_root / f"{legacy_stem}.png"
                    legacy_label_path = label_root / f"{legacy_stem}.json"
                    image.crop(box).save(legacy_crop_path, format="PNG", optimize=False)
                    self._write_label(legacy_label_path, label)
                    outputs.extend([legacy_crop_path, legacy_label_path])
        return outputs

    @staticmethod
    def _pixel_box(bbox: list[float], width: int, height: int) -> tuple[int, int, int, int]:
        return (
            max(0, math.floor(bbox[0])),
            max(0, math.floor(bbox[1])),
            min(width, math.ceil(bbox[2])),
            min(height, math.ceil(bbox[3])),
        )

    @staticmethod
    def _safe_line_id(line_id: str) -> str:
        if not _SAFE_COMPONENT.fullmatch(line_id) or line_id in {".", ".."}:
            raise InvalidDocumentError("line id is unsafe for dataset export")
        return line_id

    @staticmethod
    def _legacy_line_stem(line_id: str, page_number: int, crop_root: Path) -> str:
        stem = DatasetExporter._safe_line_id(line_id)
        if not (crop_root / f"{stem}.png").exists() and not (crop_root / f"{stem}.json").exists():
            return stem
        return f"page-{page_number:04d}--{stem}"

    @staticmethod
    def _line_label(
        document: Document,
        page: Page,
        line: Line,
        pixel_box: tuple[int, int, int, int],
        crop_path: Path,
        root: Path,
    ) -> dict[str, object]:
        return {
            "document_id": document.id,
            "page_number": page.page_number,
            "page_image_path": f"pages/page_{page.page_number:04d}/image.png",
            "source_page_uri": page.source_uri,
            "rendered_page_uri": page.rendered_uri,
            "line_id": line.id,
            "raw_text": line.raw_text,
            "normalized_text": line.normalized_text,
            "corrected_text": line.corrected_text,
            "effective_text": line.corrected_text or line.raw_text,
            "bbox": line.bbox.as_list(),
            "polygon": (
                [point.model_dump(mode="json") for point in line.polygon]
                if line.polygon
                else None
            ),
            "coordinate_space": line.source.coordinate_space.value,
            "confidence": line.confidence,
            "language": line.language,
            "script": line.script,
            "text_type": line.text_type.value,
            "reading_order": line.reading_order,
            "verification_status": line.verification_status.value,
            "needs_review": line.needs_review,
            "selected_candidate_id": line.selected_candidate_id,
            "tiny_text": line.tiny_text,
            "uncertainty_flags": [flag.value for flag in line.uncertainty_flags],
            "reason_codes": [reason.value for reason in line.reason_codes],
            "review_artifact_uri": line.review_artifact_uri,
            "source": line.source.model_dump(mode="json"),
            "extraction": line.extraction.model_dump(mode="json"),
            "candidates": [candidate.model_dump(mode="json") for candidate in line.candidates],
            "verification_history": [
                attempt.model_dump(mode="json") for attempt in line.verification_history
            ],
            "correction_history": [
                correction.model_dump(mode="json")
                for correction in line.correction_history
            ],
            "crop": {
                "page_bbox": line.bbox.as_list(),
                "pixel_bbox": list(pixel_box),
                "coordinate_space": line.source.coordinate_space.value,
                "page_dimensions": {"width": page.width, "height": page.height},
                "rendered_page_dimensions": {
                    "width": page.rendered_width,
                    "height": page.rendered_height,
                },
                "dataset_path": crop_path.relative_to(root).as_posix(),
            },
        }

    @staticmethod
    def _write_label(path: Path, label: dict[str, object]) -> None:
        path.write_text(
            json.dumps(label, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _read_artifact_uri(self, uri: str) -> bytes:
        prefix = "artifact://"
        if not uri.startswith(prefix):
            raise ArtifactStorageError("crop source is not an artifact URI")
        remainder = uri[len(prefix) :]
        document_id, separator, artifact_name = remainder.partition("/")
        if not separator or not document_id or not artifact_name:
            raise ArtifactStorageError("invalid artifact URI")
        if not _SAFE_COMPONENT.fullmatch(document_id) or document_id in {".", ".."}:
            raise ArtifactStorageError("invalid artifact URI")
        if artifact_name.startswith(("/", "\\")) or ":" in artifact_name:
            raise ArtifactStorageError("invalid artifact URI")
        normalized_name = artifact_name.replace("\\", "/")
        components = normalized_name.split("/")
        if any(
            not _SAFE_COMPONENT.fullmatch(component) or component in {".", ".."}
            for component in components
        ):
            raise ArtifactStorageError("invalid artifact URI")
        return self.store.read_bytes(document_id, normalized_name)

    @classmethod
    def _manifest(
        cls,
        document: Document,
        formats: tuple[str, ...],
        policy: DatasetExportPolicy,
        files: list[Path],
        root: Path,
    ) -> dict[str, object]:
        artifact_entries = [
            {
                "path": str(path.relative_to(root)).replace(os.sep, "/"),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(files, key=lambda item: str(item).replace(os.sep, "/"))
        ]
        lines = [
            line
            for page in document.pages
            for block in page.blocks
            for line in block.lines
        ]
        cells = [
            cell
            for page in document.pages
            for block in page.blocks
            for cell in block.table_cells
        ]
        line_counts = Counter(line.verification_status.value for line in lines)
        cell_counts = Counter(cell.verification_status.value for cell in cells)
        exported_lines = sum(
            cls._eligible(line, policy) for line in lines
        )
        exported_cells = sum(
            cls._eligible(cell, policy) for cell in cells
        )
        counts: dict[str, int] = {
            "pages": len(document.pages),
            "lines": len(lines),
            "table_cells": len(cells),
            "accepted": line_counts[VerificationStatus.ACCEPTED.value],
            "verified": line_counts[VerificationStatus.VERIFIED.value],
            "uncertain": line_counts[VerificationStatus.UNCERTAIN.value],
            "human_review_required": line_counts[VerificationStatus.HUMAN_REVIEW_REQUIRED.value],
            "failed": line_counts[VerificationStatus.FAILED.value],
            "review_required": sum(line_counts[status.value] for status in _REVIEW_STATUSES),
            "exported_lines": exported_lines,
            "exported_table_cells": exported_cells,
        }
        backends = cls._backend_inventory(lines, cells)
        duration = cls._duration_seconds(
            document.processing_started_at,
            document.processing_finished_at,
        )
        warnings = list(document.warnings)
        warnings.extend(
            warning.message
            for warning in document.processing_warnings
            if warning.message not in warnings
        )
        return {
            "manifest_version": "2.0.0",
            "exporter_version": cls.exporter_version,
            "document_id": document.id,
            "source_filename": document.source.filename,
            "source_content_type": document.source.content_type,
            "source_byte_size": document.source.byte_size,
            "source_checksum": document.source.checksum_sha256,
            "source_sha256": document.source.checksum_sha256,
            "pipeline_version": document.pipeline_version,
            "schema_version": document.schema_version,
            "processing_checksum": document.processing_checksum,
            "configuration_hash": document.configuration_hash,
            "normalization_policy": document.normalization_policy,
            "processing_started_at": document.processing_started_at.isoformat(),
            "processing_finished_at": (
                document.processing_finished_at.isoformat()
                if document.processing_finished_at
                else None
            ),
            "processing_time_seconds": duration,
            "page_count": len(document.pages),
            "ocr_backends": backends,
            "model_identifiers": [
                f"{item['backend']}:{item['model']}@{item['model_version']}" for item in backends
            ],
            "warnings": warnings,
            "counts": counts,
            "line_counts": dict(sorted(line_counts.items())),
            "table_cell_counts": dict(sorted(cell_counts.items())),
            "export_policy": policy.value,
            "formats": list(formats),
            "artifacts": artifact_entries,
            "artifact_references": artifact_entries,
        }

    @staticmethod
    def _duration_seconds(
        started_at: datetime,
        finished_at: datetime | None,
    ) -> float | None:
        if finished_at is None:
            return None
        duration = finished_at - started_at
        if not isinstance(duration, timedelta):
            return None
        return max(0.0, duration.total_seconds())

    @staticmethod
    def _backend_inventory(
        lines: list[Line], cells: list[TableCellResult]
    ) -> list[dict[str, str]]:
        inventory: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
        for item in [*lines, *cells]:
            extraction = item.extraction
            key = (
                extraction.backend,
                extraction.model,
                extraction.model_version,
                extraction.method.value,
                extraction.confidence_scale,
            )
            inventory[key] = {
                "backend": extraction.backend,
                "model": extraction.model,
                "model_version": extraction.model_version,
                "method": extraction.method.value,
                "confidence_scale": extraction.confidence_scale,
            }
        return [inventory[key] for key in sorted(inventory)]
