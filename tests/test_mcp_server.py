"""Unit tests for the MCP server tools in perseus_smarthome.server.

All tests use MockGPIOAdapter and do not require Raspberry Pi hardware.
Tools are called via FastMCP.call_tool() without starting an HTTP listener.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any
from unittest.mock import MagicMock, patch

from perseus_smarthome.config import load_config
from perseus_smarthome.devices import build_registry
from perseus_smarthome.gpio import MockGPIOAdapter
from perseus_smarthome.server import create_server
from perseus_smarthome.service import GPIOService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mcp():
    """Return a FastMCP server wired to a mock-backed GPIOService."""
    config = load_config()
    registry = build_registry(config)
    adapter = MockGPIOAdapter()
    service = GPIOService(registry, adapter)
    mcp = create_server(service)
    return mcp, adapter


def _call(mcp, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Synchronously call a tool and return the structured result dict.

    FastMCP.call_tool() returns (TextContent_list, structured_dict) when the
    tool's return type annotation is dict[str, Any].  The assertion below
    guards against SDK shape changes that would silently make structured None.
    """
    _, structured = asyncio.run(mcp.call_tool(tool, args or {}))
    assert structured is not None, "FastMCP did not return a structured result; SDK shape may have changed"
    return structured


# ---------------------------------------------------------------------------
# Server creation
# ---------------------------------------------------------------------------


def test_create_server_registers_health_tool() -> None:
    mcp, _ = _make_mcp()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "health" in names


def test_create_server_registers_list_devices_tool() -> None:
    mcp, _ = _make_mcp()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "list_devices" in names


def test_create_server_registers_set_output_tool() -> None:
    mcp, _ = _make_mcp()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "set_output" in names


def test_create_server_registers_read_input_tool() -> None:
    mcp, _ = _make_mcp()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "read_input" in names


# ---------------------------------------------------------------------------
# health tool
# ---------------------------------------------------------------------------


def test_health_tool_returns_ok_true() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "health")
    assert result["ok"] is True


def test_health_tool_returns_service_name() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "health")
    assert result["service"] == "rpi-io-mcp"


def test_health_tool_returns_streamable_http_transport() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "health")
    assert result["transport"] == "streamable-http"


# ---------------------------------------------------------------------------
# list_devices tool
# ---------------------------------------------------------------------------


def test_list_devices_tool_returns_both_devices() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "list_devices")
    ids = {d["id"] for d in result["devices"]}
    assert ids == {"gpio23_output", "gpio24_input"}


def test_list_devices_tool_output_device_has_capabilities() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "list_devices")
    output = next(d for d in result["devices"] if d["id"] == "gpio23_output")
    assert "set_output" in output["capabilities"]


def test_list_devices_tool_input_device_has_capabilities() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "list_devices")
    input_dev = next(d for d in result["devices"] if d["id"] == "gpio24_input")
    assert "read_input" in input_dev["capabilities"]


def test_list_devices_tool_devices_have_state_field() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "list_devices")
    for device in result["devices"]:
        assert "state" in device


def test_list_devices_tool_returns_rate_limit_default() -> None:
    """list_devices includes rate_limit.output_min_interval_ms = 250 when unset."""
    mcp, _ = _make_mcp()
    result = _call(mcp, "list_devices")
    assert "rate_limit" in result
    assert result["rate_limit"]["output_min_interval_ms"] == 250


def test_list_devices_tool_returns_configured_rate_limit() -> None:
    """list_devices reflects a configured rate_limit value."""
    config = load_config()
    registry = build_registry(config)
    adapter = MockGPIOAdapter()
    service = GPIOService(registry, adapter, rate_limit_ms=500)
    mcp = create_server(service)
    result = _call(mcp, "list_devices")
    assert result["rate_limit"]["output_min_interval_ms"] == 500


# ---------------------------------------------------------------------------
# set_output tool – success
# ---------------------------------------------------------------------------


def test_set_output_tool_succeeds_with_value_one() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "set_output", {"device_id": "gpio23_output", "value": 1})
    assert result["ok"] is True
    assert result["device_id"] == "gpio23_output"
    assert result["value"] == 1


def test_set_output_tool_succeeds_with_value_zero() -> None:
    mcp, _ = _make_mcp()
    _call(mcp, "set_output", {"device_id": "gpio23_output", "value": 1})
    result = _call(mcp, "set_output", {"device_id": "gpio23_output", "value": 0})
    assert result["ok"] is True
    assert result["value"] == 0


def test_set_output_tool_drives_gpio() -> None:
    mcp, adapter = _make_mcp()
    _call(mcp, "set_output", {"device_id": "gpio23_output", "value": 1})
    assert adapter._outputs[23] == 1


