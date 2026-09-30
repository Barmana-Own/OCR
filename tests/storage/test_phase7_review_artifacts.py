import pytest

from ocr_platform.storage import ArtifactLayout


def test_review_artifact_names_are_page_scoped_and_safe() -> None:
    layout = ArtifactLayout()

    assert (
        layout.page_review_name(2, "abc123", "json")
        == "pages/page_0002/reviews/abc123.json"
    )
    assert layout.page_review_name(2, "abc123-overlay", "png").endswith(".png")
    with pytest.raises(ValueError):
        layout.page_review_name(2, "../escape", "json")
    with pytest.raises(ValueError):
        layout.page_review_name(2, "safe", "../json")
