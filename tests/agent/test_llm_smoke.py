"""Smoke test for the llm pytest marker and --run-llm opt-in.

This test is intentionally minimal: it only verifies that the marker
infrastructure works.  No real LLM call is made.

Spec: AGENT-FR-003, AGENT-FR-010.
"""

from __future__ import annotations

import pytest


@pytest.mark.llm
def test_llm_marker_smoke() -> None:
    """Passes trivially when --run-llm is given; skipped otherwise."""
    assert True
