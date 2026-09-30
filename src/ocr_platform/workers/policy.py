"""Configuration-backed processing mode policies."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ocr_platform.config import Settings

from .models import ProcessingMode


@dataclass(frozen=True)
class ProcessingModePolicy:
    """Effective immutable settings used for one submitted job."""

    mode: ProcessingMode
    settings: Settings

    @classmethod
    def for_mode(cls, settings: Settings, mode: ProcessingMode | str) -> ProcessingModePolicy:
        selected = ProcessingMode(mode)
        retries = dict(settings.mode_max_retries)[selected.value]
        high_quality_retry = dict(settings.mode_enable_high_quality_retry)[selected.value]
        return cls(
            mode=selected,
            settings=replace(
                settings,
                max_retries=retries,
                verification_enable_high_quality_retry=high_quality_retry,
            ),
        )
