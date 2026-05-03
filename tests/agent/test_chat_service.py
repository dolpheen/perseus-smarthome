"""Unit tests for the agent chat service.

Tests cover:
  - Frame shapes: ``agent_turn``, ``tool_call``, ``tool_result``, ``agent_done``.
  - Session-superseded handoff (most-recent-wins policy).
  - Degraded-mode turn (``_UnconfiguredAgent``).
  - Static HTML page served at ``/``.
  - Invalid path returns 404.

All tests use a stub agent factory so no LLM or GPIO hardware is required.
The stub implements ``astream_events()`` returning synthetic LangGraph-style
events (plain dicts) that ``_event_to_frame`` translates to WebSocket frames.

``websockets`` is in the dev dependency group so all tests in this file run
in default CI (``uv sync`` without ``--extra agent``).

Spec: AGENT-FR-001, AGENT-FR-002
Design: "WebSocket Protocol", "Multi-session policy" → session_superseded
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, AsyncIterator

import pytest

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

# Import the module under test only when websockets is present (avoids
# ImportError at collection time if [agent] extras are absent).
if _WS_AVAILABLE:
    from perseus_smarthome.agent.chat_service import ChatService, _event_to_frame
    from perseus_smarthome.agent.factory import _UnconfiguredAgent


# ---------------------------------------------------------------------------
# Stub agent / factory helpers
# ---------------------------------------------------------------------------


class _StubAgent:
    """Scripted agent that yields pre-defined synthetic LangGraph events.

    Events are plain dicts; ``_event_to_frame`` handles both LangChain
    objects and plain dicts, so no langchain imports are needed here.
    """

    def __init__(self, events_per_turn: list[list[dict[str, Any]]]) -> None:
        self._turns: list[list[dict[str, Any]]] = list(events_per_turn)
        self._index = 0

    async def astream_events(
        self, input: Any, *, version: str = "v2"
    ) -> AsyncIterator[dict[str, Any]]:
        events = self._turns[self._index] if self._index < len(self._turns) else []
        self._index += 1
        for ev in events:
            yield ev


def _stub_factory(
    events_per_turn: list[list[dict[str, Any]]],
) -> Any:
    """Return a factory callable that always produces the same _StubAgent."""

    def factory() -> _StubAgent:
        return _StubAgent(events_per_turn)

    return factory


# Convenience event builders (plain dicts, no langchain deps)
def _tool_start(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"event": "on_tool_start", "name": name, "data": {"input": args}}


def _tool_end(name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"event": "on_tool_end", "name": name, "data": {"output": result}}


def _chat_end(content: str, tool_calls: list[Any] | None = None) -> dict[str, Any]:
    return {
        "event": "on_chat_model_end",
        "name": "stub",
        "data": {"output": {"content": content, "tool_calls": tool_calls or []}},
    }


def _noop_factory() -> Any:
    """Return an agent factory callable that produces a stub emitting no events.

    Consistent with ``_stub_factory``: call ``_noop_factory()`` and pass the
    result as ``agent_factory`` to ``_running_service`` / ``ChatService``.
    """

    def _factory() -> _StubAgent:
        return _StubAgent([])

    return _factory


# ---------------------------------------------------------------------------
# Test server context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _running_service(
    agent_factory: Any, host: str = "127.0.0.1"
) -> AsyncIterator[tuple[ChatService, int]]:
    """Async context manager: start a ChatService on a random port, yield (service, port)."""
    service = ChatService(agent_factory, host=host, port=0)
    async with ws_serve(
        service._handle_connection,
        host,
        0,
        process_request=service._process_request,
    ) as server:
        port: int = server.sockets[0].getsockname()[1]
        yield service, port


# ---------------------------------------------------------------------------
# Helper: collect frames until agent_done (or connection closes)
# ---------------------------------------------------------------------------


async def _collect_turn(ws: Any, timeout: float = 5.0) -> list[dict[str, Any]]:
    """Recv frames until ``agent_done`` or connection closes."""
    frames: list[dict[str, Any]] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except (asyncio.TimeoutError, Exception):
            break
        frame = json.loads(raw)
        frames.append(frame)
        if frame.get("type") == "agent_done":
            break
    return frames


async def _wait_for_session(
    service: "ChatService", timeout: float = 2.0
) -> None:
    """Poll until *service._current_ws* is set (server accepted the connection)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if service._current_ws is not None:
            return
        await asyncio.sleep(0.001)


