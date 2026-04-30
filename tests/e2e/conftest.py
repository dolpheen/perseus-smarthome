"""E2E suite configuration.

Loopback tests (`@pytest.mark.hardware`) require GPIO23 wired to GPIO24
through a current-limiting resistor on the target board. Without the
wiring those tests cannot pass, so they are skipped by default. Pass
``--run-hardware`` to opt in once the loopback is wired:

    RPI_MCP_URL=http://<pi>:8000/mcp uv run pytest tests/e2e/ --run-hardware
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-hardware",
        action="store_true",
        default=False,
        help="Run @pytest.mark.hardware tests (requires GPIO23↔GPIO24 loopback wiring).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-hardware"):
        return
    skip_hardware = pytest.mark.skip(
        reason="hardware-only; pass --run-hardware once GPIO23↔GPIO24 is wired"
    )
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip_hardware)
