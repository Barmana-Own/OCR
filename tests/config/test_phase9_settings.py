import pytest

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError


def test_processing_mode_environment_overrides_are_hashed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_MODE_MAX_RETRIES", "fast:0,balanced:1,accurate:5")
    monkeypatch.setenv("OCR_MODE_HIGH_QUALITY_RETRY", "fast:false,balanced:false,accurate:true")

    settings = Settings.from_env()

    assert dict(settings.mode_max_retries)["accurate"] == 5
    assert dict(settings.mode_enable_high_quality_retry)["balanced"] is False
    assert settings.configuration_hash != Settings().configuration_hash


def test_processing_mode_environment_requires_all_known_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_MODE_MAX_RETRIES", "fast:0,balanced:1")

    with pytest.raises(ConfigurationError, match="mode retry policy"):
        Settings.from_env()
