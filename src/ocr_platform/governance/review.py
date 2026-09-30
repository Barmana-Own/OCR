"""Audited human correction workflow over immutable OCR evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from ocr_platform.domain import Document, ReviewCorrection, VerificationStatus
from ocr_platform.errors import InvalidDocumentError
from ocr_platform.utils import stable_hash


class ReviewCorrectionService:
    """Apply a correction as a new revision without replacing ``raw_text``."""

    def correct(
        self,
        document: Document,
        *,
        target_id: str,
        corrected_text: str,
        reviewer_id: str,
        reason: str,
    ) -> Document:
        if not target_id or not reviewer_id or not reason:
            raise InvalidDocumentError("review target, reviewer, and reason are required")
        if not corrected_text.strip():
            raise InvalidDocumentError("corrected text must not be empty")
        timestamp = datetime.now(UTC)
        pages = []
        found = False
        for page in document.pages:
            blocks = []
            for block in page.blocks:
                lines = []
                for line in block.lines:
                    if line.id != target_id:
                        lines.append(line)
                        continue
                    found = True
                    revision = ReviewCorrection(
                        id="review-" + stable_hash(
                            {
                                "document_id": document.id,
                                "target_id": target_id,
                                "reviewer_id": reviewer_id,
                                "corrected_text": corrected_text,
                                "created_at": timestamp.isoformat(),
                            }
                        )[:32],
                        document_id=document.id,
                        target_id=target_id,
                        target_type="line",
                        reviewer_id=reviewer_id,
                        previous_corrected_text=line.corrected_text,
                        corrected_text=corrected_text,
                        raw_text_unchanged=line.raw_text,
                        reason=reason,
                        created_at=timestamp,
                    )
                    lines.append(
                        line.model_copy(
                            update={
                                "corrected_text": corrected_text,
                                "correction_history": [*line.correction_history, revision],
                                "needs_review": False,
                                "uncertainty_flags": [],
                                "reason_codes": [],
                                "verification_status": VerificationStatus.VERIFIED,
                            }
                        )
                    )
                cells = []
                for cell in block.table_cells:
                    if cell.id != target_id:
                        cells.append(cell)
                        continue
                    found = True
                    revision = ReviewCorrection(
                        id="review-" + stable_hash(
                            {
                                "document_id": document.id,
                                "target_id": target_id,
                                "reviewer_id": reviewer_id,
                                "corrected_text": corrected_text,
                                "created_at": timestamp.isoformat(),
                            }
                        )[:32],
                        document_id=document.id,
                        target_id=target_id,
                        target_type="table_cell",
                        reviewer_id=reviewer_id,
                        previous_corrected_text=cell.corrected_text,
                        corrected_text=corrected_text,
                        raw_text_unchanged=cell.raw_text,
                        reason=reason,
                        created_at=timestamp,
                    )
                    cells.append(
                        cell.model_copy(
                            update={
                                "corrected_text": corrected_text,
                                "correction_history": [*cell.correction_history, revision],
                                "needs_review": False,
                                "uncertainty_flags": [],
                                "reason_codes": [],
                                "verification_status": VerificationStatus.VERIFIED,
                            }
                        )
                    )
                blocks.append(block.model_copy(update={"lines": lines, "table_cells": cells}))
            pages.append(page.model_copy(update={"blocks": blocks}))
        if not found:
            raise InvalidDocumentError("review target was not found")
        return document.model_copy(update={"pages": pages})


__all__ = ["ReviewCorrectionService"]
