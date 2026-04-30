"""GPIO I/O service layer for Perseus Smarthome.

Validates device access and drives the GPIO adapter.  The MCP tool layer
must not call the GPIO adapter directly; all GPIO operations go through
this layer.
"""

from __future__ import annotations

from typing import Any

from perseus_smarthome.devices import DeviceRegistry, DeviceError
from perseus_smarthome.gpio import GPIOAdapter, GPIOError


class GPIOService:
    """Service layer that mediates between MCP tools and the GPIO adapter."""

    def __init__(self, registry: DeviceRegistry, adapter: GPIOAdapter) -> None:
        self._registry = registry
        self._adapter = adapter
        try:
            self._init_pins()
        except GPIOError:
            # Partial init may have configured GPIO23 as an active output.
            # Drive outputs low and release the adapter before re-raising so no
            # pin is left driven without a teardown path (design.md Safety Rules).
            try:
                self.close()
            except GPIOError:
                pass
            raise

    def _init_pins(self) -> None:
        """Configure all registered GPIO pins on startup."""
        for device in self._registry.list_devices():
            if device.kind == "output":
                self._adapter.setup_output(device.pin, safe_default=device.safe_default)
            else:
                self._adapter.setup_input(
                    device.pin,
                    pull=device.pull if device.pull is not None else "down",
                )

    def health(self) -> dict[str, Any]:
        """Return service health and runtime details."""
        return {"ok": True, "service": "rpi-io-mcp", "transport": "streamable-http"}

    def list_devices(self) -> dict[str, Any]:
        """Return all configured devices with capabilities and current state."""
        devices = []
        for device in self._registry.list_devices():
            devices.append(
                {
                    "id": device.id,
                    "name": device.name,
                    "kind": device.kind,
                    "capabilities": list(device.capabilities),
                    "state": device.state,
                }
            )
        return {"devices": devices}

    def set_output(self, device_id: str, value: int) -> dict[str, Any]:
        """Set an allowed output device to 0 or 1.

        Returns a structured result dict.  On error, includes ``ok: false``,
        ``error`` (error code), and ``message``.
        """
        if isinstance(value, bool) or value not in (0, 1):
            return {
                "ok": False,
                "error": "invalid_value",
                "message": f"Value must be 0 or 1, got {value!r}.",
            }
        try:
            device = self._registry.require_output(device_id)
        except DeviceError as exc:
            return {"ok": False, "error": exc.code, "message": exc.message}
        try:
            self._adapter.write_output(device.pin, value)
            device.state = value
        except GPIOError as exc:
            return {"ok": False, "error": exc.code, "message": exc.message}
        return {"device_id": device_id, "value": value, "ok": True}

    def read_input(self, device_id: str) -> dict[str, Any]:
        """Read an allowed input device and return 0 or 1.

        Returns a structured result dict.  On error, includes ``ok: false``,
        ``error`` (error code), and ``message``.
        """
        try:
            device = self._registry.require_input(device_id)
        except DeviceError as exc:
            return {"ok": False, "error": exc.code, "message": exc.message}
        try:
            value = self._adapter.read_input(device.pin)
            device.state = value
        except GPIOError as exc:
            return {"ok": False, "error": exc.code, "message": exc.message}
        return {"device_id": device_id, "value": value, "ok": True}

    def close(self) -> None:
        """Reset outputs to safe defaults and release all GPIO resources."""
        for device in self._registry.list_devices():
            if device.kind == "output":
                try:
                    self._adapter.write_output(device.pin, 0)
                except GPIOError:
                    pass
        self._adapter.close()
