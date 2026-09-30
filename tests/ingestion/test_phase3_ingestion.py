from pathlib import Path

import fitz
import pytest
from PIL import Image

from ocr_platform.config import Settings
from ocr_platform.domain import CoordinateSpace, PageType
from ocr_platform.errors import (
    CorruptPdfError,
    ImageDecodeError,
    InvalidDocumentError,
    PasswordProtectedPdfError,
)
from ocr_platform.ingestion import (
    DocumentIngestionService,
    ImageReader,
    PdfReader,
    detect_content_type,
)
from ocr_platform.ingestion.models import PageInput, PageQualityMetadata


def _save_pdf(path: Path, pages: list[dict[str, object]]) -> None:
    document = fitz.open()
    for page_data in pages:
        page = document.new_page(
            width=float(page_data.get("width", 300)),
            height=float(page_data.get("height", 400)),
        )
        text = page_data.get("text")
        font_size = float(page_data.get("font_size", 11))
        if isinstance(text, str):
            font_path = Path("C:/Windows/Fonts/arial.ttf")
            if font_path.is_file():
                page.insert_font(fontname="Arial", fontfile=str(font_path))
                page.insert_text((40, 70), text, fontname="Arial", fontsize=font_size)
            else:
                page.insert_text((40, 70), text, fontsize=font_size)
        if page_data.get("image"):
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 50), False)
            pixmap.clear_with(0xFFFFFF)
            page.insert_image(fitz.Rect(40, 120, 140, 180), pixmap=pixmap)
        if page_data.get("rotation"):
            page.set_rotation(int(page_data["rotation"]))
    document.save(path)
    document.close()


def test_native_pdf_inspection_preserves_persian_and_mixed_text(tmp_path: Path) -> None:
    path = tmp_path / "native.pdf"
    _save_pdf(path, [{"text": "شماره قرارداد ١٢٣٤٥ / Ref ABC-123"}])

    settings = Settings(environment="test")
    pages = PdfReader(settings).read(
        path,
        document_id="doc-native",
        source_uri="artifact://doc-native/source/original.bin",
    )

    page = pages[0]
    assert page.page_type is PageType.NATIVE_TEXT
    assert page.native_text_reliable is True
    assert page.native_text_evidence is not None
    assert page.native_text_evidence.character_count > 5
    assert page.native_text_evidence.text_coverage > 0
    assert "ABC" in page.native_lines[0].text
    assert any("\u0600" <= char <= "\ufdff" for char in page.native_lines[0].text)
    assert page.rotation == 0


def test_scanned_and_mixed_pages_are_classified_per_page(tmp_path: Path) -> None:
    path = tmp_path / "mixed.pdf"
    _save_pdf(
        path,
        [
            {"image": True},
            {"text": "Native page", "image": True},
        ],
    )

    pages = PdfReader(Settings(environment="test")).read(
        path,
        document_id="doc-mixed",
        source_uri="artifact://doc-mixed/source/original.bin",
    )

    assert pages[0].page_type is PageType.SCANNED
    assert pages[0].native_text_reliable is False
    assert pages[0].image_regions
    assert pages[1].page_type is PageType.MIXED
    assert pages[1].native_text_reliable is True
    assert pages[1].image_regions


def test_rotated_page_preserves_rotation_and_unrotated_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "rotated.pdf"
    _save_pdf(path, [{"text": "Rotated", "width": 200, "height": 400, "rotation": 90}])

    page = PdfReader(Settings(environment="test")).read(
        path,
        document_id="doc-rotated",
        source_uri="artifact://doc-rotated/source/original.bin",
    )[0]

    assert page.rotation == 90
    assert page.unrotated_width == 200
    assert page.unrotated_height == 400
    assert (page.width, page.height) == (400, 200)


