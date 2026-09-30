import pytest

from ocr_platform.config import Settings


def test_phase6_ocr_language_and_timeout_configuration_is_validated_and_hashed() -> None:
    first = Settings(ocr_languages=("fas", "eng"), ocr_backend_timeout_seconds=45)
    second = Settings(ocr_languages=("eng",), ocr_backend_timeout_seconds=45)

    assert first.ocr_languages == ("fas", "eng")
    assert first.ocr_backend_timeout_seconds == 45
    assert first.configuration_hash != second.configuration_hash


def test_htr_model_configuration_is_explicit_and_hashed(monkeypatch) -> None:
    monkeypatch.setenv("OCR_HANDWRITING_BACKEND", "transformers")
    monkeypatch.setenv("OCR_HANDWRITING_MODEL_ID", "org/validated-htr")
    monkeypatch.setenv("OCR_HANDWRITING_PROCESSOR_ID", "org/validated-processor")
    monkeypatch.setenv("OCR_HANDWRITING_REVISION", "revision-1")
    monkeypatch.setenv("OCR_HANDWRITING_LOCAL_FILES_ONLY", "false")
    monkeypatch.setenv("OCR_HANDWRITING_TRUST_REMOTE_CODE", "true")
    monkeypatch.setenv("OCR_HANDWRITING_MAX_GENERATION_LENGTH", "73")
    monkeypatch.setenv("OCR_HANDWRITING_LANGUAGE", "und")
    monkeypatch.setenv("OCR_HANDWRITING_SCRIPT", "Unknown")
    monkeypatch.setenv("OCR_HANDWRITING_FALLBACK_TO_PRINTED", "true")

    settings = Settings.from_env()

    assert settings.handwriting_backend == "transformers"
    assert settings.handwriting_model_id == "org/validated-htr"
    assert settings.handwriting_processor_id == "org/validated-processor"
    assert settings.handwriting_revision == "revision-1"
    assert settings.handwriting_local_files_only is False
    assert settings.handwriting_trust_remote_code is True
    assert settings.handwriting_max_generation_length == 73
    assert settings.handwriting_fallback_to_printed is True
    assert settings.configuration_payload["handwriting_model_id"] == "org/validated-htr"


def test_htr_generation_length_is_bounded() -> None:
    from ocr_platform.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="generation length"):
        Settings(environment="test", handwriting_max_generation_length=0)

    with pytest.raises(ConfigurationError, match="generation length"):
        Settings(environment="test", handwriting_max_generation_length=4097)

