"""E2E integration tests for the agent chat service against a real rpi-io-mcp instance.

Uses a scripted mock agent that executes canned MCP tool calls against the real
rpi-io-mcp server, so no ``--run-llm`` flag (and no real LLM) is required.

All tests are ``@pytest.mark.hardware`` and are skipped by default.  Pass
``--run-hardware`` (and set ``RPI_MCP_URL``) to opt in, for example::

    RPI_MCP_URL=http://<pi>:8000/mcp uv run pytest tests/e2e/test_agent_chat.py --run-hardware

Tests 1–2 also verify actual GPIO state and therefore require the GPIO23↔GPIO24
loopback wiring documented in ``specs/features/rpi-io-mcp/design.md``.

Spec: AGENT-FR-005, AGENT-FR-006
Acceptance Criteria: Phase A — first three positive prompts.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# ---------------------------------------------------------------------------
# Optional dependency guard — chat service tests require websockets.
# ---------------------------------------------------------------------------

_WS_AVAILABLE = True
try:
    import websockets
    from websockets.asyncio.client import connect as ws_connect
    from websockets.asyncio.server import serve as ws_serve
except ImportError:
    _WS_AVAILABLE = False

_skip_without_ws = pytest.mark.skipif(
    not _WS_AVAILABLE,
    reason="requires websockets (dev dependency group)",
)

if _WS_AVAILABLE:
    from perseus_smarthome.agent.chat_service import ChatService


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------


def _get_mcp_url() -> str:
    """Return ``RPI_MCP_URL`` or skip the test."""
    url = os.environ.get("RPI_MCP_URL")
    if not url:
        pytest.skip(
            "RPI_MCP_URL is not set; "
            "run: RPI_MCP_URL=http://<pi>:8000/mcp uv run pytest tests/e2e/test_agent_chat.py --run-hardware"
        )
    return url  # type: ignore[return-value]


async def _mcp_call(mcp_url: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Issue a single MCP tool call and return the structured result dict."""
    import httpx

    try:
        async with streamablehttp_client(mcp_url, timeout=10.0) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        pytest.fail(
            f"Cannot reach rpi-io-mcp at {mcp_url!r} for tool '{tool}': {exc}"
        )
    if result.structuredContent is not None:
        return result.structuredContent
    pytest.fail(
        f"MCP tool '{tool}' returned no structured content: {result!r}"
    )


async def _reset_gpio23(mcp_url: str) -> None:
    """Set GPIO23 to 0 (safe default)."""
    await _mcp_call(mcp_url, "set_output", {"device_id": "gpio23_output", "value": 0})


# ---------------------------------------------------------------------------
# Scripted mock agent
# ---------------------------------------------------------------------------


