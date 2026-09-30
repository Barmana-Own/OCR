import pytest

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError


def test_verification_defaults_are_bounded_and_part_of_configuration_hash() -> None:
    settings = Settings(environment="test")

    assert settings.verification_max_candidates >= settings.verification_min_consensus_candidates
    assert settings.verification_require_consensus_for_verified is True
    assert settings.verification_max_suspicious_char_rate <= 1
    assert settings.verification_min_image_quality <= 1
    assert len(settings.configuration_hash) == 64
    assert settings.configuration_hash != Settings(
        environment="test", verification_max_candidates=settings.verification_max_candidates + 1
    ).configuration_hash


def test_verification_thresholds_and_attempt_bounds_are_validated() -> None:
    with pytest.raises(ConfigurationError, match="verification threshold"):
        Settings(environment="test", confidence_threshold=0.95, verification_threshold=0.90)
    with pytest.raises(ConfigurationError, match="maximum verification candidates"):
        Settings(environment="test", verification_max_candidates=0)
    with pytest.raises(ConfigurationError, match="consensus candidates"):
        Settings(environment="test", verification_min_consensus_candidates=0)
    with pytest.raises(ConfigurationError, match="suspicious ratio"):
        Settings(environment="test", verification_max_suspicious_char_rate=1.1)


def test_verification_environment_overrides_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_VERIFICATION_MAX_CANDIDATES", "9")
    monkeypatch.setenv("OCR_VERIFICATION_MIN_CONSENSUS_CANDIDATES", "3")
    monkeypatch.setenv("OCR_VERIFICATION_REQUIRE_CONSENSUS", "false")
    monkeypatch.setenv("OCR_BACKEND_CONFIDENCE_THRESHOLDS", "a:0.70,b:0.91")

    settings = Settings.from_env()

    assert settings.verification_max_candidates == 9
    assert settings.verification_min_consensus_candidates == 3
    assert settings.verification_require_consensus_for_verified is False
    assert settings.backend_confidence_thresholds == (("a", 0.70), ("b", 0.91))