def test_corrupt_and_password_protected_pdfs_fail_explicitly(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nnot a complete PDF")
    reader = PdfReader(Settings(environment="test"))

    with pytest.raises(CorruptPdfError):
        reader.read(corrupt, document_id="doc-corrupt", source_uri="artifact://corrupt")

    protected = tmp_path / "protected.pdf"
    document = fitz.open()
    document.new_page().insert_text((30, 30), "secret")
    document.save(
        protected,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()

    with pytest.raises(PasswordProtectedPdfError):
        reader.read(protected, document_id="doc-protected", source_uri="artifact://protected")


def test_image_reader_corrects_exif_orientation_and_reports_quality(tmp_path: Path) -> None:
    path = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (40, 20), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(path, format="JPEG", exif=exif.tobytes())

    reader = ImageReader(Settings(environment="test"))
    page = reader.read(path, source_uri="artifact://doc-image/source/original.bin")[0]
    rendered = reader.render(path, source_uri=page.source_uri)

    assert (page.width, page.height) == (20, 40)
    assert page.quality is not None
    assert page.quality.pixel_count == 800
    assert page.quality.exif_orientation == 6
    assert (rendered.width, rendered.height) == (20, 40)
    assert rendered.image_format == "png"


def test_malformed_image_and_dimension_bounds_are_rejected(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.png"
    malformed.write_bytes(b"\x89PNG\r\n\x1a\nnot-an-image")
    with pytest.raises(ImageDecodeError):
        ImageReader(Settings(environment="test")).read(
            malformed,
            source_uri="artifact://bad/source/original.bin",
        )

    large = tmp_path / "large.png"
    Image.new("RGB", (20, 20), "white").save(large)
    with pytest.raises(InvalidDocumentError, match="page dimensions"):
        ImageReader(Settings(environment="test", max_page_width=10)).read(
            large,
            source_uri="artifact://large/source/original.bin",
        )


def test_document_ingestion_stores_source_and_page_render_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "photo.png"
    Image.new("RGB", (100, 60), "white").save(path)
    settings = Settings(environment="test", storage_root=tmp_path / "artifacts")

    result = DocumentIngestionService(settings).ingest(
        path,
        filename="photo.png",
        declared_content_type="image/png",
    )

    assert result.document_id.startswith("doc-")
    assert result.page_count == 1
    assert result.source.checksum_sha256
    assert result.pages[0].page_type is PageType.IMAGE
    assert result.pages[0].render_artifact is not None
    assert result.pages[0].render_artifact.uri.startswith(
        f"artifact://{result.document_id}/pages/page_0001/"
    )
    assert (settings.storage_root / result.document_id / "source" / "original.bin").is_file()
    assert (
        settings.storage_root
        / result.document_id
        / "pages"
        / "page_0001"
        / "original_render_300dpi.png"
    ).is_file()











def test_tiny_embedded_text_is_flagged_without_discarding_native_text(tmp_path: Path) -> None:
    path = tmp_path / "tiny.pdf"
    _save_pdf(path, [{"text": "tiny 123", "font_size": 4}])

    page = PdfReader(Settings(environment="test")).read(
        path,
        document_id="doc-tiny",
        source_uri="artifact://doc-tiny/source/original.bin",
    )[0]

    assert page.native_text_reliable is True
    assert page.tiny_text is True
    assert page.quality is not None
    assert "tiny_text" in page.quality.quality_flags
    assert page.render_artifact is None


def test_tiny_text_suspected_quality_flag_routes_to_tiny_text_path() -> None:
    page = PageInput(
        page_number=1,
        width=1200,
        height=1600,
        coordinate_space=CoordinateSpace.SOURCE_PIXEL,
        page_type=PageType.IMAGE,
        source_uri="artifact://doc/page-1.png",
        native_text_reliable=False,
        native_text_reason="image-only source",
        quality=PageQualityMetadata(quality_flags=("tiny_text_suspected",)),
    )

    assert page.tiny_text is True


@pytest.mark.parametrize("extension", ["tiff", "webp"])
def test_pillow_supported_raster_formats_are_inspected(tmp_path: Path, extension: str) -> None:
    path = tmp_path / f"image.{extension}"
    Image.new("RGB", (24, 16), "white").save(path, format=extension.upper())

    content_type = detect_content_type(path)
    assert content_type in {"image/tiff", "image/webp"}
    page = ImageReader(Settings(environment="test")).read(
        path,
        source_uri="artifact://doc-image/source/original.bin",
    )[0]
    assert page.page_type is PageType.IMAGE


def test_ingestion_rejects_unsafe_custom_document_id(tmp_path: Path) -> None:
    path = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), "white").save(path)
    service = DocumentIngestionService(
        Settings(environment="test", storage_root=tmp_path / "artifacts")
    )

    with pytest.raises(InvalidDocumentError, match="document id"):
        service.ingest(path, filename="photo.png", document_id="../escape")

