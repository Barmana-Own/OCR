from ocr_platform.config import Settings


def test_phase6_ocr_language_and_timeout_configuration_is_validated_and_hashed() -> None:
    first = Settings(ocr_languages=("fas", "eng"), ocr_backend_timeout_seconds=45)
    second = Settings(ocr_languages=("eng",), ocr_backend_timeout_seconds=45)

    assert first.ocr_languages == ("fas", "eng")
    assert first.ocr_backend_timeout_seconds == 45
    assert first.configuration_hash != second.configuration_hash

