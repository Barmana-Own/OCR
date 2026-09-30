from __future__ import annotations

from io import BytesIO

import pytest

from ocr_platform.errors import ArtifactStorageError, QueueCapacityError
from ocr_platform.storage import S3ArtifactStore, read_artifact_uri
from ocr_platform.workers import RedisJobQueue


class _MissingObject(Exception):
    response = {"Error": {"Code": "404"}}


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[f"{Bucket}/{Key}"] = Body

    def head_object(self, *, Bucket: str, Key: str) -> None:
        if f"{Bucket}/{Key}" not in self.objects:
            raise _MissingObject()

    def get_object(self, *, Bucket: str, Key: str):
        try:
            value = self.objects[f"{Bucket}/{Key}"]
        except KeyError as exc:
            raise _MissingObject() from exc
        return {"Body": BytesIO(value)}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, **_kwargs):
        prefix = f"{Bucket}/{Prefix}"
        return {
            "Contents": [
                {"Key": key[len(Bucket) + 1 :]}
                for key in self.objects
                if key.startswith(prefix)
            ],
            "IsTruncated": False,
        }

    def delete_objects(self, *, Bucket: str, Delete: dict[str, object]) -> None:
        for item in Delete["Objects"]:
            self.objects.pop(f"{Bucket}/{item['Key']}", None)


def test_s3_store_is_immutable_and_uri_readable(tmp_path) -> None:
    client = _FakeS3()
    store = S3ArtifactStore(
        bucket="ocr-test",
        prefix="ocr",
        cache_root=tmp_path / "cache",
        client=client,
    )
    artifact = store.put_bytes("doc-1", "pages/page-0001.png", b"bytes")

    assert store.exists("doc-1", "pages/page-0001.png")
    assert read_artifact_uri(store, artifact.uri) == b"bytes"
    with pytest.raises(ArtifactStorageError):
        store.put_bytes("doc-1", "pages/page-0001.png", b"changed")
    assert store.delete_document("doc-1") == 1
    assert not store.exists("doc-1", "pages/page-0001.png")


def test_s3_store_rejects_unsafe_prefix(tmp_path) -> None:
    with pytest.raises(ValueError, match="unsafe path component"):
        S3ArtifactStore(
            bucket="ocr-test",
            prefix="ocr/../escape",
            cache_root=tmp_path / "cache",
            client=_FakeS3(),
        )


class _FakeRedis:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []
        self.processing: list[str] = []

    def rpush(self, queue: str, item: str) -> None:
        self.items.append((queue, item))

    def blpop(self, queue: str, timeout: int):
        del timeout
        if not self.items:
            return None
        selected_queue, item = self.items.pop(0)
        assert selected_queue == queue
        return selected_queue, item

    def brpoplpush(self, source: str, destination: str, timeout: int):
        del timeout
        if not self.items:
            return None
        selected_queue, item = self.items.pop()
        assert selected_queue == source
        assert destination.endswith(":processing")
        self.processing.append(item)
        return item

    def lrem(self, queue: str, count: int, item: str) -> int:
        assert queue.endswith(":processing")
        assert count == 1
        try:
            self.processing.remove(item)
        except ValueError:
            return 0
        return 1

    def llen(self, queue: str) -> int:
        if queue.endswith(":processing"):
            return len(self.processing)
        return len(self.items)


def test_redis_queue_round_trips_job_ids() -> None:
    client = _FakeRedis()
    queue = RedisJobQueue("redis://unused", client=client)
    queue.enqueue("job-123")
    assert queue.dequeue(timeout_seconds=0) == "job-123"
    queue.ack("job-123")
    assert client.processing == []


def test_redis_queue_enforces_configured_capacity() -> None:
    client = _FakeRedis()
    queue = RedisJobQueue("redis://unused", max_queued_jobs=1, client=client)
    queue.enqueue("job-123")
    with pytest.raises(QueueCapacityError):
        queue.enqueue("job-456")
