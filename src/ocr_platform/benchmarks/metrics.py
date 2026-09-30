"""Reference-backed benchmark metric aggregation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ocr_platform.domain.models import VerificationStatus
from ocr_platform.quality.metrics import (
    box_iou,
    cer,
    exact_match_accuracy,
    line_detection_precision_recall,
    reading_order_accuracy,
    wer,
)

from .models import (
    BenchmarkCategory,
    BenchmarkMetrics,
    CategoryMetrics,
    GroundTruthDataset,
    GroundTruthDocument,
    GroundTruthLine,
    GroundTruthPage,
    PredictionDataset,
    PredictionDocument,
    PredictionLine,
    PredictionPage,
    TinyTextMetrics,
)
from .tiny_text import evaluate_tiny_text


def _text(raw_text: str, normalized_text: str | None) -> str:
    return normalized_text if normalized_text is not None else raw_text


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _page_pairs(
    reference: GroundTruthDocument,
    prediction: PredictionDocument,
) -> list[tuple[GroundTruthPage, PredictionPage | None]]:
    predictions = {page.page_number: page for page in prediction.pages}
    return [(page, predictions.get(page.page_number)) for page in reference.pages]


def _match_lines(
    reference: Sequence[GroundTruthLine],
    prediction: Sequence[PredictionLine],
    *,
    iou_threshold: float,
) -> tuple[list[tuple[GroundTruthLine, PredictionLine | None]], list[PredictionLine]]:
    by_id = {line.id: line for line in prediction}
    unmatched = set(range(len(prediction)))
    pairs: list[tuple[GroundTruthLine, PredictionLine | None]] = []
    for reference_line in sorted(reference, key=lambda line: line.reading_order):
        selected: int | None = None
        direct = by_id.get(reference_line.id)
        if direct is not None:
            selected = prediction.index(direct)
        else:
            selected = max(
                unmatched,
                key=lambda index: box_iou(
                    tuple(reference_line.bbox.as_list()),
                    tuple(prediction[index].bbox.as_list()),
                ),
                default=None,
            )
            if selected is not None and box_iou(
                tuple(reference_line.bbox.as_list()),
                tuple(prediction[selected].bbox.as_list()),
            ) < iou_threshold:
                selected = None
        if selected is not None and selected in unmatched:
            unmatched.remove(selected)
            pairs.append((reference_line, prediction[selected]))
        else:
            pairs.append((reference_line, None))
    return pairs, [prediction[index] for index in sorted(unmatched)]


def _detection_rates(
    pages: Sequence[tuple[GroundTruthPage, PredictionPage | None]],
    *,
    iou_threshold: float,
) -> tuple[float, float]:
    predicted_total = 0
    reference_total = 0
    weighted_precision = 0.0
    weighted_recall = 0.0
    for reference_page, prediction_page in pages:
        predicted = prediction_page.lines if prediction_page else []
        reference_boxes = [tuple(line.bbox.as_list()) for line in reference_page.lines]
        predicted_boxes = [tuple(line.bbox.as_list()) for line in predicted]
        precision, recall = line_detection_precision_recall(
            predicted_boxes,
            reference_boxes,
            iou_threshold=iou_threshold,
        )
        predicted_total += len(predicted_boxes)
        reference_total += len(reference_boxes)
        weighted_precision += precision * len(predicted_boxes)
        weighted_recall += recall * len(reference_boxes)
    return (
        weighted_precision / predicted_total
        if predicted_total
        else (1.0 if not reference_total else 0.0),
        weighted_recall / reference_total
        if reference_total
        else (1.0 if not predicted_total else 0.0),
    )


def _table_cell_accuracy(
    pages: Sequence[tuple[GroundTruthPage, PredictionPage | None]],
) -> tuple[int, int, float]:
    reference_cells = 0
    predicted_cells = 0
    matches = 0
    for reference_page, prediction_page in pages:
        predicted = prediction_page.table_cells if prediction_page else []
        by_position = {(cell.row, cell.column): cell for cell in predicted}
        predicted_cells += len(predicted)
        for cell in reference_page.table_cells:
            reference_cells += 1
            candidate = by_position.get((cell.row, cell.column))
            if candidate is not None and _text(cell.raw_text, cell.normalized_text) == _text(
                candidate.raw_text, candidate.normalized_text
            ):
                matches += 1
    return reference_cells, predicted_cells, matches / reference_cells if reference_cells else 1.0


def _tiny_text_metrics(
    references: Sequence[GroundTruthDocument],
    predictions: Sequence[PredictionDocument],
) -> TinyTextMetrics:
    by_id = {document.document_id: document for document in predictions}
    results = [
        evaluate_tiny_text(reference, by_id[reference.document_id])
        for reference in references
        if reference.document_id in by_id
    ]
    if not results:
        return TinyTextMetrics()
    fields = (
        "first_pass_cer",
        "high_dpi_cer",
        "crop_upscaled_cer",
        "verified_final_cer",
        "recovery_improvement",
    )
    values = {
        field: _mean(
            getattr(result, field)
            for result in results
            if getattr(result, field) is not None
        )
        if any(getattr(result, field) is not None for result in results)
        else None
        for field in fields
    }
    return TinyTextMetrics(count=sum(result.count for result in results), **values)


def evaluate_category(
    references: Sequence[GroundTruthDocument],
    predictions: Sequence[PredictionDocument],
    *,
    category: BenchmarkCategory | str | None = None,
    iou_threshold: float = 0.5,
) -> CategoryMetrics:
    """Evaluate a category without collapsing other categories into it."""

    if not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold must be between 0 and 1")
    reference_by_id = {document.document_id: document for document in references}
    prediction_by_id = {document.document_id: document for document in predictions}
    if set(reference_by_id) != set(prediction_by_id):
        raise ValueError("reference and prediction document IDs must match")
    selected_category = category or (references[0].category if references else "unknown")
    selected_category = (
        selected_category.value
        if isinstance(selected_category, BenchmarkCategory)
        else str(selected_category)
    )
    pages: list[tuple[GroundTruthPage, PredictionPage | None]] = []
    page_cer_values: list[float] = []
    page_wer_values: list[float] = []
    line_cer_values: list[float] = []
    line_wer_values: list[float] = []
    reference_line_count = 0
    predicted_line_count = 0
    matched_line_count = 0
    reading_values: list[float] = []
    automatic = verification = human_review = predicted_for_status = 0
    disagreement_lines = disagreed_lines = 0

    for reference_document in references:
        prediction_document = prediction_by_id[reference_document.document_id]
        for reference_page, prediction_page in _page_pairs(reference_document, prediction_document):
            pages.append((reference_page, prediction_page))
            prediction_lines = prediction_page.lines if prediction_page else []
            predicted_line_count += len(prediction_lines)
            predicted_for_status += len(prediction_lines)
            page_text = prediction_page.page_text if prediction_page else ""
            page_cer_values.append(cer(reference_page.page_text, page_text))
            page_wer_values.append(wer(reference_page.page_text, page_text))
            pairs, _ = _match_lines(
                reference_page.lines,
                prediction_lines,
                iou_threshold=iou_threshold,
            )
            reference_line_count += len(reference_page.lines)
            matched_line_count += sum(candidate is not None for _, candidate in pairs)
            for reference_line, candidate in pairs:
                expected = _text(reference_line.raw_text, reference_line.normalized_text)
                actual = _text(candidate.raw_text, candidate.normalized_text) if candidate else ""
                line_cer_values.append(cer(expected, actual))
                line_wer_values.append(wer(expected, actual))
            for candidate in prediction_lines:
                automatic += candidate.verification_status == VerificationStatus.ACCEPTED
                verification += candidate.sent_to_verification
                human_review += (
                    candidate.verification_status == VerificationStatus.HUMAN_REVIEW_REQUIRED
                )
                if len(candidate.candidates) >= 2:
                    disagreement_lines += 1
                    candidate_texts = {
                        _text(item.raw_text, item.normalized_text)
                        for item in candidate.candidates
                    }
                    disagreed_lines += len(candidate_texts) > 1
            reading_values.append(
                reading_order_accuracy(
                    [
                        line.id
                        for line in sorted(
                            prediction_lines, key=lambda line: line.reading_order
                        )
                    ],
                    [
                        line.id
                        for line in sorted(
                            reference_page.lines, key=lambda line: line.reading_order
                        )
                    ],
                )
            )

    precision, recall = _detection_rates(pages, iou_threshold=iou_threshold)
    reference_cells, predicted_cells, table_accuracy = _table_cell_accuracy(pages)
    tiny = _tiny_text_metrics(references, predictions)
    reference_texts = [
        _text(line.raw_text, line.normalized_text)
        for document in references
        for page in document.pages
        for line in page.lines
    ]
    return CategoryMetrics(
        category=selected_category,
        document_count=len(references),
        page_count=len(pages),
        reference_line_count=reference_line_count,
        predicted_line_count=predicted_line_count,
        matched_line_count=matched_line_count,
        reference_table_cell_count=reference_cells,
        predicted_table_cell_count=predicted_cells,
        page_cer=_mean(page_cer_values),
        page_wer=_mean(page_wer_values),
        cer=_mean(line_cer_values),
        wer=_mean(line_wer_values),
        exact_line_accuracy=exact_match_accuracy(
            [
                _text(candidate.raw_text, candidate.normalized_text)
                if candidate is not None
                else ""
                for page in pages
                for reference_line, candidate in _match_lines(
                    page[0].lines,
                    page[1].lines if page[1] else [],
                    iou_threshold=iou_threshold,
                )[0]
            ],
            reference_texts,
        ),
        line_detection_precision=precision,
        line_detection_recall=recall,
        reading_order_accuracy=_mean(reading_values),
        table_cell_accuracy=table_accuracy,
        accepted_automatically_rate=(
            automatic / predicted_for_status if predicted_for_status else 0.0
        ),
        verification_rate=(verification / predicted_for_status if predicted_for_status else 0.0),
        human_review_rate=(human_review / predicted_for_status if predicted_for_status else 0.0),
        backend_disagreement_rate=(
            disagreed_lines / disagreement_lines if disagreement_lines else 0.0
        ),
        tiny_text=tiny,
    )


def evaluate_dataset(
    ground_truth: GroundTruthDataset,
    predictions: PredictionDataset,
    *,
    iou_threshold: float = 0.5,
) -> BenchmarkMetrics:
    """Evaluate every category and retain a clearly labeled overall view."""

    prediction_by_id = {document.document_id: document for document in predictions.documents}
    grouped: dict[BenchmarkCategory, list[GroundTruthDocument]] = {}
    for document in ground_truth.documents:
        grouped.setdefault(document.category, []).append(document)
    category_results = [
        evaluate_category(
            documents,
            [prediction_by_id[item.document_id] for item in documents],
            category=category,
            iou_threshold=iou_threshold,
        )
        for category, documents in sorted(grouped.items(), key=lambda item: item[0].value)
    ]
    overall = evaluate_category(
        ground_truth.documents,
        [prediction_by_id[item.document_id] for item in ground_truth.documents],
        category="overall",
        iou_threshold=iou_threshold,
    )
    return BenchmarkMetrics(categories=category_results, overall=overall)
