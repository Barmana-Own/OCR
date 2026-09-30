"""Deterministic OCR quality metric hooks."""

from __future__ import annotations

from collections.abc import Sequence


def _levenshtein(left: Sequence[str], right: Sequence[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            insertion = current[right_index - 1] + 1
            deletion = previous[right_index] + 1
            substitution = previous[right_index - 1] + (left_item != right_item)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    if not reference and not hypothesis:
        return 0.0
    if not reference:
        return 1.0
    return _levenshtein(list(reference), list(hypothesis)) / len(reference)


def wer(reference: str, hypothesis: str) -> float:
    reference_words = reference.split()
    hypothesis_words = hypothesis.split()
    if not reference_words and not hypothesis_words:
        return 0.0
    if not reference_words:
        return 1.0
    return _levenshtein(reference_words, hypothesis_words) / len(reference_words)


def normalized_difference(left: str, right: str) -> float:
    denominator = max(len(left), len(right), 1)
    return _levenshtein(list(left), list(right)) / denominator


def mean_confidence(values: Sequence[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def disagreement_rate(values: Sequence[str]) -> float:
    if len(values) < 2:
        return 0.0
    baseline = values[0]
    return sum(value != baseline for value in values[1:]) / (len(values) - 1)


def box_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    intersection_left = max(left[0], right[0])
    intersection_top = max(left[1], right[1])
    intersection_right = min(left[2], right[2])
    intersection_bottom = min(left[3], right[3])
    intersection_width = max(0.0, intersection_right - intersection_left)
    intersection_height = max(0.0, intersection_bottom - intersection_top)
    intersection = intersection_width * intersection_height
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def line_detection_precision_recall(
    predicted: Sequence[tuple[float, float, float, float]],
    reference: Sequence[tuple[float, float, float, float]],
    *,
    iou_threshold: float = 0.5,
) -> tuple[float, float]:
    if not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold must be between 0 and 1")
    unmatched = set(range(len(reference)))
    true_positives = 0
    for candidate in predicted:
        match = max(
            unmatched,
            key=lambda index: box_iou(candidate, reference[index]),
            default=None,
        )
        if match is not None and box_iou(candidate, reference[match]) >= iou_threshold:
            unmatched.remove(match)
            true_positives += 1
    precision = true_positives / len(predicted) if predicted else (1.0 if not reference else 0.0)
    recall = true_positives / len(reference) if reference else (1.0 if not predicted else 0.0)
    return precision, recall


def reading_order_accuracy(predicted: Sequence[str], reference: Sequence[str]) -> float:
    if not predicted and not reference:
        return 1.0
    if not reference:
        return 0.0
    return sum(
        predicted[index] == value for index, value in enumerate(reference) if index < len(predicted)
    ) / max(len(predicted), len(reference))


def exact_match_accuracy(predicted: Sequence[str], reference: Sequence[str]) -> float:
    if not predicted and not reference:
        return 1.0
    if not reference:
        return 0.0
    matches = sum(
        predicted[index] == value for index, value in enumerate(reference) if index < len(predicted)
    )
    return matches / len(reference)


def review_rate(reviewed: int, total: int) -> float:
    if reviewed < 0 or total < 0 or reviewed > total:
        raise ValueError("reviewed must be between zero and total")
    return reviewed / total if total else 0.0


def tiny_text_recovery_rate(recovered: int, total_tiny: int) -> float:
    if recovered < 0 or total_tiny < 0 or recovered > total_tiny:
        raise ValueError("recovered must be between zero and total_tiny")
    return recovered / total_tiny if total_tiny else 0.0
