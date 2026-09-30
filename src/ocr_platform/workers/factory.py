"""Construction of optional durable worker queues."""

from __future__ import annotations

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError

from .ports import JobQueue
from .redis_queue import RedisJobQueue


def build_job_queue(settings: Settings) -> JobQueue | None:
    if settings.queue_backend == "local":
        return None
    if settings.queue_backend == "redis" and settings.redis_url:
        return RedisJobQueue(
            settings.redis_url,
            queue_name=settings.redis_queue_name,
            max_queued_jobs=settings.max_queued_jobs,
        )
    raise ConfigurationError("unsupported or incomplete job queue backend")


__all__ = ["build_job_queue"]
