from ocr_platform.ocr.verification.comparison import compare_text


def test_comparison_preserves_raw_text_and_detects_persian_normalized_agreement() -> None:
    left = "شماره قرارداد ١٢٣٤٥"
    right = "شماره قرارداد ۱۲۳۴۵"

    comparison = compare_text(left, right)

    assert comparison.left == left
    assert comparison.right == right
    assert comparison.exact is False
    assert comparison.unicode_equal is False
    assert comparison.normalized_equal is True
    assert comparison.edit_distance == 5
    assert comparison.cer_like == 5 / 19
    assert comparison.digit_only_disagreement is False


def test_comparison_classifies_single_digit_difference_without_reordering_rtl_text() -> None:
    comparison = compare_text("شماره ۱۲۳٤", "شماره ۱۲۴٤")

    assert comparison.normalized_equal is False
    assert comparison.digit_only_disagreement is True
    assert comparison.punctuation_only_disagreement is False
    assert comparison.whitespace_only_disagreement is False
    assert comparison.edit_distance == 1


def test_comparison_classifies_punctuation_and_whitespace_differences() -> None:
    punctuation = compare_text("Invoice: A-12", "Invoice A-12")
    whitespace = compare_text("A  B", "A B")

    assert punctuation.punctuation_only_disagreement is True
    assert punctuation.whitespace_only_disagreement is False
    assert whitespace.whitespace_only_disagreement is True
    assert whitespace.punctuation_only_disagreement is False


def test_comparison_handles_mixed_rtl_ltr_content_without_reversing_it() -> None:
    comparison = compare_text("ایمیل: user@example.com", "ایمیل: user@example.coм")

    assert comparison.left == "ایمیل: user@example.com"
    assert comparison.right == "ایمیل: user@example.coм"
    assert comparison.normalized_equal is False
    assert comparison.edit_distance == 1
