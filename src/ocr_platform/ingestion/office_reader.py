"""Native Office document inspection with optional render-to-PDF fallback.

The reader extracts text and basic layout from OOXML containers without
rasterizing them. Rendering is used only when a later OCR route explicitly
needs visual content, and requires a locally installed LibreOffice command.
"""

from __future__ import annotations

import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path
from xml.etree import ElementTree

from ocr_platform.config import Settings
from ocr_platform.domain import CoordinateSpace, PageType
from ocr_platform.errors import BackendUnavailableError, InvalidDocumentError, ProcessingError

from .models import NativeTextLine, PageInput, RenderedPage
from .pdf_reader import PdfReader

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLS_CONTENT_TYPE = "application/vnd.ms-excel"

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


class OfficeReader:
    def __init__(self, settings: Settings, *, executable: str = "soffice") -> None:
        self.settings = settings
        self.executable = executable
        self._pdf_reader = PdfReader(settings)

    def extract(
        self,
        path: Path,
        *,
        content_type: str,
        source_uri: str,
    ) -> tuple[PageInput, ...]:
        try:
            if content_type == DOCX_CONTENT_TYPE:
                return self._read_docx(path, source_uri=source_uri)
            if content_type == XLSX_CONTENT_TYPE:
                return self._read_xlsx(path, source_uri=source_uri)
            if content_type == PPTX_CONTENT_TYPE:
                return self._read_pptx(path, source_uri=source_uri)
            if content_type == XLS_CONTENT_TYPE:
                return self._read_xls(path, source_uri=source_uri)
        except BackendUnavailableError:
            raise
        except (KeyError, OSError, ElementTree.ParseError, zipfile.BadZipFile) as exc:
            raise InvalidDocumentError("Office container is malformed") from exc
        raise InvalidDocumentError(f"no Office reader is registered for {content_type}")

    def render_page(
        self,
        path: Path,
        *,
        content_type: str,
        page_number: int,
        dpi: int,
        source_uri: str,
    ) -> RenderedPage:
        if page_number <= 0:
            raise InvalidDocumentError("page number must be positive")
        executable = shutil.which(self.executable)
        if executable is None:
            raise BackendUnavailableError(
                "Office visual rendering requires a local LibreOffice/soffice executable"
            )
        suffix = {
            DOCX_CONTENT_TYPE: ".docx",
            XLSX_CONTENT_TYPE: ".xlsx",
            PPTX_CONTENT_TYPE: ".pptx",
            XLS_CONTENT_TYPE: ".xls",
        }.get(content_type)
        if suffix is None:
            raise InvalidDocumentError(f"unsupported Office render type: {content_type}")
        try:
            with tempfile.TemporaryDirectory(
                prefix="ocr-office-", dir=str(self.settings.temporary_workspace)
            ) as temporary:
                temporary_path = Path(temporary)
                input_path = temporary_path / f"source{suffix}"
                output_path = temporary_path / "pdf"
                output_path.mkdir()
                input_path.write_bytes(path.read_bytes())
                completed = subprocess.run(
                    [
                        executable,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(output_path),
                        str(input_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.processing_timeout_seconds,
                )
                if completed.returncode != 0:
                    raise ProcessingError(
                        "LibreOffice failed to render the Office document",
                        retryable=True,
                    )
                pdf_path = output_path / "source.pdf"
                if not pdf_path.is_file():
                    raise ProcessingError(
                        "LibreOffice did not produce a PDF render",
                        retryable=True,
                    )
                rendered = self._pdf_reader.render_page(
                    pdf_path,
                    page_number=page_number,
                    dpi=dpi,
                )
                return RenderedPage(
                    page_number=rendered.page_number,
                    width=rendered.width,
                    height=rendered.height,
                    dpi=rendered.dpi,
                    image_format=rendered.image_format,
                    image_bytes=rendered.image_bytes,
                    source_uri=source_uri,
                    rotation=rendered.rotation,
                    quality=rendered.quality,
                )
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError("Office rendering timed out", retryable=True) from exc
        except OSError as exc:
            raise ProcessingError("Office source could not be rendered", retryable=True) from exc

    def _read_docx(self, path: Path, *, source_uri: str) -> tuple[PageInput, ...]:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            has_embedded_images = any(
                name.lower().startswith("word/media/") for name in archive.namelist()
            )
        page_width, page_height = _docx_page_size(root)
        pages: list[list[tuple[str, int]]] = [[]]
        block_index = 0
        for paragraph in root.iter(f"{_W_NS}p"):
            text = "".join(node.text or "" for node in paragraph.iter(f"{_W_NS}t"))
            if text.strip():
                pages[-1].append((text, block_index))
                block_index += 1
            if any(
                br.get(f"{_W_NS}type") == "page"
                for br in paragraph.iter(f"{_W_NS}br")
            ):
                pages.append([])
        return tuple(
            _native_page(
                page_number=index,
                width=page_width,
                height=page_height,
                source_uri=source_uri,
                lines=_positioned_lines(lines, page_width),
                page_id=f"docx-page-{index:04d}",
                reason="embedded_docx_text",
                image_regions=((0.0, 0.0, page_width, page_height),)
                if has_embedded_images
                else (),
            )
            for index, lines in enumerate(pages, start=1)
        )

    def _read_xlsx(self, path: Path, *, source_uri: str) -> tuple[PageInput, ...]:
        with zipfile.ZipFile(path) as archive:
            shared = _xlsx_shared_strings(archive)
            has_embedded_images = any(
                name.lower().startswith("xl/media/") for name in archive.namelist()
            )
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relation_targets = {
                relation.attrib.get("Id"): relation.attrib.get("Target", "")
                for relation in relationships
            }
            pages: list[PageInput] = []
            for sheet_index, sheet in enumerate(_iter_local(workbook, "sheet"), start=1):
                relationship_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                target = _resolve_relationship_target(
                    "xl", relation_targets.get(relationship_id, "")
                )
                if target not in archive.namelist():
                    continue
                worksheet = ElementTree.fromstring(archive.read(target))
                lines = _xlsx_lines(worksheet, shared)
                width = max(612.0, 36.0 + 80.0 * max((item[3] for item in lines), default=1))
                height = max(792.0, 54.0 + 22.0 * max((item[2] for item in lines), default=1))
                pages.append(
                    _native_page(
                        page_number=len(pages) + 1,
                        width=min(width, float(self.settings.max_page_width)),
                        height=min(height, float(self.settings.max_page_height)),
                        source_uri=source_uri,
                        lines=_xlsx_positioned_lines(lines),
                        page_id=f"xlsx-sheet-{sheet_index:04d}",
                        reason=f"native_xlsx_sheet:{sheet.attrib.get('name', sheet_index)}",
                        image_regions=((0.0, 0.0, width, height),)
                        if has_embedded_images
                        else (),
                    )
                )
            return tuple(pages)

    def _read_pptx(self, path: Path, *, source_uri: str) -> tuple[PageInput, ...]:
        with zipfile.ZipFile(path) as archive:
            presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
            size = next(_iter_local(presentation, "sldSz"), None)
            width = (
                _emu_to_points(int(size.attrib.get("cx", 9144000)))
                if size is not None
                else 720.0
            )
            height = (
                _emu_to_points(int(size.attrib.get("cy", 6858000)))
                if size is not None
                else 540.0
            )
            relationships = ElementTree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
            relation_targets = {
                relation.attrib.get("Id"): relation.attrib.get("Target", "")
                for relation in relationships
            }
            pages: list[PageInput] = []
            for index, slide_id in enumerate(_iter_local(presentation, "sldId"), start=1):
                relationship_id = slide_id.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                target = _resolve_relationship_target(
                    "ppt", relation_targets.get(relationship_id, "")
                )
                if target not in archive.namelist():
                    continue
                slide = ElementTree.fromstring(archive.read(target))
                lines, image_regions = _pptx_content(slide, width, height)
                pages.append(
                    _native_page(
                        page_number=len(pages) + 1,
                        width=min(width, float(self.settings.max_page_width)),
                        height=min(height, float(self.settings.max_page_height)),
                        source_uri=source_uri,
                        lines=lines,
                        page_id=f"pptx-slide-{index:04d}",
                        reason="native_pptx_slide",
                        image_regions=image_regions,
                    )
                )
            return tuple(pages)

    def _read_xls(self, path: Path, *, source_uri: str) -> tuple[PageInput, ...]:
        try:
            import xlrd
        except ImportError as exc:
            raise BackendUnavailableError(
                "legacy XLS extraction requires the optional 'office' extra (xlrd)"
            ) from exc
        try:
            workbook = xlrd.open_workbook(path, on_demand=True)
            pages: list[PageInput] = []
            for sheet_index, sheet in enumerate(workbook.sheets(), start=1):
                lines: list[tuple[str, int, int, int]] = []
                for row_index in range(sheet.nrows):
                    for column_index in range(sheet.ncols):
                        value = sheet.cell_value(row_index, column_index)
                        if str(value).strip():
                            lines.append((str(value), row_index, row_index, column_index))
                pages.append(
                    _native_page(
                        page_number=sheet_index,
                        width=min(612.0 + sheet.ncols * 80.0, float(self.settings.max_page_width)),
                        height=min(
                            792.0 + sheet.nrows * 22.0,
                            float(self.settings.max_page_height),
                        ),
                        source_uri=source_uri,
                        lines=_xlsx_positioned_lines(lines),
                        page_id=f"xls-sheet-{sheet_index:04d}",
                        reason=f"native_xls_sheet:{sheet.name}",
                    )
                )
            return tuple(pages)
        except Exception as exc:
            raise InvalidDocumentError("legacy XLS workbook could not be read") from exc


def _native_page(
    *,
    page_number: int,
    width: float,
    height: float,
    source_uri: str,
    lines: Iterable[NativeTextLine],
    page_id: str,
    reason: str,
    image_regions: tuple[tuple[float, float, float, float], ...] = (),
) -> PageInput:
    return PageInput(
        page_number=page_number,
        width=width,
        height=height,
        coordinate_space=CoordinateSpace.PDF_POINT,
        page_type=PageType.MIXED if image_regions else PageType.NATIVE_TEXT,
        source_uri=source_uri,
        native_text_reliable=True,
        native_text_reason=reason,
        native_lines=tuple(lines),
        image_regions=image_regions,
        page_id=page_id,
    )


def _empty_native_page(source_uri: str, width: float, height: float, reason: str) -> PageInput:
    return _native_page(
        page_number=1,
        width=width,
        height=height,
        source_uri=source_uri,
        lines=(),
        page_id="office-page-0001",
        reason=reason,
    )


def _positioned_lines(lines: list[tuple[str, int]], width: float) -> tuple[NativeTextLine, ...]:
    return tuple(
        NativeTextLine(
            text=text,
            bbox=(36.0, 36.0 + index * 18.0, max(40.0, width - 36.0), 50.0 + index * 18.0),
            block_index=block_index,
            line_index=index,
        )
        for index, (text, block_index) in enumerate(lines)
    )


def _xlsx_positioned_lines(lines: list[tuple[str, int, int, int]]) -> tuple[NativeTextLine, ...]:
    return tuple(
        NativeTextLine(
            text=text,
            bbox=(
                36.0 + column * 80.0,
                36.0 + row * 22.0,
                108.0 + column * 80.0,
                54.0 + row * 22.0,
            ),
            block_index=row,
            line_index=index,
        )
        for index, (text, row, _row_end, column) in enumerate(lines)
    )


def _docx_page_size(root: ElementTree.Element) -> tuple[float, float]:
    section = next(root.iter(f"{_W_NS}sectPr"), None)
    page_size = section.find(f"{_W_NS}pgSz") if section is not None else None
    if page_size is None:
        return 612.0, 792.0
    try:
        return float(page_size.attrib.get(f"{_W_NS}w", 12240)) / 20, float(
            page_size.attrib.get(f"{_W_NS}h", 15840)
        ) / 20
    except (TypeError, ValueError):
        return 612.0, 792.0


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in _iter_local(item, "t"))
        for item in _iter_local(root, "si")
    ]


