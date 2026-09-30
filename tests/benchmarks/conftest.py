from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep deterministic benchmark tests selectable independently in CI."""

    for item in items:
        item.add_marker(pytest.mark.benchmark)
