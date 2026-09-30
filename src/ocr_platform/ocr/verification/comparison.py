"""Deterministic, Unicode-aware comparison of OCR candidate text.

Comparison is deliberately non-destructive: callers retain the original
candidate strings while this module derives temporary comparison views for
agreement and disagreement classification.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from ocr_platform.normalization import normalize_text


@dataclass(frozen=True, slots=True)
class TextComparison:
    """Comparable evidence derived from two raw candidate strings."""

    left: str
    right: str
    exact: bool
    unicode_equal: bool
    normalized_equal: bool
    edit_distance: int
    cer_like: float
    digit_only_disagreement: bool
    punctuation_only_disagreement: bool
    whitespace_only_disagreement: bool


def unicode_normalize(text: str) -> str:
    """Return NFC text for comparison without changing the stored raw value."""

    return unicodedata.normalize("NFC", text)


def edit_distance(left: str, right: str) -> int:
    """Compute Levenshtein distance using code points, without reordering text."""

    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insertion = current[right_index - 1] + 1
            deletion = previous[right_index] + 1
            substitution = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def cer_like_distance(left: str, right: str) -> float:
    """Return a bounded edit-distance ratio suitable for candidate comparison."""

    left_nfc = unicode_normalize(left)
    right_nfc = unicode_normalize(right)
    denominator = max(len(left_nfc), len(right_nfc))
    if denominator == 0:
        return 0.0
    return edit_distance(left_nfc, right_nfc) / denominator


def _without(text: str, predicate: Callable[[str], bool]) -> str:
    return "".join(char for char in unicode_normalize(text) if not predicate(char))


def _digits(text: str) -> str:
    return "".join(char for char in unicode_normalize(normalize_text(text)) if char.isdigit())


def compare_text(left: str, right: str) -> TextComparison:
    """Compare raw OCR candidates with explicit agreement classifications."""

    left_nfc = unicode_normalize(left)
    right_nfc = unicode_normalize(right)
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    normalized_equal = left_normalized == right_normalized
    punctuation_stripped_equal = _without(left_normalized, _is_punctuation) == _without(
        right_normalized, _is_punctuation
    )
    whitespace_stripped_equal = _without(left_normalized, str.isspace) == _without(
        right_normalized, str.isspace
    )
    left_digits = _digits(left)
    right_digits = _digits(right)
    digits_are_different = left_digits != right_digits
    return TextComparison(
        left=left,
        right=right,
        exact=left == right,
        unicode_equal=left_nfc == right_nfc,
        normalized_equal=normalized_equal,
        edit_distance=edit_distance(left_nfc, right_nfc),
        cer_like=cer_like_distance(left_nfc, right_nfc),
        digit_only_disagreement=(
            not normalized_equal
            and digits_are_different
            and _without(left_normalized, str.isdigit)
            == _without(right_normalized, str.isdigit)
        ),
        punctuation_only_disagreement=(
            not normalized_equal
            and punctuation_stripped_equal
            and not whitespace_stripped_equal
        ),
        whitespace_only_disagreement=(
            not normalized_equal
            and whitespace_stripped_equal
            and not punctuation_stripped_equal
        ),
    )


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P")


def exact_agreement(left: str, right: str) -> bool:
    return compare_text(left, right).exact


def normalized_agreement(left: str, right: str) -> bool:
    return compare_text(left, right).normalized_equal


__all__ = [
    "TextComparison",
    "cer_like_distance",
    "compare_text",
    "edit_distance",
    "exact_agreement",
    "normalized_agreement",
    "unicode_normalize",
]
