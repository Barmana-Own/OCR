import io
import json
import logging

from ocr_platform.observability.logging import JsonFormatter, RedactionFilter, bind_log_context


def test_scoped_context_is_emitted_and_sensitive_extras_are_redacted() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger("phase2-observability")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    with bind_log_context(
        document_id="doc-1",
        job_id="job-1",
        page_number=2,
        block_id="block-3",
        backend="paddleocr",
        phase="ocr",
    ):
        logger.info("OCR started", extra={"raw_text": "sensitive document contents"})

    payload = json.loads(stream.getvalue())
    assert payload["document_id"] == "doc-1"
    assert payload["job_id"] == "job-1"
    assert payload["page_number"] == 2
    assert payload["block_id"] == "block-3"
    assert payload["backend"] == "paddleocr"
    assert payload["phase"] == "ocr"
    assert payload["raw_text"] == "[REDACTED]"

    stream.seek(0)
    stream.truncate(0)
    logger.info("outside scope")
    outside = json.loads(stream.getvalue())
    assert "document_id" not in outside


def test_nested_logging_context_restores_outer_values() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("phase2-observability-nested")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    with bind_log_context(document_id="doc-outer", phase="pipeline"):
        with bind_log_context(page_number=4, phase="ocr"):
            logger.info("inner")
        logger.info("outer")

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert records[0]["document_id"] == "doc-outer"
    assert records[0]["page_number"] == 4
    assert records[0]["phase"] == "ocr"
    assert records[1]["document_id"] == "doc-outer"
    assert "page_number" not in records[1]
    assert records[1]["phase"] == "pipeline"


def test_marked_sensitive_debug_messages_are_redacted() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger("phase11-sensitive-message")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info(
        "sensitive document text: شماره قرارداد ۱۲۳",
        extra={"sensitive_content": True},
    )

    payload = json.loads(stream.getvalue())
    assert payload["message"] == "[REDACTED]"
    assert "شماره قرارداد" not in stream.getvalue()