def _xlsx_lines(root: ElementTree.Element, shared: list[str]) -> list[tuple[str, int, int, int]]:
    values: list[tuple[str, int, int, int]] = []
    for cell in _iter_local(root, "c"):
        value = next(_iter_local(cell, "v"), None)
        inline = next(_iter_local(cell, "t"), None)
        text = inline.text if inline is not None else (value.text if value is not None else "")
        if cell.attrib.get("t") == "s" and text is not None:
            try:
                text = shared[int(text)]
            except (ValueError, IndexError):
                text = ""
        if not str(text).strip():
            continue
        match = re.fullmatch(r"([A-Z]+)([0-9]+)", cell.attrib.get("r", "A1"))
        if not match:
            continue
        column = 0
        for char in match.group(1):
            column = column * 26 + ord(char) - ord("A") + 1
        values.append((str(text), int(match.group(2)) - 1, int(match.group(2)) - 1, column - 1))
    return values


def _pptx_content(
    root: ElementTree.Element, width: float, height: float
) -> tuple[tuple[NativeTextLine, ...], tuple[tuple[float, float, float, float], ...]]:
    lines: list[NativeTextLine] = []
    images: list[tuple[float, float, float, float]] = []
    order = 0
    for shape in _iter_local(root, "sp"):
        text = " ".join(
            (node.text or "").strip()
            for node in _iter_local(shape, "t")
            if (node.text or "").strip()
        )
        if not text:
            continue
        bbox = _pptx_shape_bbox(shape, width, height)
        lines.append(NativeTextLine(text, bbox, order, order))
        order += 1
    for picture in _iter_local(root, "pic"):
        bbox = _pptx_shape_bbox(picture, width, height)
        images.append(bbox)
    return tuple(lines), tuple(images)


