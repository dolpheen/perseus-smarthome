"""Agent test suite configuration.

Tests that call the real LLM provider are marked ``@pytest.mark.llm``
and skipped by default.  Pass ``--run-llm`` to opt in:

    LLM_API_KEY=<key> uv run pytest tests/agent/ --run-llm

The ``--run-llm`` option is registered in ``tests/conftest.py`` so it
is available from any pytest invocation at the repository root.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-llm"):
        return
    skip_llm = pytest.mark.skip(
        reason="llm-only; pass --run-llm with LLM_API_KEY set"
    )
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)
