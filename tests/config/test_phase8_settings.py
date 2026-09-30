import pytest

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError
from ocr_platform.normalization import (
    DigitPolicy,
    NormalizationConfig,
    UnicodeNormalizationForm,
    WhitespacePolicy,
)


def test_normalization_policy_is_in_configuration_payload_and_hash() -> None:
    default = Settings(environment="test")
    ascii_digits = Settings(
        environment="test",
        normalization=NormalizationConfig(digit_policy=DigitPolicy.ASCII),
    )

    assert default.configuration_payload["normalization"] == default.normalization.to_payload()
    assert default.configuration_hash != ascii_digits.configuration_hash


def test_normalization_environment_overrides_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_NORMALIZATION_DIGIT_POLICY", "ascii")
    monkeypatch.setenv("OCR_NORMALIZATION_UNICODE_FORM", "nfkc")
    monkeypatch.setenv("OCR_NORMALIZATION_WHITESPACE_POLICY", "collapse")
    monkeypatch.setenv("OCR_NORMALIZATION_TRIM_LINE_EDGES", "false")

    settings = Settings.from_env()

    assert settings.normalization.digit_policy is DigitPolicy.ASCII
    assert settings.normalization.unicode_form is UnicodeNormalizationForm.NFKC
    assert settings.normalization.whitespace_policy is WhitespacePolicy.COLLAPSE
    assert settings.normalization.trim_line_edges is False


def test_invalid_normalization_environment_value_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_NORMALIZATION_DIGIT_POLICY", "invalid")

    with pytest.raises(ConfigurationError, match="digit policy"):
        Settings.from_env()
