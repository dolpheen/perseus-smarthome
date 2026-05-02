"""Unit tests for the agent MCP tool wrappers.

All tests inject a synchronous-safe async mock for ``call_tool`` so no
HTTP server or GPIO hardware is required.

Spec: AGENT-FR-004, AGENT-FR-005, AGENT-FR-006, AGENT-FR-007, AGENT-FR-008.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from perseus_smarthome.agent.mcp_tools import MCPToolError, RpiIOMCPTools


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DEVICES = [
    {
        "id": "gpio23_output",
        "name": "GPIO23 Output",
        "kind": "output",
        "capabilities": ["set_output"],
        "state": 0,
    },
    {
        "id": "gpio24_input",
        "name": "GPIO24 Input",
        "kind": "input",
        "capabilities": ["read_input"],
        "state": 0,
    },
]

_LIST_DEVICES_RESULT: dict[str, Any] = {
    "devices": _DEVICES,
    "rate_limit": {"output_min_interval_ms": 250},
}


def _make_tools(side_effects: dict[str, Any]) -> tuple[RpiIOMCPTools, AsyncMock]:
    """Return an RpiIOMCPTools backed by an AsyncMock.

    ``side_effects`` maps tool names to the dict the mock returns when
    called with that tool name.  A callable value is used as a
    ``side_effect`` (so it can raise exceptions).
    """
    mock = AsyncMock()

    async def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = side_effects[name]
        if callable(handler) and not isinstance(handler, dict):
            return await asyncio.coroutine(handler)(name, args) if asyncio.iscoroutinefunction(handler) else handler(name, args)  # type: ignore[arg-type]
        return handler

    tools = RpiIOMCPTools(_dispatch)
    return tools, mock


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------


def test_list_devices_returns_devices() -> None:
    tools = RpiIOMCPTools(AsyncMock(return_value=_LIST_DEVICES_RESULT))
    result = _run(tools.list_devices())
    ids = {d["id"] for d in result["devices"]}
    assert ids == {"gpio23_output", "gpio24_input"}


def test_list_devices_returns_rate_limit() -> None:
    tools = RpiIOMCPTools(AsyncMock(return_value=_LIST_DEVICES_RESULT))
    result = _run(tools.list_devices())
    assert result["rate_limit"]["output_min_interval_ms"] == 250


def test_list_devices_caches_device_ids() -> None:
    """After list_devices, known IDs are cached so set_output can validate."""
    mock_call = AsyncMock(
        side_effect=[
            _LIST_DEVICES_RESULT,
            {"device_id": "gpio23_output", "value": 1, "ok": True},
        ]
    )
    tools = RpiIOMCPTools(mock_call)
    _run(tools.list_devices())
    _run(tools.set_output("gpio23_output", 1))
    # list_devices called once; set_output called once — no second list_devices
    assert mock_call.call_count == 2


# ---------------------------------------------------------------------------
# set_output — success
# ---------------------------------------------------------------------------


def test_set_output_calls_mcp_with_correct_args() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, args))
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"device_id": "gpio23_output", "value": 1, "ok": True}

    tools = RpiIOMCPTools(recording_call)
    result = _run(tools.set_output("gpio23_output", 1))
    assert result["ok"] is True
    tool_call = next(c for c in calls if c[0] == "set_output")
    assert tool_call[1] == {"device_id": "gpio23_output", "value": 1}


def test_set_output_value_zero_passes_correctly() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, args))
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"device_id": "gpio23_output", "value": 0, "ok": True}

    tools = RpiIOMCPTools(recording_call)
    _run(tools.set_output("gpio23_output", 0))
    tool_call = next(c for c in calls if c[0] == "set_output")
    assert tool_call[1]["value"] == 0


# ---------------------------------------------------------------------------
# set_output — refuse unknown device before MCP call (AGENT-FR-007)
# ---------------------------------------------------------------------------


def test_set_output_refuses_unknown_device_before_mcp() -> None:
    mcp_calls: list[str] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        mcp_calls.append(name)
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"ok": True}

    tools = RpiIOMCPTools(recording_call)
    with pytest.raises(MCPToolError) as exc_info:
        _run(tools.set_output("nonexistent_pin", 1))
    assert exc_info.value.code == "unknown_device"
    assert "set_output" not in mcp_calls


def test_set_output_unknown_device_error_message_names_device() -> None:
    tools = RpiIOMCPTools(AsyncMock(return_value=_LIST_DEVICES_RESULT))
    with pytest.raises(MCPToolError) as exc_info:
        _run(tools.set_output("mystery_pin", 1))
    assert "mystery_pin" in exc_info.value.message


# ---------------------------------------------------------------------------
# set_output — translate MCP error codes (AGENT-FR-008)
# ---------------------------------------------------------------------------


def test_set_output_translates_wrong_direction_error() -> None:
    async def failing_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {
            "ok": False,
            "error": "wrong_direction",
            "message": "Device 'gpio24_input' is not an output device.",
        }

    tools = RpiIOMCPTools(failing_call)
    with pytest.raises(MCPToolError) as exc_info:
        _run(tools.set_output("gpio24_input", 1))
    assert exc_info.value.code == "wrong_direction"


def test_set_output_translates_invalid_value_error() -> None:
    async def failing_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {
            "ok": False,
            "error": "invalid_value",
            "message": "Value must be 0 or 1.",
        }

    tools = RpiIOMCPTools(failing_call)
    with pytest.raises(MCPToolError) as exc_info:
        _run(tools.set_output("gpio23_output", 1))
    assert exc_info.value.code == "invalid_value"
    assert exc_info.value.message == "Value must be 0 or 1."


# ---------------------------------------------------------------------------
# read_input — success
# ---------------------------------------------------------------------------


def test_read_input_calls_mcp_with_correct_args() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, args))
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"device_id": "gpio24_input", "value": 0, "ok": True}

    tools = RpiIOMCPTools(recording_call)
    result = _run(tools.read_input("gpio24_input"))
    assert result["ok"] is True
    tool_call = next(c for c in calls if c[0] == "read_input")
    assert tool_call[1] == {"device_id": "gpio24_input"}


def test_read_input_returns_integer_value() -> None:
    async def ok_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"device_id": "gpio24_input", "value": 1, "ok": True}

    tools = RpiIOMCPTools(ok_call)
    result = _run(tools.read_input("gpio24_input"))
    assert isinstance(result["value"], int)
    assert result["value"] == 1


# ---------------------------------------------------------------------------
# read_input — refuse unknown device (AGENT-FR-007)
# ---------------------------------------------------------------------------


def test_read_input_refuses_unknown_device_before_mcp() -> None:
    mcp_calls: list[str] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        mcp_calls.append(name)
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"ok": True}

    tools = RpiIOMCPTools(recording_call)
    with pytest.raises(MCPToolError) as exc_info:
        _run(tools.read_input("nonexistent"))
    assert exc_info.value.code == "unknown_device"
    assert "read_input" not in mcp_calls


# ---------------------------------------------------------------------------
# read_input — translate MCP errors (AGENT-FR-008)
# ---------------------------------------------------------------------------


def test_read_input_translates_wrong_direction_error() -> None:
    async def failing_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {
            "ok": False,
            "error": "wrong_direction",
            "message": "Device 'gpio23_output' is not an input device.",
        }

    tools = RpiIOMCPTools(failing_call)
    with pytest.raises(MCPToolError) as exc_info:
        _run(tools.read_input("gpio23_output"))
    assert exc_info.value.code == "wrong_direction"


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def test_health_returns_ok_true() -> None:
    tools = RpiIOMCPTools(
        AsyncMock(return_value={"ok": True, "service": "rpi-io-mcp", "transport": "streamable-http"})
    )
    result = _run(tools.health())
    assert result["ok"] is True
    assert result["service"] == "rpi-io-mcp"


# ---------------------------------------------------------------------------
# Lazy device-list fetch
# ---------------------------------------------------------------------------


def test_set_output_fetches_device_list_lazily() -> None:
    """_require_known_device triggers list_devices on first call."""
    calls: list[str] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append(name)
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"device_id": "gpio23_output", "value": 1, "ok": True}

    tools = RpiIOMCPTools(recording_call)
    # No explicit list_devices call — set_output fetches it lazily.
    _run(tools.set_output("gpio23_output", 1))
    assert "list_devices" in calls


def test_device_list_not_refetched_on_subsequent_calls() -> None:
    """Known IDs are cached; list_devices is not called again."""
    calls: list[str] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append(name)
        if name == "list_devices":
            return _LIST_DEVICES_RESULT
        return {"device_id": "gpio23_output", "value": 1, "ok": True}

    tools = RpiIOMCPTools(recording_call)
    _run(tools.set_output("gpio23_output", 1))
    _run(tools.set_output("gpio23_output", 0))
    assert calls.count("list_devices") == 1
