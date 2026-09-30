"""Structured JSON logging with scoped processing context and conservative redaction."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

_request_id: ContextVar[str] = ContextVar("ocr_request_id", default="-")


@dataclass(frozen=True, slots=True)
class LogContext:
    """Correlation fields shared by API, worker, and processing logs."""

    document_id: str | None = None
    job_id: str | None = None
    page_number: int | None = None
    block_id: str | None = None
    backend: str | None = None
    phase: str | None = None

    def as_dict(self) -> dict[str, str | int]:
        return {
            key: value
            for key, value in {
                "document_id": self.document_id,
                "job_id": self.job_id,
                "page_number": self.page_number,
                "block_id": self.block_id,
                "backend": self.backend,
                "phase": self.phase,
            }.items()
            if value is not None
        }


_log_context: ContextVar[LogContext | None] = ContextVar("ocr_log_context", default=None)
_UNSET = object()
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "token",
        "password",
        "secret",
        "raw_text",
        "normalized_text",
        "text",
        "document_bytes",
        "image_bytes",
        "document_content",
        "document_text",
        "ocr_text",
        "sensitive_content",
    }
)
_SAFE_EXTRA_KEYS = frozenset(
    {"event", "error_code", "status_code", "retryable", "duration_ms", "attempt", "artifact_uri"}
)


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_log_context() -> LogContext:
    return _log_context.get() or LogContext()


@contextmanager
def bind_log_context(
    *,
    document_id: str | None | object = _UNSET,
    job_id: str | None | object = _UNSET,
    page_number: int | None | object = _UNSET,
    block_id: str | None | object = _UNSET,
    backend: str | None | object = _UNSET,
    phase: str | None | object = _UNSET,
) -> Iterator[LogContext]:
    """Temporarily bind processing fields and restore the prior scope safely."""

    if (
        page_number is not _UNSET
        and page_number is not None
        and (not isinstance(page_number, int) or page_number <= 0)
    ):
        raise ValueError("page_number must be a positive integer")
    values = {
        key: value
        for key, value in {
            "document_id": document_id,
            "job_id": job_id,
            "page_number": page_number,
            "block_id": block_id,
            "backend": backend,
            "phase": phase,
        }.items()
        if value is not _UNSET
    }
    current = get_log_context()
    token = _log_context.set(replace(current, **values))
    try:
        yield _log_context.get()
    finally:
        _log_context.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sensitive_message = any(
            key in record.__dict__
            for key in {
                "raw_text",
                "normalized_text",
                "text",
                "document_text",
                "ocr_text",
                "sensitive_content",
            }
        )
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": "[REDACTED]" if sensitive_message else record.getMessage(),
            "request_id": _request_id.get(),
        }
        payload.update(get_log_context().as_dict())
        for key in _SENSITIVE_KEYS:
            if key in record.__dict__:
                payload[key] = "[REDACTED]"
        for key in _SAFE_EXTRA_KEYS:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key in _SENSITIVE_KEYS:
            if key in record.__dict__:
                record.__dict__[key] = "[REDACTED]"
        if any(
            key in record.__dict__
            for key in {
                "raw_text",
                "normalized_text",
                "text",
                "document_text",
                "ocr_text",
                "sensitive_content",
            }
        ):
            record.msg = "[REDACTED]"
            record.args = ()
        return True


def configure_logging(
    level: str | None = None,
    *,
    allow_sensitive_debug_logging: bool = False,
) -> None:
    selected = (level or os.getenv("OCR_LOG_LEVEL", "INFO")).upper()
    if allow_sensitive_debug_logging and selected == "INFO":
        selected = "DEBUG"
    root = logging.getLogger()
    root.setLevel(selected)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.addFilter(RedactionFilter())
        root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)



