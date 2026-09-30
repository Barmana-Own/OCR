"""Real Tesseract CLI adapter.

The adapter is optional. If the executable is absent, it raises a typed
backend-unavailable error instead of returning a guessed or placeholder string.
"""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ocr_platform.domain import ExtractionMethod, TextType
from ocr_platform.errors import BackendUnavailableError, ProcessingError

from ..models import BackendTextLine, BackendWord, OcrRegion, OcrResult


class TesseractBackend:
    name = "tesseract"
    model = "tesseract-lstm"
    model_version = "external"
    confidence_scale = "tesseract_0_100"
    backend_family = "tesseract"

    def __init__(
        self,
        *,
        executable: str = "tesseract",
        language: str = "eng",
        timeout_seconds: int = 120,
    ) -> None:
        if not language or any(not part for part in language.split("+")):
            raise ValueError("Tesseract language selection must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("Tesseract timeout must be positive")
        self.executable = executable
        self.language = language
        self.timeout_seconds = timeout_seconds
        self._resolved_executable: str | None = shutil.which(executable)

    @property
    def available(self) -> bool:
        return self._resolved_executable is not None

    def recognize(
        self,
        image_bytes: bytes,
        *,
        region: OcrRegion,
        dpi: int,
        region_scale: int,
        preprocess_variant: str,
    ) -> OcrResult:
        if not self._resolved_executable:
            raise BackendUnavailableError("Tesseract executable is not installed")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(image_bytes)
                temporary_path = Path(handle.name)
            command = [
                self._resolved_executable,
                str(temporary_path),
                "stdout",
                "--psm",
                "6",
                "-l",
                self.language,
                "tsv",
            ]
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if completed.returncode != 0:
                raise ProcessingError("Tesseract failed to process the image", retryable=True)
            lines = self._parse_tsv(completed.stdout)
            stderr = completed.stderr.strip()
            return OcrResult(
                backend=self.name,
                model=self.model,
                model_version=self.model_version,
                method=ExtractionMethod.OCR,
                confidence_scale=self.confidence_scale,
                dpi=float(dpi),
                region_scale=float(region_scale),
                preprocess_variant=preprocess_variant,
                lines=tuple(lines),
                runtime_metadata=(
                    ("executable", self._resolved_executable),
                    ("language", self.language),
                    ("timeout_seconds", str(self.timeout_seconds)),
                    ("model_identifier", self.model),
                ),
                warnings=(f"tesseract: {stderr[:512]}",) if stderr else (),
                backend_family=self.backend_family,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError("Tesseract timed out", retryable=True) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _parse_tsv(payload: str) -> list[BackendTextLine]:
        reader = csv.DictReader(payload.splitlines(), delimiter="\t")
        grouped: dict[tuple[str, str, str, str, str], list[tuple[dict[str, str], str]]] = {}
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            key = (
                row.get("block_num", "0"),
                row.get("par_num", "0"),
                row.get("line_num", "0"),
                row.get("page_num", "0"),
                row.get("level", "0"),
            )
            grouped.setdefault(key, []).append((row, text))
        result: list[BackendTextLine] = []
        for _, entries in enumerate(grouped.values()):
            boxes: list[tuple[int, int, int, int]] = []
            words: list[BackendWord] = []
            raw_words: list[str] = []
            confidences: list[float] = []
            for row, text in entries:
                try:
                    left = int(row.get("left", "0"))
                    top = int(row.get("top", "0"))
                    width = int(row.get("width", "0"))
                    height = int(row.get("height", "0"))
                    confidence = float(row.get("conf", "-1"))
                except ValueError:
                    continue
                boxes.append((left, top, left + width, top + height))
                raw_words.append(text)
                if confidence >= 0:
                    confidences.append(max(0.0, min(confidence / 100.0, 1.0)))
                words.append(
                    BackendWord(
                        text=text,
                        bbox=(float(left), float(top), float(left + width), float(top + height)),
                        confidence=(
                            max(0.0, min(confidence / 100.0, 1.0)) if confidence >= 0 else None
                        ),
                        reading_order=len(words),
                    )
                )
            if not boxes or not raw_words:
                continue
            x0 = min(box[0] for box in boxes)
            y0 = min(box[1] for box in boxes)
            x1 = max(box[2] for box in boxes)
            y1 = max(box[3] for box in boxes)
            result.append(
                BackendTextLine(
                    raw_text=" ".join(raw_words),
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                    confidence=(sum(confidences) / len(confidences) if confidences else None),
                    language=_infer_language(" ".join(raw_words)),
                    script=_infer_script(" ".join(raw_words)),
                    text_type=TextType.PRINTED,
                    words=tuple(words),
                )
            )
        return result


_PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _infer_language(text: str) -> str:
    has_rtl = bool(_PERSIAN_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_rtl and has_latin:
        return "fa+en"
    if has_rtl:
        return "fa"
    if has_latin:
        return "en"
    return "und"


def _infer_script(text: str) -> str:
    has_rtl = bool(_PERSIAN_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_rtl and has_latin:
        return "Arabic+Latin"
    if has_rtl:
        return "Arabic"
    if has_latin:
        return "Latin"
    return "Unknown"