def _pptx_shape_bbox(
    shape: ElementTree.Element,
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    offset = next(_iter_local(shape, "off"), None)
    extent = next(_iter_local(shape, "ext"), None)
    if offset is None or extent is None:
        return (0.0, 0.0, width, height)
    try:
        x = _emu_to_points(int(offset.attrib.get("x", 0)))
        y = _emu_to_points(int(offset.attrib.get("y", 0)))
        right = x + _emu_to_points(int(extent.attrib.get("cx", 0)))
        bottom = y + _emu_to_points(int(extent.attrib.get("cy", 0)))
        return (max(0.0, x), max(0.0, y), min(width, right), min(height, bottom))
    except (TypeError, ValueError):
        return (0.0, 0.0, width, height)


def _emu_to_points(value: int) -> float:
    return value / 12700.0


def _resolve_relationship_target(base_directory: str, target: str) -> str:
    normalized = target.replace("\\", "/")
    if normalized.startswith("/"):
        return posixpath.normpath(normalized.lstrip("/"))
    resolved = posixpath.normpath(posixpath.join(base_directory, normalized))
    if resolved == ".." or resolved.startswith("../"):
        return ""
    return resolved


def _iter_local(root: ElementTree.Element, name: str) -> Iterable[ElementTree.Element]:
    """Iterate XML elements by local name for namespaced and minimal fixtures."""

    return (
        element
        for element in root.iter()
        if _local_name(element.tag) == name
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


__all__ = [
    "DOCX_CONTENT_TYPE",
    "PPTX_CONTENT_TYPE",
    "XLSX_CONTENT_TYPE",
    "XLS_CONTENT_TYPE",
    "OfficeReader",
]
