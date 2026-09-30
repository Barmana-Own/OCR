from pathlib import Path

import pytest

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError
from ocr_platform.governance import RetentionClass


def test_settings_expose_safe_retention_defaults_without_secret_hash_inputs() -> None:
    settings = Settings(environment="test", api_keys=("secret-value",))

    assert settings.retention_policy.seconds_for(RetentionClass.ORIGINAL_SOURCE) > 0
    assert settings.allow_sensitive_debug_logging is False
    assert "secret-value" not in str(settings.configuration_payload)


def test_settings_parse_retention_and_export_staging_overrides(monkeypatch) -> None:
    monkeypatch.setenv("OCR_RETENTION_TEMPORARY_SECONDS", "11")
    monkeypatch.setenv("OCR_RETENTION_SOURCE_SECONDS", "22")
    monkeypatch.setenv("OCR_RETENTION_DERIVED_SECONDS", "33")
    monkeypatch.setenv("OCR_RETENTION_VERIFIED_DATASET_SECONDS", "44")
    monkeypatch.setenv("OCR_EXPORT_STAGING_WORKSPACE", "var/phase11-exports")

    settings = Settings.from_env()

    assert settings.retention_policy.temporary_seconds == 11
    assert settings.retention_policy.source_seconds == 22
    assert settings.retention_policy.derived_seconds == 33
    assert settings.retention_policy.verified_dataset_seconds == 44
    assert settings.export_staging_workspace == Path("var/phase11-exports")


def test_sensitive_debug_logging_is_development_only() -> None:
    with pytest.raises(ConfigurationError, match="sensitive debug"):
        Settings(
            environment="production",
            require_auth=True,
            api_keys=("runtime-secret",),
            allow_sensitive_debug_logging=True,
        )