# ---------------------------------------------------------------------------
# set_output tool – error paths
# ---------------------------------------------------------------------------


def test_set_output_tool_unknown_device_returns_error() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "set_output", {"device_id": "nonexistent", "value": 1})
    assert result["ok"] is False
    assert result["error"] == "unknown_device"


def test_set_output_tool_wrong_direction_returns_error() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "set_output", {"device_id": "gpio24_input", "value": 1})
    assert result["ok"] is False
    assert result["error"] == "wrong_direction"


def test_set_output_tool_invalid_value_returns_error() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "set_output", {"device_id": "gpio23_output", "value": 2})
    assert result["ok"] is False
    assert result["error"] == "invalid_value"


# ---------------------------------------------------------------------------
# read_input tool – success
# ---------------------------------------------------------------------------


def test_read_input_tool_returns_zero_by_default() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "read_input", {"device_id": "gpio24_input"})
    assert result["ok"] is True
    assert result["value"] == 0
    assert isinstance(result["value"], int)


def test_read_input_tool_returns_one_after_mock_set() -> None:
    mcp, adapter = _make_mcp()
    adapter.set_mock_input(24, 1)
    result = _call(mcp, "read_input", {"device_id": "gpio24_input"})
    assert result["ok"] is True
    assert result["value"] == 1


def test_read_input_tool_returns_device_id() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "read_input", {"device_id": "gpio24_input"})
    assert result["device_id"] == "gpio24_input"


def test_read_input_tool_value_is_integer() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "read_input", {"device_id": "gpio24_input"})
    assert isinstance(result["value"], int)


# ---------------------------------------------------------------------------
# read_input tool – error paths
# ---------------------------------------------------------------------------


def test_read_input_tool_unknown_device_returns_error() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "read_input", {"device_id": "nonexistent"})
    assert result["ok"] is False
    assert result["error"] == "unknown_device"


def test_read_input_tool_wrong_direction_returns_error() -> None:
    mcp, _ = _make_mcp()
    result = _call(mcp, "read_input", {"device_id": "gpio23_output"})
    assert result["ok"] is False
    assert result["error"] == "wrong_direction"


# ---------------------------------------------------------------------------
# server.main entry point
# ---------------------------------------------------------------------------


def test_main_is_callable() -> None:
    """The rpi-io-mcp console script entry point must be a callable."""
    import perseus_smarthome.server as server_module

    assert callable(server_module.main)


# ---------------------------------------------------------------------------
# server.main SIGTERM handler
# ---------------------------------------------------------------------------


def test_main_registers_sigterm_handler() -> None:
    """main() must install a SIGTERM handler before the server starts."""
    import pytest

    registered: dict[int, Any] = {}

    def _record(sig: int, handler: Any) -> None:
        registered[sig] = handler

    mock_service = MagicMock()
    mock_mcp = MagicMock()

    with (
        patch("signal.signal", side_effect=_record),
        patch("perseus_smarthome.config.load_config"),
        patch("perseus_smarthome.devices.build_registry"),
        patch("perseus_smarthome.gpio.GPIOZeroAdapter"),
        patch("perseus_smarthome.server.GPIOService", return_value=mock_service),
        patch("perseus_smarthome.server.create_server", return_value=mock_mcp),
    ):
        import perseus_smarthome.server as server_module
        server_module.main()

    assert signal.SIGTERM in registered, "SIGTERM handler was not installed by main()"
    # The registered handler must raise SystemExit(0) so the try/finally runs.
    with pytest.raises(SystemExit) as exc_info:
        registered[signal.SIGTERM](signal.SIGTERM, None)
    assert exc_info.value.code == 0


def test_main_sigterm_handler_triggers_service_close() -> None:
    """SystemExit from the SIGTERM handler must cause service.close() to run."""
    import pytest

    mock_service = MagicMock()
    mock_mcp = MagicMock()
    # Simulate mcp.run() raising SystemExit(0) as the SIGTERM handler would do.
    mock_mcp.run.side_effect = SystemExit(0)

    with (
        patch("signal.signal"),
        patch("perseus_smarthome.config.load_config"),
        patch("perseus_smarthome.devices.build_registry"),
        patch("perseus_smarthome.gpio.GPIOZeroAdapter"),
        patch("perseus_smarthome.server.GPIOService", return_value=mock_service),
        patch("perseus_smarthome.server.create_server", return_value=mock_mcp),
    ):
        import perseus_smarthome.server as server_module
        with pytest.raises(SystemExit):
            server_module.main()

    mock_service.close.assert_called_once()
