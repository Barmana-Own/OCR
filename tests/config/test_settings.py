from pathlib import Path

import pytest

from ocr_platform.config.settings import Settings
from ocr_platform.errors import ConfigurationError


def test_phase2_defaults_are_centralized() -> None:
    settings = Settings()

    assert settings.default_dpi == 300
    assert settings.high_quality_dpi == 450
    assert settings.tiny_text_dpi == 600
    assert settings.region_scale_candidates == (2, 3, 4)
    assert settings.verification_threshold == 0.92
    assert settings.max_page_width > 0
    assert settings.max_page_height > 0
    assert settings.processing_timeout_seconds > 0
    assert settings.enabled_ocr_backends == ("tesseract",)
    assert settings.layout_backend == "heuristic"
    assert settings.layout_max_pixels == 4_000_000
    assert settings.layout_max_regions == 512
    assert settings.layout_min_confidence == 0.35
    assert settings.handwriting_backend == "unavailable"
    assert settings.preprocessing_profiles == (
        "clean_print",
        "mobile_photo",
        "low_contrast",
        "tiny_text",
        "handwriting",
        "binary_scan",
    )
    assert settings.default_preprocessing_profile == "clean_print"
    assert settings.max_preprocessing_variants > 0


def test_environment_overrides_parse_paths_lists_and_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "OCR_DEFAULT_DPI": "360",
        "OCR_HIGH_QUALITY_DPI": "480",
        "OCR_TINY_TEXT_DPI": "640",
        "OCR_REGION_SCALE_CANDIDATES": "2, 3, 4",
        "OCR_VERIFICATION_THRESHOLD": "0.94",
        "OCR_ENABLED_OCR_BACKENDS": "tesseract,paddleocr",
        "OCR_LAYOUT_BACKEND": "pp_structure",
        "OCR_HANDWRITING_BACKEND": "surya",
        "OCR_TABLE_BACKEND": "pp_structure",
        "OCR_MAX_PAGE_WIDTH": "24000",
        "OCR_MAX_PAGE_HEIGHT": "32000",
        "OCR_PROCESSING_TIMEOUT_SECONDS": "900",
        "OCR_ARTIFACT_BUCKET": "documents",
        "OCR_TEMPORARY_WORKSPACE": "var/phase2-tmp",
        "OCR_MODEL_PATH": "var/phase2-models",
        "OCR_CACHE_PATH": "var/phase2-cache",
        "OCR_PREPROCESSING_PROFILES": "clean_print,tiny_text",
        "OCR_DEFAULT_PREPROCESSING_PROFILE": "tiny_text",
        "OCR_MAX_PREPROCESSING_VARIANTS": "5",
        "OCR_TINY_TEXT_PIXEL_HEIGHT_THRESHOLD": "10",
        "OCR_LAYOUT_MAX_PIXELS": "2000000",
        "OCR_LAYOUT_MAX_REGIONS": "128",
        "OCR_LAYOUT_MIN_CONFIDENCE": "0.45",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    settings = Settings.from_env()

    assert settings.default_dpi == 360
    assert settings.high_quality_dpi == 480
    assert settings.tiny_text_dpi == 640
    assert settings.region_scale_candidates == (2, 3, 4)
    assert settings.verification_threshold == 0.94
    assert settings.enabled_ocr_backends == ("tesseract", "paddleocr")
    assert settings.layout_backend == "pp_structure"
    assert settings.handwriting_backend == "surya"
    assert settings.table_backend == "pp_structure"
    assert settings.max_page_width == 24000
    assert settings.max_page_height == 32000
    assert settings.processing_timeout_seconds == 900
    assert settings.artifact_bucket == "documents"
    assert settings.temporary_workspace == Path("var/phase2-tmp")
    assert settings.model_path == Path("var/phase2-models")
    assert settings.cache_path == Path("var/phase2-cache")
    assert settings.preprocessing_profiles == ("clean_print", "tiny_text")
    assert settings.default_preprocessing_profile == "tiny_text"
    assert settings.max_preprocessing_variants == 5
    assert settings.tiny_text_pixel_height_threshold == 10
    assert settings.layout_max_pixels == 2_000_000
    assert settings.layout_max_regions == 128
    assert settings.layout_min_confidence == 0.45


def test_configuration_hash_is_deterministic_and_excludes_api_keys() -> None:
    first = Settings(api_keys=("secret-a",))
    second = Settings(api_keys=("secret-b",))

    assert first.configuration_hash == second.configuration_hash
    assert "secret-a" not in first.configuration_hash
    assert "secret-b" not in second.configuration_hash
    assert Settings(default_dpi=301).configuration_hash != first.configuration_hash


def test_invalid_phase2_configuration_fails_explicitly() -> None:
    with pytest.raises(ConfigurationError):
        Settings(verification_threshold=0)

    with pytest.raises(ConfigurationError):
        Settings(region_scale_candidates=(2, 5))

    with pytest.raises(ConfigurationError):
        Settings(processing_timeout_seconds=0)

    with pytest.raises(ConfigurationError):
        Settings(preprocessing_profiles=())

    with pytest.raises(ConfigurationError):
        Settings(default_preprocessing_profile="unknown")

    with pytest.raises(ConfigurationError):
        Settings(layout_max_pixels=0)

    with pytest.raises(ConfigurationError):
        Settings(layout_max_regions=0)

    with pytest.raises(ConfigurationError):
        Settings(layout_min_confidence=1.1)


