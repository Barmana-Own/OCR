import pytest

from ocr_platform.observability.metrics import MetricsRegistry
from ocr_platform.observability.tracing import trace_span


def test_metrics_snapshot_is_deterministic_and_content_free() -> None:
    metrics = MetricsRegistry(max_series=4)
    metrics.increment("documents_processed_total")
    metrics.observe("stage_latency_seconds", 0.25, labels={"stage": "ocr"})

    assert metrics.snapshot() == {
        "counters": [
            {
                "labels": {},
                "name": "documents_processed_total",
                "value": 1,
            }
        ],
        "summaries": [
            {
                "count": 1,
                "labels": {"stage": "ocr"},
                "max": 0.25,
                "min": 0.25,
                "name": "stage_latency_seconds",
                "sum": 0.25,
            }
        ],
    }


def test_metrics_reject_sensitive_labels_and_bound_series() -> None:
    metrics = MetricsRegistry(max_series=1)
    with pytest.raises(ValueError):
        metrics.increment("documents_processed_total", labels={"raw_text": "secret"})
    with pytest.raises(ValueError):
        metrics.increment("documents_processed_total", labels={"stage": "document text"})
    metrics.increment("documents_processed_total")
    metrics.increment("other_total")
    assert len(metrics.snapshot()["counters"]) == 1


def test_trace_span_records_latency_and_failures() -> None:
    metrics = MetricsRegistry()
    with trace_span("render", metrics=metrics):
        pass
    with pytest.raises(RuntimeError), trace_span("ocr", metrics=metrics):
        raise RuntimeError("backend failure")

    snapshot = metrics.snapshot()
    assert any(item["labels"] == {"stage": "render"} for item in snapshot["summaries"])
    assert snapshot["counters"] == [
        {"name": "stage_failures_total", "labels": {"stage": "ocr"}, "value": 1}
    ]