class _ScriptedMCPAgent:
    """Mock agent that executes a scripted sequence of real MCP tool calls.

    For each ``(tool_name, args)`` pair the agent:

    1. Yields an ``on_tool_start`` event so ``ChatService`` emits a
       ``tool_call`` WebSocket frame.
    2. Issues the actual MCP call against the live ``rpi-io-mcp`` server.
    3. Yields an ``on_tool_end`` event so ``ChatService`` emits a
       ``tool_result`` frame.

    After all tool calls the agent yields one ``on_chat_model_end`` event
    whose content is ``reply_template`` with ``{value}`` substituted from
    the last MCP result (useful for ``read_input`` assertions).
    """

    def __init__(
        self,
        mcp_url: str,
        tool_sequence: list[tuple[str, dict[str, Any]]],
        *,
        reply_template: str = "Done.",
    ) -> None:
        self._mcp_url = mcp_url
        self._tool_sequence = tool_sequence
        self._reply_template = reply_template
        self._last_result: dict[str, Any] = {}

    async def astream_events(
        self, input: Any, *, version: str = "v2"
    ) -> AsyncIterator[dict[str, Any]]:
        for tool_name, args in self._tool_sequence:
            yield {
                "event": "on_tool_start",
                "name": tool_name,
                "data": {"input": args},
            }

            result_dict: dict[str, Any]
            try:
                async with streamablehttp_client(
                    self._mcp_url, timeout=10.0
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        call_result = await session.call_tool(tool_name, args)
                result_dict = (
                    call_result.structuredContent
                    if call_result.structuredContent is not None
                    else {"ok": False, "error": "no_structured_content"}
                )
            except (OSError, TimeoutError) as exc:  # pragma: no cover
                result_dict = {
                    "ok": False,
                    "error": "mcp_error",
                    "message": str(exc),
                }

            self._last_result = result_dict
            yield {
                "event": "on_tool_end",
                "name": tool_name,
                "data": {"output": result_dict},
            }

        value = self._last_result.get("value", "")
        reply = self._reply_template.format(value=value)
        yield {
            "event": "on_chat_model_end",
            "name": "scripted",
            "data": {"output": {"content": reply, "tool_calls": []}},
        }


def _scripted_factory(
    mcp_url: str,
    tool_sequence: list[tuple[str, dict[str, Any]]],
    *,
    reply_template: str = "Done.",
) -> Any:
    """Return a factory callable that produces a fresh ``_ScriptedMCPAgent``."""

    def factory() -> _ScriptedMCPAgent:
        return _ScriptedMCPAgent(mcp_url, tool_sequence, reply_template=reply_template)

    return factory


# ---------------------------------------------------------------------------
# Chat-turn helper
# ---------------------------------------------------------------------------


async def _run_chat_turn(
    agent_factory: Any,
    user_message: str,
    *,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Start a local ChatService, send one user turn, collect all frames."""
    service = ChatService(agent_factory, host="127.0.0.1", port=0)
    async with ws_serve(
        service._handle_connection,
        "127.0.0.1",
        0,
        process_request=service._process_request,
    ) as server:
        port: int = server.sockets[0].getsockname()[1]
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws:
            await ws.send(json.dumps({"type": "user_turn", "content": user_message}))
            frames = await _collect_frames(ws, timeout=timeout)
    return frames


async def _collect_frames(ws: Any, *, timeout: float) -> list[dict[str, Any]]:
    """Recv WebSocket frames until ``agent_done`` or timeout."""
    frames: list[dict[str, Any]] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            break
        frame = json.loads(raw)
        frames.append(frame)
        if frame.get("type") == "agent_done":
            break
    return frames


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.hardware
@_skip_without_ws
def test_set_output_high_turn_on_pin_23() -> None:
    """Agent chat 'turn on pin 23': set_output(gpio23_output, 1) is called
    and GPIO state matches (AGENT-FR-005, Acceptance Criteria prompt 1).

    Requires GPIO23↔GPIO24 loopback wiring to verify state via read_input.
    """
    asyncio.run(_async_test_set_output_high())


async def _async_test_set_output_high() -> None:
    mcp_url = _get_mcp_url()
    frames: list[dict[str, Any]] = []
    gpio_state: dict[str, Any] = {}
    try:
        factory = _scripted_factory(
            mcp_url,
            [("set_output", {"device_id": "gpio23_output", "value": 1})],
            reply_template="gpio23_output is now on.",
        )
        frames = await _run_chat_turn(factory, "turn on pin 23")
        # Verify GPIO state via direct MCP read before cleanup (needs loopback).
        gpio_state = await _mcp_call(
            mcp_url, "read_input", {"device_id": "gpio24_input"}
        )
    finally:
        await _reset_gpio23(mcp_url)

    # tool_call frame must name the tool with correct args.
    tool_calls = [f for f in frames if f["type"] == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "set_output"
    assert tool_calls[0]["args"] == {"device_id": "gpio23_output", "value": 1}

    # tool_result must report ok.
    tool_results = [f for f in frames if f["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["ok"] is True, f"set_output returned error: {tool_results[0]}"

    # agent_turn and agent_done must be present.
    assert any(f["type"] == "agent_turn" for f in frames)
    assert frames[-1]["type"] == "agent_done"

    # GPIO24 must read 1 (via loopback from GPIO23).
    assert gpio_state.get("value") == 1, (
        f"Expected GPIO24=1 after turning on GPIO23, got {gpio_state.get('value')}. "
        "Check GPIO23↔GPIO24 loopback wiring."
    )


@pytest.mark.e2e
@pytest.mark.hardware
@_skip_without_ws
def test_set_output_low_turn_off_pin_23() -> None:
    """Agent chat 'turn off pin 23': set_output(gpio23_output, 0) is called
    and GPIO state matches (AGENT-FR-005, Acceptance Criteria prompt 2).

    Requires GPIO23↔GPIO24 loopback wiring to verify state via read_input.
    """
    asyncio.run(_async_test_set_output_low())


async def _async_test_set_output_low() -> None:
    mcp_url = _get_mcp_url()
    frames: list[dict[str, Any]] = []
    gpio_state: dict[str, Any] = {}
    try:
        # Drive GPIO23 high first so the test exercises a real low transition.
        await _mcp_call(
            mcp_url, "set_output", {"device_id": "gpio23_output", "value": 1}
        )
        factory = _scripted_factory(
            mcp_url,
            [("set_output", {"device_id": "gpio23_output", "value": 0})],
            reply_template="gpio23_output is now off.",
        )
        frames = await _run_chat_turn(factory, "turn off pin 23")
        # Verify GPIO state before cleanup (needs loopback).
        gpio_state = await _mcp_call(
            mcp_url, "read_input", {"device_id": "gpio24_input"}
        )
    finally:
        await _reset_gpio23(mcp_url)

    tool_calls = [f for f in frames if f["type"] == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "set_output"
    assert tool_calls[0]["args"] == {"device_id": "gpio23_output", "value": 0}

    tool_results = [f for f in frames if f["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["ok"] is True, f"set_output returned error: {tool_results[0]}"

    assert any(f["type"] == "agent_turn" for f in frames)
    assert frames[-1]["type"] == "agent_done"

    # GPIO24 must read 0 (loopback from GPIO23 driven low).
    assert gpio_state.get("value") == 0, (
        f"Expected GPIO24=0 after turning off GPIO23, got {gpio_state.get('value')}. "
        "Check GPIO23↔GPIO24 loopback wiring."
    )


@pytest.mark.e2e
@pytest.mark.hardware
@_skip_without_ws
def test_read_input_what_is_on_pin_24() -> None:
    """Agent chat 'what is on pin 24': read_input(gpio24_input) is called and
    the returned value reaches the chat reply (AGENT-FR-006, Acceptance
    Criteria prompt 3).
    """
    asyncio.run(_async_test_read_input())


async def _async_test_read_input() -> None:
    mcp_url = _get_mcp_url()
    factory = _scripted_factory(
        mcp_url,
        [("read_input", {"device_id": "gpio24_input"})],
        reply_template="gpio24_input reads {value}.",
    )
    frames = await _run_chat_turn(factory, "what is on pin 24")

    # tool_call frame must name read_input with correct device_id.
    tool_calls = [f for f in frames if f["type"] == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "read_input"
    assert tool_calls[0]["args"] == {"device_id": "gpio24_input"}

    # tool_result must be ok and return a valid binary value.
    tool_results = [f for f in frames if f["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["ok"] is True, f"read_input returned error: {tool_results[0]}"
    read_value = tool_results[0].get("value")
    assert read_value in (0, 1), f"read_input value must be 0 or 1, got {read_value!r}"

    # The value read by the tool must appear verbatim in the agent_turn reply.
    agent_turns = [f for f in frames if f["type"] == "agent_turn"]
    assert agent_turns, "expected at least one agent_turn frame"
    reply = agent_turns[-1]["content"]
    assert str(read_value) in reply, (
        f"Expected value {read_value!r} to appear in agent reply {reply!r}"
    )

    assert frames[-1]["type"] == "agent_done"
