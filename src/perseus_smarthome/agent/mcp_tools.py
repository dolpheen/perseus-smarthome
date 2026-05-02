"""Thin async wrappers around the rpi-io-mcp MCP tool contract.

These wrappers are consumed by the deepagents tool layer.  They:

- Call each MCP tool and return the structured result dict.
- Cache known device IDs from ``list_devices`` and refuse unknown
  ``device_id`` values *before* issuing an MCP call.
- Translate ``ok=False`` MCP results into :exc:`MCPToolError` with a
  plain-language message so the agent can surface them in chat.

Usage in unit tests — inject a mock callable::

    async def fake_call(name, args):
        return {"devices": [...], "rate_limit": {...}}

    tools = RpiIOMCPTools(fake_call)

Usage in production with the MCP client session::

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = RpiIOMCPTools.from_session(session)
            result = await tools.list_devices()

Spec: AGENT-FR-004, AGENT-FR-005, AGENT-FR-006, AGENT-FR-007, AGENT-FR-008.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp import ClientSession

from perseus_smarthome.agent.rate_limit import OutputRateLimiter

# Callable type alias: (tool_name, args) -> structured result dict
CallTool = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class MCPToolError(Exception):
    """Raised when an rpi-io-mcp tool returns ``ok=False`` or targets an
    unconfigured device.

    Attributes:
        code: Structured error code from the MCP contract (e.g.
            ``"unknown_device"``, ``"wrong_direction"``).
        message: Plain-language message suitable for surfacing in chat.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @classmethod
    def _from_result(cls, result: dict[str, Any]) -> "MCPToolError":
        """Build from an ``ok=False`` MCP tool result dict."""
        return cls(result.get("error", "unknown_error"), result.get("message", ""))


class RpiIOMCPTools:
    """Async wrappers around the four rpi-io-mcp MCP tools.

    Args:
        call_tool: Async callable ``(tool_name, args) -> structured_dict``
            that issues an MCP tool call and returns the structured content.
            Inject a mock for unit tests; use :meth:`from_session` in
            production.
    """

    def __init__(self, call_tool: CallTool) -> None:
        self._call_tool = call_tool
        self._known_device_ids: set[str] | None = None
        self._rate_limiter: OutputRateLimiter | None = None

    # ------------------------------------------------------------------
    # Public tool methods
    # ------------------------------------------------------------------

    async def list_devices(self) -> dict[str, Any]:
        """Wrap MCP ``list_devices``.

        Caches the returned device IDs so that subsequent :meth:`set_output`
        and :meth:`read_input` calls can validate them locally before
        reaching the MCP server (AGENT-FR-007).  Also initialises the
        per-device rate limiter from the ``rate_limit`` field.
        """
        result = await self._call_tool("list_devices", {})
        self._known_device_ids = {d["id"] for d in result.get("devices", [])}
        self._rate_limiter = OutputRateLimiter.from_list_devices_result(result)
        return result

    async def set_output(self, device_id: str, value: int) -> dict[str, Any]:
        """Wrap MCP ``set_output``.

        Refuses unknown ``device_id`` values before calling the MCP server
        (AGENT-FR-007).  Serializes calls per device through an
        :class:`~perseus_smarthome.agent.rate_limit.OutputRateLimiter` and
        enforces the minimum inter-toggle interval from ``list_devices``.
        Translates ``ok=False`` results to :exc:`MCPToolError`
        (AGENT-FR-008).
        """
        await self._require_known_device(device_id)
        # _rate_limiter is guaranteed non-None after _require_known_device
        # (list_devices always sets both _known_device_ids and _rate_limiter).
        assert self._rate_limiter is not None
        async with self._rate_limiter.guard(device_id):
            result = await self._call_tool(
                "set_output", {"device_id": device_id, "value": value}
            )
        if not result.get("ok"):
            raise MCPToolError._from_result(result)
        return result

    async def read_input(self, device_id: str) -> dict[str, Any]:
        """Wrap MCP ``read_input``.

        Refuses unknown ``device_id`` values before calling the MCP server
        (AGENT-FR-007).  Translates ``ok=False`` results to
        :exc:`MCPToolError` (AGENT-FR-008).
        """
        await self._require_known_device(device_id)
        result = await self._call_tool("read_input", {"device_id": device_id})
        if not result.get("ok"):
            raise MCPToolError._from_result(result)
        return result

    async def health(self) -> dict[str, Any]:
        """Wrap MCP ``health``."""
        return await self._call_tool("health", {})

    # ------------------------------------------------------------------
    # Production factory
    # ------------------------------------------------------------------

    @classmethod
    def from_session(cls, session: "ClientSession") -> "RpiIOMCPTools":
        """Build an :class:`RpiIOMCPTools` backed by an open MCP
        :class:`~mcp.ClientSession`.

        The session must already be initialised (``await session.initialize()``
        called by the caller before invoking any tool methods).
        """

        async def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            result = await session.call_tool(name, args)
            if result.structuredContent is not None:
                return result.structuredContent
            raise MCPToolError(
                "protocol_error",
                f"MCP server returned no structured content for tool '{name}'.",
            )

        return cls(_call)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _require_known_device(self, device_id: str) -> None:
        """Raise :exc:`MCPToolError` if *device_id* is not in the device list.

        Fetches the device list on first call (lazy init).
        """
        if self._known_device_ids is None:
            await self.list_devices()
        if device_id not in self._known_device_ids:  # type: ignore[operator]
            raise MCPToolError(
                "unknown_device",
                f"Device '{device_id}' is not configured in rpi-io-mcp.",
            )