async def _wait_for_session_change(
    service: "ChatService", old_ws: Any, timeout: float = 2.0
) -> None:
    """Poll until *service._current_ws* changes from *old_ws*."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if service._current_ws is not old_ws:
            return
        await asyncio.sleep(0.001)


# ---------------------------------------------------------------------------
# _event_to_frame unit tests (no server needed)
# ---------------------------------------------------------------------------


@_skip_without_ws
def test_event_to_frame_tool_start() -> None:
    """on_tool_start → tool_call frame with name and args."""
    event = _tool_start("set_output", {"device_id": "gpio23_output", "value": 1})
    frame = _event_to_frame(event)
    assert frame is not None
    assert frame["type"] == "tool_call"
    assert frame["name"] == "set_output"
    assert frame["args"] == {"device_id": "gpio23_output", "value": 1}


@_skip_without_ws
def test_event_to_frame_tool_end() -> None:
    """on_tool_end → tool_result frame with ok and extra fields."""
    event = _tool_end("set_output", {"ok": True, "value": 1})
    frame = _event_to_frame(event)
    assert frame is not None
    assert frame["type"] == "tool_result"
    assert frame["name"] == "set_output"
    assert frame["ok"] is True
    assert frame["value"] == 1


@_skip_without_ws
def test_event_to_frame_tool_end_not_ok() -> None:
    """on_tool_end with ok=false surfaces correctly."""
    event = _tool_end("set_output", {"ok": False, "code": "device_not_found"})
    frame = _event_to_frame(event)
    assert frame is not None
    assert frame["ok"] is False
    assert frame["code"] == "device_not_found"


@_skip_without_ws
def test_event_to_frame_chat_model_end_text() -> None:
    """on_chat_model_end with text content → agent_turn frame."""
    event = _chat_end("Turning on the light.")
    frame = _event_to_frame(event)
    assert frame is not None
    assert frame["type"] == "agent_turn"
    assert frame["content"] == "Turning on the light."


@_skip_without_ws
def test_event_to_frame_chat_model_end_no_content() -> None:
    """on_chat_model_end with empty content → None (tool-call-only turn)."""
    event = _chat_end("")
    assert _event_to_frame(event) is None


@_skip_without_ws
def test_event_to_frame_unknown_event() -> None:
    """Unrecognised event kinds → None."""
    assert _event_to_frame({"event": "on_chain_start"}) is None
    assert _event_to_frame({}) is None


# ---------------------------------------------------------------------------
# Static page tests
# ---------------------------------------------------------------------------


@_skip_without_ws
def test_static_page_served_at_root() -> None:
    """GET / must return 200 with HTML content."""
    asyncio.run(_async_test_static_page())


async def _async_test_static_page() -> None:
    async with _running_service(_noop_factory()) as (_, port):
        # Open a raw TCP connection and send a minimal HTTP/1.1 request.
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
        )
        await writer.drain()
        data = await reader.read(65536)
        writer.close()

    response = data.decode(errors="replace")
    assert "200" in response
    assert "text/html" in response
    assert "<!DOCTYPE html>" in response or "<html" in response


@_skip_without_ws
def test_unknown_path_returns_404() -> None:
    """GET /unknown must return 404."""
    asyncio.run(_async_test_404())


async def _async_test_404() -> None:
    async with _running_service(_noop_factory()) as (_, port):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"GET /unknown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
        )
        await writer.drain()
        data = await reader.read(4096)
        writer.close()

    assert b"404" in data


# ---------------------------------------------------------------------------
# WebSocket frame-shape tests
# ---------------------------------------------------------------------------


@_skip_without_ws
def test_basic_agent_turn_frame() -> None:
    """A user_turn message must produce agent_turn + agent_done frames."""
    asyncio.run(_async_test_basic_agent_turn())


async def _async_test_basic_agent_turn() -> None:
    events = [_chat_end("Hello from the agent.")]
    async with _running_service(_stub_factory([events])) as (_, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws:
            await ws.send(json.dumps({"type": "user_turn", "content": "hi"}))
            frames = await _collect_turn(ws)

    assert any(f["type"] == "agent_turn" and f["content"] == "Hello from the agent." for f in frames)
    assert frames[-1]["type"] == "agent_done"


@_skip_without_ws
def test_tool_call_and_result_frames_in_order() -> None:
    """tool_call and tool_result frames must be emitted in order, before agent_done."""
    asyncio.run(_async_test_tool_frames())


async def _async_test_tool_frames() -> None:
    events = [
        _tool_start("set_output", {"device_id": "gpio23_output", "value": 1}),
        _tool_end("set_output", {"ok": True}),
        _chat_end("I turned on gpio23_output."),
    ]
    async with _running_service(_stub_factory([events])) as (_, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws:
            await ws.send(json.dumps({"type": "user_turn", "content": "turn on pin 23"}))
            frames = await _collect_turn(ws)

    types = [f["type"] for f in frames]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "agent_turn" in types
    assert types[-1] == "agent_done"
    # tool_call must precede tool_result
    assert types.index("tool_call") < types.index("tool_result")
    # Verify frame payloads
    call = next(f for f in frames if f["type"] == "tool_call")
    assert call["name"] == "set_output"
    assert call["args"] == {"device_id": "gpio23_output", "value": 1}
    result = next(f for f in frames if f["type"] == "tool_result")
    assert result["name"] == "set_output"
    assert result["ok"] is True


@_skip_without_ws
def test_multiple_tool_calls_in_one_turn() -> None:
    """Multiple tool calls in a single turn are all forwarded."""
    asyncio.run(_async_test_multi_tool())


async def _async_test_multi_tool() -> None:
    events = [
        _tool_start("list_devices", {}),
        _tool_end("list_devices", {"ok": True, "devices": []}),
        _tool_start("set_output", {"device_id": "gpio23_output", "value": 1}),
        _tool_end("set_output", {"ok": True}),
        _chat_end("Done."),
    ]
    async with _running_service(_stub_factory([events])) as (_, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws:
            await ws.send(json.dumps({"type": "user_turn", "content": "list then set"}))
            frames = await _collect_turn(ws)

    tool_calls = [f for f in frames if f["type"] == "tool_call"]
    tool_results = [f for f in frames if f["type"] == "tool_result"]
    assert len(tool_calls) == 2
    assert len(tool_results) == 2
    assert frames[-1]["type"] == "agent_done"


@_skip_without_ws
def test_agent_done_always_sent() -> None:
    """agent_done must be the last frame even when no events are emitted."""
    asyncio.run(_async_test_agent_done())


async def _async_test_agent_done() -> None:
    # Stub emits no events.
    async with _running_service(_stub_factory([[]])) as (_, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws:
            await ws.send(json.dumps({"type": "user_turn", "content": "hello"}))
            frames = await _collect_turn(ws)

    assert frames[-1]["type"] == "agent_done"


@_skip_without_ws
def test_unconfigured_agent_returns_error_and_done() -> None:
    """When the factory returns _UnconfiguredAgent, the turn emits error + agent_done."""
    asyncio.run(_async_test_unconfigured())


async def _async_test_unconfigured() -> None:
    def _unconfigured_factory() -> _UnconfiguredAgent:
        return _UnconfiguredAgent()

    async with _running_service(_unconfigured_factory) as (_, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws:
            await ws.send(json.dumps({"type": "user_turn", "content": "hello"}))
            frames = await _collect_turn(ws)

    assert frames[0]["type"] == "error"
    assert frames[0]["code"] == "llm_unconfigured"
    assert frames[-1]["type"] == "agent_done"


@_skip_without_ws
def test_factory_raises_emits_agent_error_frame() -> None:
    """When agent_factory raises, the connection handler emits an agent_error frame.

    Covers the bug where exceptions escaping ``_run_turn`` (or pre-turn errors
    such as the agent factory raising) were logged but never surfaced to the
    operator's browser — the WebSocket would silently dead-end.
    """
    asyncio.run(_async_test_factory_raises())


async def _async_test_factory_raises() -> None:
    def _raising_factory() -> Any:
        raise RuntimeError("boom — agent could not be constructed")

    async with _running_service(_raising_factory) as (_, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws:
            # Server will fail to construct the agent and emit an error
            # frame before closing. We only need to observe the frame; the
            # send may race the close so it is wrapped defensively.
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "user_turn", "content": "hello"}))
            frames = await _collect_turn(ws)

    error_frames = [f for f in frames if f.get("type") == "error"]
    assert error_frames, "expected an error frame surfaced to the WebSocket"
    assert error_frames[0]["code"] == "agent_error"


# ---------------------------------------------------------------------------
# Session-superseded tests
# ---------------------------------------------------------------------------


@_skip_without_ws
def test_session_superseded_prior_receives_error() -> None:
    """When ws2 connects, ws1 must receive session_superseded and be closed."""
    asyncio.run(_async_test_superseded())


async def _async_test_superseded() -> None:
    async with _running_service(_noop_factory()) as (service, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws1:
            # Poll until the server has registered ws1 as the current session.
            await _wait_for_session(service)
            old_ws = service._current_ws

            # ws2 takes the session.
            async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws2:
                # Poll until the server swaps in ws2.
                await _wait_for_session_change(service, old_ws)

                # ws1 should have received the superseded error frame.
                try:
                    raw = await asyncio.wait_for(ws1.recv(), timeout=2.0)
                    frame = json.loads(raw)
                    assert frame["type"] == "error"
                    assert frame["code"] == "session_superseded"
                except websockets.exceptions.ConnectionClosed:
                    # Connection was closed before we could recv; that is also
                    # acceptable — the superseded frame may have arrived and
                    # the connection was closed in rapid succession.
                    pass

                # ws2 should be functional: can send and receive a turn.
                await ws2.send(
                    json.dumps({"type": "user_turn", "content": "hello from ws2"})
                )
                frames = await _collect_turn(ws2)
                assert frames[-1]["type"] == "agent_done"


@_skip_without_ws
def test_new_session_after_supersede_is_active() -> None:
    """After superseding ws1, ws2 must be the active session."""
    asyncio.run(_async_test_new_session_active())


async def _async_test_new_session_active() -> None:
    # Each connection gets a fresh stub with the same scripted events so that
    # ws2's first user_turn produces an agent_turn frame.
    events = [_chat_end("I am the new session.")]

    def fresh_factory() -> _StubAgent:
        return _StubAgent([events])

    async with _running_service(fresh_factory) as (service, port):
        async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws1:
            await _wait_for_session(service)
            old_ws = service._current_ws

            async with ws_connect(f"ws://127.0.0.1:{port}/chat") as ws2:
                await _wait_for_session_change(service, old_ws)

                # Drain the superseded frame from ws1.
                try:
                    await asyncio.wait_for(ws1.recv(), timeout=1.0)
                except Exception:
                    pass

                # ws2 runs a full turn successfully.
                await ws2.send(
                    json.dumps({"type": "user_turn", "content": "are you there?"})
                )
                frames = await _collect_turn(ws2)

    agent_turns = [f for f in frames if f["type"] == "agent_turn"]
    assert agent_turns, "ws2 should receive an agent_turn frame"
    assert frames[-1]["type"] == "agent_done"
