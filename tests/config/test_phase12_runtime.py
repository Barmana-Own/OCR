from pathlib import Path

import pytest

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError


def test_runtime_settings_are_configurable_and_hashed_without_paths() -> None:
    settings = Settings(
        environment="test",
        storage_root=Path("private-artifacts"),
        device="cpu",
        model_load_mode="startup",
        gpu_inference_concurrency=2,
        max_pages_in_flight=3,
    )

    assert settings.device == "cpu"
    assert settings.model_load_mode == "startup"
    assert settings.configuration_payload["gpu_inference_concurrency"] == 2
    assert "private-artifacts" not in str(settings.configuration_payload)


def test_runtime_environment_overrides_are_validated(monkeypatch) -> None:
    monkeypatch.setenv("OCR_DEVICE", "cpu")
    monkeypatch.setenv("OCR_MODEL_LOAD_MODE", "startup")
    monkeypatch.setenv("OCR_GPU_INFERENCE_CONCURRENCY", "4")
    monkeypatch.setenv("OCR_MAX_PAGES_IN_FLIGHT", "2")

    settings = Settings.from_env()

    assert settings.device == "cpu"
    assert settings.model_load_mode == "startup"
    assert settings.gpu_inference_concurrency == 4
    assert settings.max_pages_in_flight == 2


def test_invalid_runtime_device_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="device"):
        Settings(environment="test", device="npu")
