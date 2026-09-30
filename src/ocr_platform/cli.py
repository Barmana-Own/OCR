"""Small CLI wrapper around the pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocr_platform.config import get_settings
from ocr_platform.observability.logging import configure_logging
from ocr_platform.pipeline import DocumentPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Process a document through the OCR pipeline.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--filename", default=None)
    parser.add_argument("--content-type", default=None)
    args = parser.parse_args()
    configure_logging()
    document = DocumentPipeline(get_settings()).process_path(
        args.path,
        filename=args.filename or args.path.name,
        declared_content_type=args.content_type,
    )
    print(json.dumps(document.canonical_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
