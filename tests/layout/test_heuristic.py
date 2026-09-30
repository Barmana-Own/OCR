from io import BytesIO

from PIL import Image, ImageDraw

from ocr_platform.domain import BlockType
from ocr_platform.layout import HeuristicLayoutBackend


def _png(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def _two_column_page() -> Image.Image:
    image = Image.new("L", (800, 600), 255)
    draw = ImageDraw.Draw(image)
    for y in range(120, 360, 28):
        draw.rectangle((60, y, 330, y + 9), fill=0)
        draw.rectangle((470, y, 740, y + 9), fill=0)
    return image


def test_heuristic_backend_detects_two_columns_deterministically() -> None:
    backend = HeuristicLayoutBackend()
    first = backend.detect(_png(_two_column_page()), page_width=800, page_height=600)
    second = backend.detect(_png(_two_column_page()), page_width=800, page_height=600)

    assert first == second
    assert len(first) == 2
    assert {dict(region.metadata)["column_index"] for region in first} == {"0", "1"}
    assert all(region.block_type is BlockType.MULTI_COLUMN for region in first)
    assert all(region.lines for region in first)


def test_heuristic_backend_classifies_header_and_footer_bands() -> None:
    image = Image.new("L", (600, 500), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((160, 35, 440, 48), fill=0)
    for y in range(120, 310, 30):
        draw.rectangle((80, y, 520, y + 9), fill=0)
    draw.rectangle((260, 455, 340, 466), fill=0)

    regions = HeuristicLayoutBackend().detect(_png(image), page_width=600, page_height=500)

    assert regions[0].block_type is BlockType.HEADER
    assert regions[-1].block_type in {BlockType.FOOTER, BlockType.PAGE_NUMBER}


def test_heuristic_backend_keeps_unsupported_handwriting_uncertain() -> None:
    image = Image.new("L", (400, 200), 255)
    draw = ImageDraw.Draw(image)
    draw.line((20, 80, 180, 70), fill=0, width=3)
    draw.line((220, 120, 370, 130), fill=0, width=3)

    regions = HeuristicLayoutBackend().detect(_png(image), page_width=400, page_height=200)

    assert regions
    assert all(region.text_type.value == "unknown" for region in regions)
    assert all(region.needs_review for region in regions)
