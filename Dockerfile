ARG PYTHON_BASE_IMAGE=python:3.12-slim
ARG OCR_EXTRAS=""
FROM ${PYTHON_BASE_IMAGE} AS runtime
ARG OCR_EXTRAS=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OCR_ENVIRONMENT=production \
    OCR_STORAGE_ROOT=/var/lib/ocr-platform/artifacts \
    OCR_TEMPORARY_WORKSPACE=/var/lib/ocr-platform/tmp \
    OCR_EXPORT_STAGING_WORKSPACE=/var/lib/ocr-platform/tmp/exports \
    OCR_MODEL_PATH=/var/lib/ocr-platform/models \
    OCR_CACHE_PATH=/var/lib/ocr-platform/cache \
    OCR_DEVICE=auto \
    OCR_MODEL_LOAD_MODE=lazy \
    OCR_GPU_INFERENCE_CONCURRENCY=1 \
    OCR_MAX_PAGES_IN_FLIGHT=1 \
    OCR_PROCESSING_TIMEOUT_SECONDS=300 \
    OCR_MAX_UPLOAD_BYTES=52428800 \
    OCR_MAX_RENDER_PIXELS=50000000

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN if [ -n "${OCR_EXTRAS}" ]; then \
        python -m pip install --no-cache-dir --no-compile ".[${OCR_EXTRAS}]"; \
    else \
        python -m pip install --no-cache-dir --no-compile .; \
    fi \
    && useradd --create-home --uid 10001 ocr \
    && mkdir -p /var/lib/ocr-platform/artifacts /var/lib/ocr-platform/tmp \
        /var/lib/ocr-platform/models /var/lib/ocr-platform/cache \
    && chown -R ocr:ocr /app /var/lib/ocr-platform

USER ocr
EXPOSE 8000
VOLUME [
    "/var/lib/ocr-platform/artifacts",
    "/var/lib/ocr-platform/tmp",
    "/var/lib/ocr-platform/models",
    "/var/lib/ocr-platform/cache"
]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["uvicorn", "ocr_platform.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
