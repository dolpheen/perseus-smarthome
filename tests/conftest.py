"""Top-level test suite configuration.

Options that must be registered before argument parsing (so they are
available to any ``pytest -m <marker> --<opt>`` invocation from the
repository root) live here.

- ``--run-llm``: opt into ``@pytest.mark.llm`` tests that call a real
  LLM provider.  Handled by ``tests/agent/conftest.py``.
- ``--run-hardware``: opt into ``@pytest.mark.hardware`` loopback tests.
  Handled by ``tests/e2e/conftest.py``.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="Run @pytest.mark.llm tests (skipped by default; set LLM_API_KEY in .env for real calls).",
    )
