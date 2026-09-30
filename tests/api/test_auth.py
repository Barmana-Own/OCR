import asyncio

import pytest

from ocr_platform.api.auth import build_api_key_dependency
from ocr_platform.config import Settings
from ocr_platform.errors import AuthenticationError, AuthorizationError


def test_api_key_dependency_rejects_missing_and_invalid_keys() -> None:
    dependency = build_api_key_dependency(
        Settings(environment="test", require_auth=True, api_keys=("secret",))
    )
    with pytest.raises(AuthenticationError):
        asyncio.run(dependency(None))
    with pytest.raises(AuthorizationError):
        asyncio.run(dependency("wrong"))


def test_api_key_dependency_accepts_configured_key() -> None:
    dependency = build_api_key_dependency(
        Settings(environment="test", require_auth=True, api_keys=("secret",))
    )
    assert asyncio.run(dependency("secret")) == "service"
