"""Server-side API-key authentication for operational endpoints."""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import Header

from ocr_platform.config import Settings
from ocr_platform.errors import AuthenticationError, AuthorizationError


def build_api_key_dependency(settings: Settings) -> Callable[..., str]:
    async def require_api_key(
        x_ocr_api_key: str | None = Header(default=None, alias="X-OCR-API-Key"),
    ) -> str:
        if not settings.require_auth:
            return "anonymous"
        if not x_ocr_api_key:
            raise AuthenticationError()
        if not any(
            hmac.compare_digest(x_ocr_api_key, configured) for configured in settings.api_keys
        ):
            raise AuthorizationError()
        return "service"

    return require_api_key
