"""Provider-label normalization into the stable internal layout taxonomy."""

from __future__ import annotations

from dataclasses import dataclass

from ocr_platform.domain import BlockType, TextType

from .ports import RegionRouteHint


@dataclass(frozen=True, slots=True)
class LayoutClassification:
    block_type: BlockType
    route_hint: RegionRouteHint
    text_type: TextType
    needs_review: bool
    uncertainty_flags: tuple[str, ...] = ()


_LABELS: dict[str, tuple[BlockType, RegionRouteHint, TextType]] = {
    "title": (BlockType.TITLE, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "heading": (BlockType.TITLE, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "header": (BlockType.HEADER, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "paragraph": (BlockType.PARAGRAPH, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "text": (BlockType.PARAGRAPH, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "body_text": (BlockType.PARAGRAPH, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "text_line": (BlockType.TEXT_LINE_GROUP, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "line": (BlockType.TEXT_LINE_GROUP, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "line_group": (BlockType.TEXT_LINE_GROUP, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "printed_text": (BlockType.PRINTED_TEXT, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "handwriting": (BlockType.HANDWRITING, RegionRouteHint.HANDWRITING, TextType.HANDWRITTEN),
    "handwritten": (BlockType.HANDWRITING, RegionRouteHint.HANDWRITING, TextType.HANDWRITTEN),
    "handwritten_text": (BlockType.HANDWRITING, RegionRouteHint.HANDWRITING, TextType.HANDWRITTEN),
    "table": (BlockType.TABLE, RegionRouteHint.TABLE, TextType.UNKNOWN),
    "form": (BlockType.FORM, RegionRouteHint.FORM, TextType.UNKNOWN),
    "key_value": (BlockType.FORM, RegionRouteHint.FORM, TextType.UNKNOWN),
    "key-value": (BlockType.FORM, RegionRouteHint.FORM, TextType.UNKNOWN),
    "formula": (BlockType.FORMULA, RegionRouteHint.FORMULA, TextType.PRINTED),
    "equation": (BlockType.FORMULA, RegionRouteHint.FORMULA, TextType.PRINTED),
    "image": (BlockType.IMAGE, RegionRouteHint.IMAGE, TextType.UNKNOWN),
    "figure": (BlockType.FIGURE, RegionRouteHint.IMAGE, TextType.UNKNOWN),
    "caption": (BlockType.CAPTION, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "footer": (BlockType.FOOTER, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "page_number": (BlockType.PAGE_NUMBER, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "page-number": (BlockType.PAGE_NUMBER, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "sidebar": (BlockType.SIDEBAR, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "list": (BlockType.LIST, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "list_item": (BlockType.LIST, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "multi_column": (BlockType.MULTI_COLUMN, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "multi-column": (BlockType.MULTI_COLUMN, RegionRouteHint.PRINTED_TEXT, TextType.PRINTED),
    "tiny_text": (BlockType.TINY_TEXT, RegionRouteHint.TINY_TEXT, TextType.PRINTED),
    "unknown": (BlockType.UNKNOWN, RegionRouteHint.UNKNOWN, TextType.UNKNOWN),
}


def normalize_provider_label(label: str | None) -> str:
    if not label:
        return "unknown"
    return "_".join(label.strip().lower().replace("/", "_").split())


def map_provider_label(
    label: str | None, *, confidence: float | None = None
) -> LayoutClassification:
    """Map provider classes without allowing unknown labels to become confident text."""

    normalized = normalize_provider_label(label)
    mapped = _LABELS.get(normalized)
    if mapped is None:
        return LayoutClassification(
            block_type=BlockType.UNKNOWN,
            route_hint=RegionRouteHint.UNKNOWN,
            text_type=TextType.UNKNOWN,
            needs_review=True,
            uncertainty_flags=("unknown_provider_class",),
        )
    needs_review = confidence is not None and confidence < 0.5
    return LayoutClassification(
        block_type=mapped[0],
        route_hint=mapped[1],
        text_type=mapped[2],
        needs_review=needs_review,
        uncertainty_flags=("low_layout_confidence",) if needs_review else (),
    )
