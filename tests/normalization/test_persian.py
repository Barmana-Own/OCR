from ocr_platform.normalization import (
    DigitPolicy,
    LineBreakPolicy,
    NormalizationConfig,
    UnicodeNormalizationForm,
    WhitespacePolicy,
    ZeroWidthPolicy,
    normalize_text,
)


def test_normalizes_persian_character_variants_without_reversing_mixed_text() -> None:
    raw = "شماره قرارداد ١٢٣٤٥ ABC-42 https://example.com"
    normalized = normalize_text(raw)
    assert normalized == "شماره قرارداد ۱۲۳۴۵ ABC-42 https://example.com"
    assert "ABC-42" in normalized


def test_raw_text_is_not_mutated_by_normalizer() -> None:
    raw = "کيک 123\u0640"
    normalized = normalize_text(
        raw, NormalizationConfig(remove_tatweel=True, digit_policy=DigitPolicy.ASCII)
    )
    assert raw == "کيک 123\u0640"
    assert normalized == "کیک 123"


def test_digit_policies_are_explicit() -> None:
    assert normalize_text("١٢٣", NormalizationConfig(digit_policy=DigitPolicy.PRESERVE)) == "١٢٣"
    assert normalize_text("۱۲۳", NormalizationConfig(digit_policy=DigitPolicy.ARABIC)) == "١٢٣"


def test_digit_normalization_preserves_urls_emails_identifiers_and_dates() -> None:
    raw = "شماره ١٢٣ ID-42 ABC-42 2024-01-02 https://example.com/items/42 mail@example.com"

    assert normalize_text(raw) == (
        "شماره ۱۲۳ ID-42 ABC-42 2024-01-02 "
        "https://example.com/items/42 mail@example.com"
    )


def test_whitespace_line_break_and_zero_width_policies_are_explicit() -> None:
    raw = " متن\u200c\u200b  اول\r\n\tدوم "
    config = NormalizationConfig(
        unicode_form=UnicodeNormalizationForm.NFC,
        digit_policy=DigitPolicy.PRESERVE,
        whitespace_policy=WhitespacePolicy.COLLAPSE,
        line_break_policy=LineBreakPolicy.SPACE,
        zero_width_policy=ZeroWidthPolicy.REMOVE,
    )

    assert normalize_text(raw, config) == "متن اول دوم"


def test_normalization_policy_payload_is_stable_and_versioned() -> None:
    config = NormalizationConfig(
        unicode_form=UnicodeNormalizationForm.NFKC,
        digit_policy=DigitPolicy.ASCII,
        zero_width_policy=ZeroWidthPolicy.PRESERVE_NON_JOINER,
    )

    assert config.to_payload() == {
        "policy_version": "1.0.0",
        "unicode_form": "NFKC",
        "normalize_character_variants": True,
        "digit_policy": "ascii",
        "remove_tatweel": False,
        "whitespace_policy": "trim",
        "line_break_policy": "preserve",
        "zero_width_policy": "preserve_non_joiner",
        "trim_line_edges": True,
    }
