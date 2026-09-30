from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ocr_platform.governance import (
    RetentionClass,
    RetentionPolicy,
    ReviewAction,
    ReviewAuditEvent,
    ReviewFieldChange,
)
from ocr_platform.governance.retention import retention_deadline


def test_retention_policy_resolves_each_sensitive_artifact_class() -> None:
    policy = RetentionPolicy(
        temporary_seconds=60,
        source_seconds=120,
        derived_seconds=180,
        verified_dataset_seconds=240,
    )

    assert policy.seconds_for(RetentionClass.TEMPORARY_PROCESSING) == 60
    assert policy.seconds_for(RetentionClass.ORIGINAL_SOURCE) == 120
    assert policy.seconds_for(RetentionClass.DERIVED_PAGE_IMAGES) == 180
    assert policy.seconds_for(RetentionClass.VERIFIED_DATASET_ARTIFACTS) == 240
    assert retention_deadline(
        policy,
        RetentionClass.ORIGINAL_SOURCE,
        datetime(2026, 9, 27, tzinfo=UTC),
    ) == datetime(2026, 9, 27, 0, 2, tzinfo=UTC)


def test_review_audit_event_preserves_previous_and_new_values_without_mutation() -> None:
    event = ReviewAuditEvent(
        id="review-1",
        document_id="doc-1",
        target_id="line-1",
        target_type="line",
        reviewer_id="reviewer-1",
        action=ReviewAction.CORRECTED,
        reason="Verified against source crop",
        changed_fields=(
            ReviewFieldChange(
                field_name="raw_text",
                previous_value="قرارداد ۱۲۳",
                new_value="قرارداد ۱۲۴",
            ),
        ),
    )

    payload = event.model_dump(mode="json")

    assert payload["action"] == "corrected"
    assert payload["changed_fields"][0]["previous_value"] == "قرارداد ۱۲۳"
    assert payload["changed_fields"][0]["new_value"] == "قرارداد ۱۲۴"
    with pytest.raises((TypeError, ValidationError)):
        event.action = ReviewAction.ACCEPTED


def test_retention_policy_rejects_non_positive_windows() -> None:
    with pytest.raises(ValidationError):
        RetentionPolicy(temporary_seconds=0)

