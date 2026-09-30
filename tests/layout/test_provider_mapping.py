import pytest

from ocr_platform.errors import ConfigurationError
from ocr_platform.layout import PaddleStructureLayoutBackend, build_layout_backend


def test_optional_paddle_adapter_is_explicit_when_runtime_is_unavailable() -> None:
    backend = PaddleStructureLayoutBackend()

    if backend.available:
        assert backend.name == "paddle-pp-structure"
    else:
        assert "paddle" in backend.unavailable_reason.lower()


def test_unknown_layout_backend_fails_as_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        build_layout_backend("not-a-real-layout-backend")
