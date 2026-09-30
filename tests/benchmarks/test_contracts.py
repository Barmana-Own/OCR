from __future__ import annotations

import pytest
from pydantic import ValidationError

from ocr_platform.benchmarks.models import (
    BenchmarkCategory,
    GroundTruthDataset,
    GroundTruthDocument,
    GroundTruthLine,
    GroundTruthPage,
)


def _line(*, line_id: str = "line-1", text: str = "سلام ۱۲۳ ABC") -> GroundTruthLine:
    return GroundTruthLine(
        id=line_id,
        raw_text=text,
        normalized_text=text,
        bbox=[10, 20, 300, 60],
        reading_order=1,
        review_label="accepted",
    )


def test_ground_truth_contract_preserves_mixed_script_and_serializes_geometry() -> None:
    page = GroundTruthPage(
        page_number=1,
        width=1000,
        height=1400,
        page_text="سلام ۱۲۳ ABC https://example.test/a?x=1",
        lines=[_line()],
    )
    dataset = GroundTruthDataset(
        schema_version="1.0.0",
        dataset_version="synthetic-1.0.0",
        documents=[
            GroundTruthDocument(
                document_id="doc-1",
                category=BenchmarkCategory.MIXED_PERSIAN_ENGLISH,
                source_uri="synthetic://doc-1",
                pages=[page],
            )
        ],
    )

    payload = dataset.model_dump(mode="json")

    assert payload["documents"][0]["pages"][0]["page_text"] == page.page_text
    assert payload["documents"][0]["pages"][0]["lines"][0]["raw_text"] == "سلام ۱۲۳ ABC"
    assert payload["documents"][0]["pages"][0]["lines"][0]["bbox"] == {
        "x0": 10.0,
        "y0": 20.0,
        "x1": 300.0,
        "y1": 60.0,
    }


def test_ground_truth_contract_rejects_geometry_outside_page() -> None:
    with pytest.raises(ValidationError, match="exceeds page reference dimensions"):
        GroundTruthPage(
            page_number=1,
            width=100,
            height=100,
            page_text="text",
            lines=[
                GroundTruthLine(
                    id="line-1",
                    raw_text="text",
                    bbox=[10, 20, 110, 40],
                    reading_order=1,
                )
            ],
        )
