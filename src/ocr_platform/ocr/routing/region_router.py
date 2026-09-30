"""Provider-neutral routing of layout regions to recognition capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ocr_platform.domain import BlockType, TextType
from ocr_platform.ocr.models import OcrRegion


class RegionRoute(StrEnum):
    PRINTED = "printed"
    HANDWRITING = "handwriting"
    TABLE = "table"


@dataclass(frozen=True)
class RegionRouteDecision:
    routes: tuple[RegionRoute, ...]
    reason: str

    @property
    def requires_handwriting(self) -> bool:
        return RegionRoute.HANDWRITING in self.routes

    @property
    def requires_table(self) -> bool:
        return RegionRoute.TABLE in self.routes


class RegionRouter:
    """Select recognition capabilities from stable layout/text hints.

    A form or explicitly mixed region intentionally selects both printed OCR and
    HTR. If one capability is unavailable, the pipeline retains the other
    result and emits a review warning instead of silently changing the route.
    """

    def route(self, region: OcrRegion) -> RegionRouteDecision:
        hint = (region.layout_route_hint or "").strip().lower()
        if region.block_type is BlockType.TABLE or hint == "table":
            return RegionRouteDecision((RegionRoute.TABLE,), "table")
        if region.block_type is BlockType.HANDWRITING or hint == "handwriting":
            return RegionRouteDecision((RegionRoute.HANDWRITING,), "handwriting")
        if (
            region.block_type is BlockType.FORM
            or region.text_type is TextType.MIXED
            or hint in {"form", "key_value", "key-value", "mixed"}
        ):
            return RegionRouteDecision(
                (RegionRoute.PRINTED, RegionRoute.HANDWRITING),
                "mixed_form",
            )
        if region.text_type is TextType.HANDWRITTEN:
            return RegionRouteDecision((RegionRoute.HANDWRITING,), "handwritten_text")
        return RegionRouteDecision((RegionRoute.PRINTED,), "printed_text")
