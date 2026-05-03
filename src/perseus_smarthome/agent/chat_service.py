"""WebSocket chat service for the LLM agent.

Spec: AGENT-FR-001, AGENT-FR-002
Design: specs/features/llm-agent/design.md
  - "WebSocket Protocol"
  - "Static Chat Page"
  - "Multi-session policy" → most-recent-wins / session_superseded
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# LangGraph event → WebSocket frame translation
# ---------------------------------------------------------------------------


def _event_to_frame(event: dict[str, Any]) -> dict[str, Any] | None:
    """Translate a LangGraph ``astream_events`` v2 event to a WebSocket frame.

    Returns a frame dict, or ``None`` if the event should be silently ignored.

    Supported mappings:
      - ``on_tool_start``      → ``tool_call``
      - ``on_tool_end``        → ``tool_result``
      - ``on_chat_model_end``  → ``agent_turn`` (text-only messages only;
                                 tool-call-only model turns are ignored)

    Spec: Design "WebSocket Protocol"
    """
    kind = event.get("event")

    if kind == "on_tool_start":
        return {
            "type": "tool_call",
            "name": event.get("name", ""),
            # Phase A tools take only device_id (str enum) and value (int
            # 0/1), so echoing args verbatim is safe. Phase B tools that
            # accept free-form text must redact per-field before this frame
            # is sent — tracked in issue #98 (AGENT-FR-010, design.md
            # "Error Model").
            "args": event.get("data", {}).get("input", {}),
        }

    if kind == "on_tool_end":
        raw = event.get("data", {}).get("output")
        if raw is None:
            return None
        # ``output`` may be a ToolMessage (has .content str) or a plain dict.
        content = getattr(raw, "content", None)
        if content is not None:
            # ToolMessage.content is a JSON string; decode it when possible.
            if isinstance(content, str):
                try:
                    result: dict[str, Any] = json.loads(content)
                except (ValueError, TypeError):
                    result = {"content": content}
            else:
                result = content if isinstance(content, dict) else {}
        elif isinstance(raw, dict):
            result = dict(raw)  # copy: avoid mutating the original event payload
        else:
            result = {}
        # ToolNode wraps tool wrapper exceptions as ToolMessage(status="error")
        # with content=str(exc); treat that as ok=False even if the decoded
        # payload has a stray "ok" key.
        status_error = getattr(raw, "status", None) == "error"
        if isinstance(result, dict):
            ok = result.pop("ok", True)
        else:
            ok = True
        if status_error:
            ok = False
        frame: dict[str, Any] = {
            "type": "tool_result",
            "name": event.get("name", ""),
            "ok": ok,
        }
        if isinstance(result, dict):
            frame.update(result)
        return frame

    if kind == "on_chat_model_end":
        output = event.get("data", {}).get("output")
        if output is None:
            return None
        # ``output`` may be an AIMessage (has .content) or a plain dict.
        content = getattr(output, "content", None)
        if content is None and isinstance(output, dict):
            content = output.get("content")
        # Ignore tool-call-only messages (empty or absent text).
        if not content:
            return None
        return {"type": "agent_turn", "content": content}

    return None


# ---------------------------------------------------------------------------
# Chat service
# ---------------------------------------------------------------------------


class ChatService:
    """Single-session WebSocket chat service with most-recent-wins policy.

    The service owns:
      - A WebSocket endpoint at ``ws://<host>:<port>/chat``.
      - A static HTML page served at ``http://<host>:<port>/``.
      - The agent loop: ``agent_factory()`` is called once per WebSocket
        connection so each session gets a fresh agent instance.

    Most-recent-wins: when a second WebSocket connection arrives, the prior
    connection receives ``{"type": "error", "code": "session_superseded", …}``
    and is closed; the new connection takes over the session.

    Spec: AGENT-FR-001, AGENT-FR-002
    Design: "WebSocket Protocol", "Multi-session policy"
    """

    def __init__(
        self,
        agent_factory: Callable[[], Any],
        host: str = "0.0.0.0",
        port: int = 8765,
    ) -> None:
        self._agent_factory = agent_factory
        self.host = host
        self.port = port
        self._current_ws: Any = None
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # HTTP + WebSocket request routing
    # ------------------------------------------------------------------

    async def _process_request(self, connection: Any, request: Any) -> Any:
        """Handle plain-HTTP requests before the WebSocket upgrade.

        ``/``     → serve ``static/index.html``.
        ``/chat`` → return ``None`` (allow WebSocket upgrade).
        Others    → 404.
        """
        from websockets.http11 import Headers, Response  # lazy: [agent] extra

        path = request.path
        if path in ("/", ""):
            html_bytes = (_STATIC_DIR / "index.html").read_bytes()
            return Response(
                200,
                "OK",
                Headers(
                    [
                        ("Content-Type", "text/html; charset=utf-8"),
                        ("Content-Length", str(len(html_bytes))),
                    ]
                ),
                html_bytes,
            )
        if path != "/chat":
            return Response(404, "Not Found", Headers([]), b"Not found\n")
        return None  # allow WebSocket upgrade for /chat

    # ------------------------------------------------------------------
    # WebSocket connection handler
    # ------------------------------------------------------------------

    async def _handle_connection(self, ws: Any) -> None:
        """Handle one WebSocket connection lifecycle."""
        # Most-recent-wins: swap current session and notify prior.
        async with self._lock:
            prior = self._current_ws
            self._current_ws = ws

        if prior is not None:
            try:
                await prior.send(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "session_superseded",
                            "message": (
                                "A newer client connection has taken the session."
                            ),
                        }
                    )
                )
                await prior.close()
            except Exception:
                pass  # prior connection may already be gone

        try:
            agent = self._agent_factory()

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    await ws.send(
                        json.dumps(
                            {
                                "type": "error",
                                "code": "invalid_frame",
                                "message": "Expected a JSON frame.",
                            }
                        )
                    )
                    continue

                if not isinstance(msg, dict):
                    await ws.send(
                        json.dumps(
                            {
                                "type": "error",
                                "code": "invalid_frame",
                                "message": "Expected a JSON object.",
                            }
                        )
                    )
                    continue

                if msg.get("type") == "user_turn":
                    await self._run_turn(agent, msg.get("content", ""), ws)
        except Exception:
            log.exception("Unexpected error in WebSocket connection handler")
            with contextlib.suppress(Exception):
                await ws.send(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "agent_error",
                            "message": (
                                "An unexpected error occurred in the chat service. "
                                "Check journalctl -u rpi-io-agent.service for details."
                            ),
                        }
                    )
                )
        finally:
            async with self._lock:
                if self._current_ws is ws:
                    self._current_ws = None

    # ------------------------------------------------------------------
    # Agent turn runner
    # ------------------------------------------------------------------

    async def _run_turn(self, agent: Any, content: str, ws: Any) -> None:
        """Run one agent turn and stream frames to *ws*.

        Handles two agent types:
          - :class:`~perseus_smarthome.agent.factory._UnconfiguredAgent`:
            calls ``.invoke()`` and emits the resulting error frame.
          - Any agent with ``astream_events()`` (``CompiledStateGraph`` or
            test stub): streams events and translates them to WebSocket frames.

        Always appends ``{"type": "agent_done"}`` when the turn finishes.
        """
        from perseus_smarthome.agent.factory import _UnconfiguredAgent

        if isinstance(agent, _UnconfiguredAgent):
            frame = agent.invoke({"messages": [{"role": "user", "content": content}]})
            await ws.send(json.dumps(frame))
            await ws.send(json.dumps({"type": "agent_done"}))
            return

        # CompiledStateGraph or stub: use astream_events.
        try:
            from langchain_core.messages import HumanMessage  # noqa: PLC0415

            input_state: dict[str, Any] = {
                "messages": [HumanMessage(content=content)]
            }
        except ImportError:
            # Fallback for test stubs that don't need langchain.
            input_state = {"messages": [{"role": "user", "content": content}]}

        try:
            async for event in agent.astream_events(input_state, version="v2"):
                frame = _event_to_frame(event)
                if frame is not None:
                    await ws.send(json.dumps(frame))
        except Exception:
            log.exception("Error during agent streaming")
            with contextlib.suppress(Exception):
                await ws.send(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "agent_error",
                            "message": "An unexpected error occurred.",
                        }
                    )
                )
        finally:
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "agent_done"}))

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the WebSocket + HTTP server and block until cancelled."""
        from websockets.asyncio.server import serve  # lazy: [agent] extra

        async with serve(
            self._handle_connection,
            self.host,
            self.port,
            process_request=self._process_request,
        ) as server:
            log.info(
                "Agent chat service listening on ws://%s:%d/chat",
                self.host,
                self.port,
            )
            await server.serve_forever()
