"""Stable JSON hashing and content-addressable identifier helpers."""

from __future__ import annotations

import hashlib
import json
import re

_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def stable_hash(value: object) -> str:
    """Hash JSON-compatible data with a canonical, Unicode-preserving encoding."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_id(namespace: str, value: object, *, digest_length: int = 16) -> str:
    """Create a stable, human-prefixed identifier from JSON-compatible content."""

    if not _NAMESPACE_PATTERN.fullmatch(namespace):
        raise ValueError("identifier namespace must be lowercase alphanumeric text")
    if not 8 <= digest_length <= 64:
        raise ValueError("identifier digest length must be between 8 and 64")
    digest = stable_hash({"namespace": namespace, "value": value})
    return f"{namespace}-{digest[:digest_length]}"
