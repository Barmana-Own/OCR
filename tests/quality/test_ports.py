
from ocr_platform.quality import QualityEvaluator
from ocr_platform.tables import TableBackend, TableExtractionBackend


def test_provider_protocol_exports_are_stable() -> None:
    assert QualityEvaluator.__name__ == "QualityEvaluator"
    assert TableBackend is TableExtractionBackend
