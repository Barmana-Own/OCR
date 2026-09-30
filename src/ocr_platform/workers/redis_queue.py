"""Optional Redis queue primitives for multi-process job workers."""

from __future__ import annotations

import json

from ocr_platform.errors import BackendUnavailableError, ProcessingError, QueueCapacityError


class RedisJobQueue:
    """Reliable-list queue with an explicit in-flight acknowledgement boundary."""

    def __init__(
        self,
        url: str,
        *,
        queue_name: str = "ocr:jobs",
        max_queued_jobs: int | None = None,
        client=None,
    ) -> None:
        if not url.strip() or not queue_name.strip():
            raise ValueError("Redis URL and queue name are required")
        if max_queued_jobs is not None and max_queued_jobs <= 0:
            raise ValueError("Redis queue capacity must be positive")
        self.url = url
        self.queue_name = queue_name
        self.processing_queue_name = f"{queue_name}:processing"
        self.max_queued_jobs = max_queued_jobs
        self._client = client

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        try:
            import redis
        except ImportError as exc:
            raise BackendUnavailableError(
                "Redis queue requires the optional 'distributed' extra"
            ) from exc
        self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    def enqueue(self, job_id: str) -> None:
        try:
            client = self._client_or_raise()
            if self.max_queued_jobs is not None and callable(getattr(client, "llen", None)):
                queue_size = int(client.llen(self.queue_name))
                processing_size = int(client.llen(self.processing_queue_name))
                if queue_size + processing_size >= self.max_queued_jobs:
                    raise QueueCapacityError()
            client.rpush(self.queue_name, json.dumps({"job_id": job_id}))
        except BackendUnavailableError:
            raise
        except QueueCapacityError:
            raise
        except Exception as exc:
            raise ProcessingError("Redis job enqueue failed", retryable=True) from exc

    def dequeue(self, *, timeout_seconds: int = 5) -> str | None:
        if timeout_seconds < 0:
            raise ValueError("Redis dequeue timeout cannot be negative")
        try:
            client = self._client_or_raise()
            if callable(getattr(client, "brpoplpush", None)):
                item = client.brpoplpush(
                    self.queue_name,
                    self.processing_queue_name,
                    timeout=timeout_seconds,
                )
            else:
                item = client.blpop(self.queue_name, timeout=timeout_seconds)
        except BackendUnavailableError:
            raise
        except Exception as exc:
            raise ProcessingError("Redis job dequeue failed", retryable=True) from exc
        if not item:
            return None
        try:
            raw_payload = item if isinstance(item, (str, bytes, bytearray)) else item[1]
            payload = json.loads(raw_payload)
            job_id = payload["job_id"]
            if not isinstance(job_id, str) or not job_id:
                raise ValueError
            return job_id
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ProcessingError("Redis queue contained an invalid job envelope") from exc

    def ack(self, job_id: str) -> None:
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("Redis acknowledgement requires a job id")
        try:
            client = self._client_or_raise()
            if callable(getattr(client, "lrem", None)):
                client.lrem(
                    self.processing_queue_name,
                    1,
                    json.dumps({"job_id": job_id}),
                )
        except BackendUnavailableError:
            raise
        except Exception as exc:
            raise ProcessingError("Redis job acknowledgement failed", retryable=True) from exc



__all__ = ["RedisJobQueue"]
