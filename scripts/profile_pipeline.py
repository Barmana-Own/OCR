"""Profile bounded OCR pipeline costs across render DPI settings.

This utility runs the real ingestion/pipeline boundary with configured
adapters and reports model-independent timing and artifact costs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import tracemalloc
from pathlib import Path

from ocr_platform.config import Settings
from ocr_platform.config.settings import (
    DEFAULT_DEFAULT_DPI,
    DEFAULT_HIGH_QUALITY_DPI,
    DEFAULT_TINY_TEXT_DPI,
)
from ocr_platform.pipeline import DocumentPipeline


def _artifact_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _hardware_snapshot() -> dict[str, object]:
    snapshot: dict[str, object] = {"cpu": True, "gpu": "unavailable"}
    try:
        import torch

        if torch.cuda.is_available():
            snapshot["gpu"] = {
                "available": True,
                "device_count": torch.cuda.device_count(),
                "current_allocated_bytes": torch.cuda.memory_allocated(),
                "current_reserved_bytes": torch.cuda.memory_reserved(),
            }
    except Exception as exc:
        snapshot["gpu_error"] = type(exc).__name__
    return snapshot


def profile(source: Path, *, dpis: tuple[int, ...], output_root: Path) -> dict[str, object]:
    source_checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    measurements: list[dict[str, object]] = []
    for dpi in dpis:
        storage_root = output_root / f"dpi-{dpi}" / "artifacts"
        settings = Settings(
            environment="test",
            storage_root=storage_root,
            default_dpi=dpi,
            high_quality_dpi=max(dpi, DEFAULT_HIGH_QUALITY_DPI),
            tiny_text_dpi=max(dpi, DEFAULT_TINY_TEXT_DPI),
        )
        pipeline = DocumentPipeline(settings)
        tracemalloc.start()
        started = time.perf_counter()
        document = pipeline.process_path(
            source,
            filename=source.name,
            declared_content_type=None,
        )
        elapsed = time.perf_counter() - started
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append(
            {
                "dpi": dpi,
                "elapsed_seconds": elapsed,
                "peak_tracemalloc_bytes": peak_memory,
                "page_count": len(document.pages),
                "warning_count": len(document.warnings),
                "processing_status": document.processing_status.value,
                "artifact_bytes": _artifact_bytes(storage_root),
                "configuration_hash": settings.configuration_hash,
            }
        )
    return {
        "source_name": source.name,
        "source_sha256": source_checksum,
        "dpis": list(dpis),
        "hardware": _hardware_snapshot(),
        "measurements": measurements,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--dpi",
        dest="dpis",
        nargs="+",
        type=int,
        default=[DEFAULT_DEFAULT_DPI, DEFAULT_HIGH_QUALITY_DPI, DEFAULT_TINY_TEXT_DPI],
    )
    parser.add_argument("--output", type=Path, default=Path("var/profile-results.json"))
    args = parser.parse_args(argv)
    if not args.source.is_file():
        parser.error("source must be an existing file")
    if any(dpi <= 0 for dpi in args.dpis):
        parser.error("DPI values must be positive")
    result = profile(
        args.source,
        dpis=tuple(dict.fromkeys(args.dpis)),
        output_root=args.output.parent,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + chr(10),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
