"""MacBook E2E tests for the Raspberry Pi I/O MCP server.

These tests connect to a real Raspberry Pi MCP server over streamable HTTP.
They require a loopback wire between GPIO23 (output) and GPIO24 (input) with
a current-limiting resistor for the hardware/loopback tests.

Run with:
    RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py

All tests are marked @pytest.mark.e2e and are excluded from the default
``uv run pytest -m "not e2e and not hardware"`` run.

Spec: IO-MCP-FR-007, IO-MCP-FR-009, IO-MCP-FR-010, IO-MCP-FR-011
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_url() -> str:
    """Return the MCP server URL from the environment.

    Calls pytest.fail (not skip) when RPI_MCP_URL is unset so the caller
    gets a clear, non-silent failure rather than a mysterious error later.
    Per IO-MCP-FR-010.
    """
    url = os.environ.get("RPI_MCP_URL")
    if not url:
        pytest.fail(
            "RPI_MCP_URL environment variable is not set. "
            "Run: RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py"
        )
    return url


def _result_dict(result: Any) -> dict[str, Any]:
    """Extract a structured dict from a CallToolResult.

    Prefers ``structuredContent`` (set by FastMCP for dict-returning tools)
    and falls back to parsing the first TextContent block as JSON.
    """
    if result.structuredContent is not None:
        return result.structuredContent
    if result.content:
        return json.loads(result.content[0].text)
    raise AssertionError(f"CallToolResult has no content: {result!r}")


async def _run_with_session(url: str, session_callback: Any) -> Any:
    """Open a streamable-HTTP MCP session and run session_callback(session).

    Calls pytest.fail with a clear message when the server is unreachable,
    per IO-MCP-FR-010.
    """
    import httpx

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    try:
        async with streamablehttp_client(url, timeout=10.0) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session_callback(session)
    except* httpx.ConnectError as eg:
        pytest.fail(
            f"Cannot connect to MCP server at {url!r}. "
            f"Check that the server is running and the URL is correct. "
            f"Error: {eg.exceptions[0]}"
        )
    except* (httpx.TimeoutException, httpx.HTTPError) as eg:
        pytest.fail(
            f"HTTP error connecting to MCP server at {url!r}: {eg.exceptions[0]}"
        )


def _run(coro_fn: Any) -> Any:
    """Call _run_with_session synchronously for use in non-async tests."""
    url = _get_url()
    return asyncio.run(_run_with_session(url, coro_fn))


# ---------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_list_devices_returns_gpio23_output() -> None:
    """list_devices must include gpio23_output (IO-MCP-FR-007)."""
    async def _check(session):
        result = _result_dict(await session.call_tool("list_devices", {}))
        ids = {d["id"] for d in result["devices"]}
        assert "gpio23_output" in ids

    _run(_check)


@pytest.mark.e2e
def test_list_devices_returns_gpio24_input() -> None:
    """list_devices must include gpio24_input (IO-MCP-FR-007)."""
    async def _check(session):
        result = _result_dict(await session.call_tool("list_devices", {}))
        ids = {d["id"] for d in result["devices"]}
        assert "gpio24_input" in ids

    _run(_check)


@pytest.mark.e2e
def test_list_devices_output_has_set_output_capability() -> None:
    """gpio23_output must advertise the set_output capability."""
    async def _check(session):
        result = _result_dict(await session.call_tool("list_devices", {}))
        output = next(d for d in result["devices"] if d["id"] == "gpio23_output")
        assert "set_output" in output["capabilities"]

    _run(_check)


@pytest.mark.e2e
def test_list_devices_input_has_read_input_capability() -> None:
    """gpio24_input must advertise the read_input capability."""
    async def _check(session):
        result = _result_dict(await session.call_tool("list_devices", {}))
        input_dev = next(d for d in result["devices"] if d["id"] == "gpio24_input")
        assert "read_input" in input_dev["capabilities"]

    _run(_check)


# ---------------------------------------------------------------------------
# Loopback: GPIO23 output → GPIO24 input
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.hardware
def test_loopback_high() -> None:
    """set_output(gpio23_output, 1) then read_input(gpio24_input) returns 1.

    Requires GPIO23 wired to GPIO24 via a current-limiting resistor.
    Spec: IO-MCP-FR-009, IO-MCP-FR-011.
    """
    async def _check(session):
        set_result = _result_dict(
            await session.call_tool("set_output", {"device_id": "gpio23_output", "value": 1})
        )
        assert set_result["ok"] is True, f"set_output high failed: {set_result}"

        read_result = _result_dict(
            await session.call_tool("read_input", {"device_id": "gpio24_input"})
        )
        assert read_result["ok"] is True, f"read_input failed: {read_result}"
        assert read_result["value"] == 1, (
            f"Expected GPIO24 to read 1 after GPIO23 set high, got {read_result['value']}. "
            "Check the loopback wiring (GPIO23 → resistor → GPIO24)."
        )

    _run(_check)


@pytest.mark.e2e
@pytest.mark.hardware
def test_loopback_low() -> None:
    """set_output(gpio23_output, 0) then read_input(gpio24_input) returns 0.

    Requires GPIO23 wired to GPIO24 via a current-limiting resistor.
    Spec: IO-MCP-FR-009, IO-MCP-FR-011.
    """
    async def _check(session):
        # Drive high first to ensure we're testing a transition.
        setup_result = _result_dict(
            await session.call_tool("set_output", {"device_id": "gpio23_output", "value": 1})
        )
        assert setup_result["ok"] is True, f"setup set_output high failed: {setup_result}"

        set_result = _result_dict(
            await session.call_tool("set_output", {"device_id": "gpio23_output", "value": 0})
        )
        assert set_result["ok"] is True, f"set_output low failed: {set_result}"

        read_result = _result_dict(
            await session.call_tool("read_input", {"device_id": "gpio24_input"})
        )
        assert read_result["ok"] is True, f"read_input failed: {read_result}"
        assert read_result["value"] == 0, (
            f"Expected GPIO24 to read 0 after GPIO23 set low, got {read_result['value']}. "
            "Check the loopback wiring (GPIO23 → resistor → GPIO24)."
        )

    _run(_check)


# ---------------------------------------------------------------------------
# Disallowed / unknown device rejection
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_unknown_device_set_output_rejected() -> None:
    """set_output on an unknown device must return a structured error (IO-MCP-FR-009)."""
    async def _check(session):
        result = _result_dict(
            await session.call_tool("set_output", {"device_id": "nonexistent_device", "value": 1})
        )
        assert result["ok"] is False
        assert result["error"] == "unknown_device"

    _run(_check)


@pytest.mark.e2e
def test_unknown_device_read_input_rejected() -> None:
    """read_input on an unknown device must return a structured error (IO-MCP-FR-009)."""
    async def _check(session):
        result = _result_dict(
            await session.call_tool("read_input", {"device_id": "nonexistent_device"})
        )
        assert result["ok"] is False
        assert result["error"] == "unknown_device"

    _run(_check)


@pytest.mark.e2e
def test_wrong_direction_set_output_rejected() -> None:
    """set_output on an input device must return a structured wrong_direction error."""
    async def _check(session):
        result = _result_dict(
            await session.call_tool("set_output", {"device_id": "gpio24_input", "value": 1})
        )
        assert result["ok"] is False
        assert result["error"] == "wrong_direction"

    _run(_check)


@pytest.mark.e2e
def test_wrong_direction_read_input_rejected() -> None:
    """read_input on an output device must return a structured wrong_direction error."""
    async def _check(session):
        result = _result_dict(
            await session.call_tool("read_input", {"device_id": "gpio23_output"})
        )
        assert result["ok"] is False
        assert result["error"] == "wrong_direction"

    _run(_check)
