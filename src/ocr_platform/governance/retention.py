"""Deterministic retention calculations independent of storage providers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import RetentionClass, RetentionPolicy


def retention_deadline(
    policy: RetentionPolicy,
    retention_class: RetentionClass,
    created_at: datetime,
) -> datetime:
    """Return a timezone-aware UTC deletion deadline for one artifact class."""

    normalized = (
        created_at.replace(tzinfo=UTC)
        if created_at.tzinfo is None
        else created_at.astimezone(UTC)
    )
    return normalized + timedelta(seconds=policy.seconds_for(retention_class))


def is_retention_expired(
    policy: RetentionPolicy,
    retention_class: RetentionClass,
    created_at: datetime,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(UTC)
    return current.astimezone(UTC) >= retention_deadline(policy, retention_class, created_at)
