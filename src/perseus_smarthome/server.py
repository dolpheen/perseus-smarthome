"""Streamable HTTP MCP server for Raspberry Pi GPIO I/O.

Entry point: ``uv run python -m perseus_smarthome.server``

The MCP endpoint is ``http://<host>:8000/mcp`` by default.
"""

from __future__ import annotations

import signal
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from perseus_smarthome.service import GPIOService


def create_server(
    service: GPIOService,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> FastMCP:
    """Create a FastMCP server wired to *service*.

    Registering tools inside a factory function keeps the service dependency
    explicit and makes unit testing straightforward: pass a ``GPIOService``
    backed by a ``MockGPIOAdapter`` and call ``mcp.call_tool`` directly.
    """
    mcp: FastMCP = FastMCP("rpi-io-mcp", host=host, port=port)

    @mcp.tool()
    def health() -> dict[str, Any]:
        """Return service health and transport details."""
        return service.health()

    @mcp.tool()
    def list_devices() -> dict[str, Any]:
        """List configured GPIO devices with capabilities and current state."""
        return service.list_devices()

    @mcp.tool()
    def set_output(device_id: str, value: int) -> dict[str, Any]:
        """Set a configured output device to 0 (off) or 1 (on).

        Args:
            device_id: The device ID from list_devices (e.g. ``gpio23_output``).
            value: ``0`` to turn off, ``1`` to turn on.
        """
        return service.set_output(device_id, value)

    @mcp.tool()
    def read_input(device_id: str) -> dict[str, Any]:
        """Read a configured input device and return 0 or 1.

        Args:
            device_id: The device ID from list_devices (e.g. ``gpio24_input``).
        """
        return service.read_input(device_id)

    return mcp


def main() -> None:
    """Start the streamable HTTP MCP server using the real GPIO adapter."""
    # Install a SIGTERM handler so that systemd stop/restart cycles propagate
    # SystemExit through the try/finally below and service.close() drives
    # GPIO23 low before the process exits (design.md Safety Rules, FR-015).
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    from perseus_smarthome.config import load_config
    from perseus_smarthome.devices import build_registry
    from perseus_smarthome.gpio import GPIOZeroAdapter

    # Widen the try/finally to cover setup. If SIGTERM arrives during config
    # load, registry build, adapter init, or service init, service.close()
    # still runs whenever a service was constructed — so the GPIO adapter is
    # released and GPIO23 cannot be left configured without a teardown path.
    service: GPIOService | None = None
    try:
        config = load_config()
        registry = build_registry(config)
        adapter = GPIOZeroAdapter()
        service = GPIOService(registry, adapter)
        mcp = create_server(service)
        mcp.run(transport="streamable-http")
    finally:
        if service is not None:
            service.close()


if __name__ == "__main__":
    main()
