"""Configurable Persian/Arabic normalization that preserves raw input."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class DigitPolicy(StrEnum):
    PRESERVE = "preserve"
    PERSIAN = "persian"
    ARABIC = "arabic"
    ASCII = "ascii"


class UnicodeNormalizationForm(StrEnum):
    NFC = "NFC"
    NFKC = "NFKC"
    NFD = "NFD"
    NFKD = "NFKD"


class WhitespacePolicy(StrEnum):
    PRESERVE = "preserve"
    TRIM = "trim"
    COLLAPSE = "collapse"


class LineBreakPolicy(StrEnum):
    PRESERVE = "preserve"
    SPACE = "space"
    REMOVE = "remove"


class ZeroWidthPolicy(StrEnum):
    PRESERVE = "preserve"
    PRESERVE_NON_JOINER = "preserve_non_joiner"
    REMOVE = "remove"


NORMALIZATION_POLICY_VERSION = "1.0.0"


@dataclass(frozen=True)
class NormalizationConfig:
    policy_version: str = NORMALIZATION_POLICY_VERSION
    unicode_form: UnicodeNormalizationForm = UnicodeNormalizationForm.NFC
    normalize_character_variants: bool = True
    digit_policy: DigitPolicy = DigitPolicy.PERSIAN
    remove_tatweel: bool = False
    whitespace_policy: WhitespacePolicy = WhitespacePolicy.TRIM
    line_break_policy: LineBreakPolicy = LineBreakPolicy.PRESERVE
    zero_width_policy: ZeroWidthPolicy = ZeroWidthPolicy.PRESERVE
    trim_line_edges: bool = True

    def __post_init__(self) -> None:
        if not self.policy_version or any(ord(char) < 32 for char in self.policy_version):
            raise ValueError("policy_version must be safe and non-empty")
        for field_name, enum_type in (
            ("unicode_form", UnicodeNormalizationForm),
            ("digit_policy", DigitPolicy),
            ("whitespace_policy", WhitespacePolicy),
            ("line_break_policy", LineBreakPolicy),
            ("zero_width_policy", ZeroWidthPolicy),
        ):
            value = getattr(self, field_name)
            try:
                normalized = enum_type(value)
            except ValueError as exc:
                raise ValueError(f"invalid {field_name}: {value!r}") from exc
            object.__setattr__(self, field_name, normalized)

    def to_payload(self) -> dict[str, str | bool]:
        return {
            "policy_version": self.policy_version,
            "unicode_form": self.unicode_form.value,
            "normalize_character_variants": self.normalize_character_variants,
            "digit_policy": self.digit_policy.value,
            "remove_tatweel": self.remove_tatweel,
            "whitespace_policy": self.whitespace_policy.value,
            "line_break_policy": self.line_break_policy.value,
            "zero_width_policy": self.zero_width_policy.value,
            "trim_line_edges": self.trim_line_edges,
        }


_CHAR_MAP = {
    "\u064a": "\u06cc",
    "\u0649": "\u06cc",
    "\u0643": "\u06a9",
    "\u0629": "\u0647",
}
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ASCII_DIGITS = "0123456789"
_ZERO_WIDTH_CHARS = frozenset(
    {
        "\u061c",  # Arabic Letter Mark
        "\u200b",  # Zero Width Space
        "\u200c",  # Zero Width Non-Joiner
        "\u200d",  # Zero Width Joiner
        "\u200e",  # Left-to-Right Mark
        "\u200f",  # Right-to-Left Mark
        "\u2060",  # Word Joiner
        "\ufeff",  # Zero Width No-Break Space/BOM
    }
)
_PROTECTED_TOKEN_RE = re.compile(
    r"(?:"
    r"(?i:\b(?:https?://|ftp://|www\.)[^\s<>()]+)"
    r"|(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"
    r"|(?<!\w)(?=[A-Za-z0-9٠-٩۰-۹:/._+-]*\d)"
    r"[A-Za-z0-9٠-٩۰-۹]+(?:[-/:._][A-Za-z0-9٠-٩۰-۹]+)+(?!\w)"
    r"|(?<!\w)(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)"
    r"[A-Za-z0-9]+(?!\w)"
    r")"
)


def normalize_text(value: str, config: NormalizationConfig | None = None) -> str:
    selected = config or NormalizationConfig()
    result = unicodedata.normalize(selected.unicode_form.value, value)
    result = _normalize_line_breaks(result, selected.line_break_policy)
    result = _normalize_zero_width(result, selected.zero_width_policy)
    if selected.normalize_character_variants:
        result = "".join(_CHAR_MAP.get(char, char) for char in result)
        if selected.remove_tatweel:
            result = result.replace("\u0640", "")
    if selected.digit_policy != DigitPolicy.PRESERVE:
        result = _normalize_digits_outside_protected_tokens(result, selected.digit_policy)
    if selected.whitespace_policy == WhitespacePolicy.COLLAPSE:
        result = re.sub(r"\s+", " ", result)
    if selected.trim_line_edges or selected.whitespace_policy == WhitespacePolicy.TRIM:
        result = result.strip()
    return result


def _normalize_digits(value: str, policy: DigitPolicy) -> str:
    output: list[str] = []
    for char in value:
        if char in _ARABIC_DIGITS:
            index = _ARABIC_DIGITS.index(char)
            output.append(
                _PERSIAN_DIGITS[index] if policy == DigitPolicy.PERSIAN else _ASCII_DIGITS[index]
            )
        elif char in _PERSIAN_DIGITS:
            index = _PERSIAN_DIGITS.index(char)
            output.append(
                _ARABIC_DIGITS[index]
                if policy == DigitPolicy.ARABIC
                else _PERSIAN_DIGITS[index]
                if policy == DigitPolicy.PERSIAN
                else _ASCII_DIGITS[index]
            )
        elif char in _ASCII_DIGITS and policy == DigitPolicy.PERSIAN:
            output.append(_PERSIAN_DIGITS[_ASCII_DIGITS.index(char)])
        elif char in _ASCII_DIGITS and policy == DigitPolicy.ARABIC:
            output.append(_ARABIC_DIGITS[_ASCII_DIGITS.index(char)])
        else:
            output.append(char)
    return "".join(output)


def _normalize_digits_outside_protected_tokens(value: str, policy: DigitPolicy) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _PROTECTED_TOKEN_RE.finditer(value):
        pieces.append(_normalize_digits(value[cursor : match.start()], policy))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(_normalize_digits(value[cursor:], policy))
    return "".join(pieces)


def _normalize_line_breaks(value: str, policy: LineBreakPolicy) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if policy == LineBreakPolicy.SPACE:
        return value.replace("\n", " ")
    if policy == LineBreakPolicy.REMOVE:
        return value.replace("\n", "")
    return value


def _normalize_zero_width(value: str, policy: ZeroWidthPolicy) -> str:
    if policy == ZeroWidthPolicy.PRESERVE:
        return value
    if policy == ZeroWidthPolicy.PRESERVE_NON_JOINER:
        return "".join(char for char in value if char not in _ZERO_WIDTH_CHARS or char == "\u200c")
    return "".join(char for char in value if char not in _ZERO_WIDTH_CHARS)
