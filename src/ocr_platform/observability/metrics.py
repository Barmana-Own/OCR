"""Bounded, content-free in-process metrics for local and single-node runs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SAFE_LABEL = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_LABEL_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SENSITIVE_LABEL_WORDS = ("text", "content", "token", "secret", "password", "image")


@dataclass(frozen=True)
class _Summary:
    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None


class MetricsRegistry:
    """Thread-safe bounded counters and summaries with deterministic snapshots."""

    def __init__(self, *, max_series: int = 1024) -> None:
        if max_series <= 0:
            raise ValueError("max_series must be positive")
        self.max_series = max_series
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        self._summaries: dict[tuple[str, tuple[tuple[str, str], ...]], _Summary] = {}
        self._lock = RLock()

    @staticmethod
    def _key(
        name: str, labels: Mapping[str, str | int | float | bool] | None
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("metric name is unsafe")
        selected: list[tuple[str, str]] = []
        for key, value in (labels or {}).items():
            if not _SAFE_LABEL.fullmatch(key):
                raise ValueError("metric label name is unsafe")
            if any(word in key.lower() for word in _SENSITIVE_LABEL_WORDS):
                raise ValueError("sensitive metric labels are not allowed")
            text = str(value)
            if not _SAFE_LABEL_VALUE.fullmatch(text):
                raise ValueError("metric label value is unsafe")
            selected.append((key, text))
        return name, tuple(sorted(selected))

    def increment(
        self,
        name: str,
        value: int = 1,
        *,
        labels: Mapping[str, str | int | float | bool] | None = None,
    ) -> None:
        if value < 0:
            raise ValueError("metric increments cannot be negative")
        key = self._key(name, labels)
        with self._lock:
            if (
                key not in self._counters
                and key not in self._summaries
                and len(self._counters) + len(self._summaries) >= self.max_series
            ):
                return
            self._counters[key] = self._counters.get(key, 0) + value

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str | int | float | bool] | None = None,
    ) -> None:
        if value < 0:
            raise ValueError("metric observations cannot be negative")
        key = self._key(name, labels)
        with self._lock:
            if (
                key not in self._summaries
                and key not in self._counters
                and len(self._counters) + len(self._summaries) >= self.max_series
            ):
                return
            current = self._summaries.get(key, _Summary())
            self._summaries[key] = _Summary(
                count=current.count + 1,
                total=current.total + value,
                minimum=value if current.minimum is None else min(current.minimum, value),
                maximum=value if current.maximum is None else max(current.maximum, value),
            )

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        with self._lock:
            counters = [
                {
                    "name": name,
                    "labels": dict(labels),
                    "value": value,
                }
                for (name, labels), value in sorted(self._counters.items())
            ]
            summaries = [
                {
                    "name": name,
                    "labels": dict(labels),
                    "count": summary.count,
                    "sum": summary.total,
                    "min": summary.minimum,
                    "max": summary.maximum,
                }
                for (name, labels), summary in sorted(self._summaries.items())
            ]
        return {"counters": counters, "summaries": summaries}
