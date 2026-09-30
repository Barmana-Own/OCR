"""Optional OpenTelemetry-compatible spans with a metrics-only fallback."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .metrics import MetricsRegistry


@contextmanager
def trace_span(
    name: str,
    *,
    metrics: MetricsRegistry | None = None,
    tracer: Any = None,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> Iterator[None]:
    """Record a stage span without requiring an OpenTelemetry installation."""

    started = time.perf_counter()
    if tracer is None:
        try:
            yield
        except Exception:
            if metrics is not None:
                metrics.increment("stage_failures_total", labels={"stage": name})
            raise
        finally:
            if metrics is not None:
                metrics.observe(
                    "stage_latency_seconds",
                    time.perf_counter() - started,
                    labels={"stage": name},
                )
        return

    with tracer.start_as_current_span(name, attributes=dict(attributes or {})):
        try:
            yield
        except Exception:
            if metrics is not None:
                metrics.increment("stage_failures_total", labels={"stage": name})
            raise
        finally:
            if metrics is not None:
                metrics.observe(
                    "stage_latency_seconds",
                    time.perf_counter() - started,
                    labels={"stage": name},
                )
