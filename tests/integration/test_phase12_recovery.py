from pathlib import Path

import fitz

from ocr_platform.config import Settings
from ocr_platform.domain import ProcessingStatus, ReviewFlag, VerificationStatus
from ocr_platform.errors import ProcessingError
from ocr_platform.pipeline import DocumentPipeline


def test_one_page_failure_preserves_other_pages_and_marks_warning(tmp_path: Path) -> None:
    source = tmp_path / "two-pages.pdf"
    document = fitz.open()
    document.new_page(width=200, height=200).insert_text((20, 40), "page one")
    document.new_page(width=200, height=200).insert_text((20, 40), "page two")
    document.save(source)
    document.close()

    pipeline = DocumentPipeline(
        Settings(environment="test", storage_root=tmp_path / "artifacts"),
        backends=(),
    )
    original = pipeline._process_page

    def fail_second_page(*args, **kwargs):
        page_input = args[2]
        if page_input.page_number == 2:
            raise ProcessingError("page backend failed", retryable=True)
        return original(*args, **kwargs)

    pipeline._process_page = fail_second_page
    result = pipeline.process_path(
        source,
        filename="two-pages.pdf",
        declared_content_type="application/pdf",
    )

    assert len(result.pages) == 2
    assert result.pages[0].blocks
    assert result.pages[1].page_flags == [ReviewFlag.BACKEND_FAILURE]
    assert result.processing_status is ProcessingStatus.COMPLETED_WITH_WARNINGS
    assert result.status is VerificationStatus.HUMAN_REVIEW_REQUIRED
    assert any("page 2 processing failed" in warning for warning in result.warnings)
