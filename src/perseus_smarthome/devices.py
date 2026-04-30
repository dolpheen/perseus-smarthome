"""Device model and registry for GPIO I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DeviceKind = Literal["output", "input"]

_CAPABILITIES: dict[str, list[str]] = {
    "output": ["set_output"],
    "input": ["read_input"],
}


class DeviceError(Exception):
    """Raised for device registry violations."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Device:
    """A configured logical GPIO device."""

    id: str
    name: str
    kind: DeviceKind
    pin_numbering: str
    pin: int
    capabilities: list[str] = field(default_factory=list)
    safe_default: int = 0
    pull: str | None = None
    state: int = 0


class DeviceRegistry:
    """Registry of configured logical GPIO devices."""

    def __init__(self, devices: list[Device]) -> None:
        self._devices: dict[str, Device] = {d.id: d for d in devices}

    def list_devices(self) -> list[Device]:
        """Return all configured devices."""
        return list(self._devices.values())

    def get(self, device_id: str) -> Device:
        """Return a device by ID or raise DeviceError('unknown_device')."""
        if device_id not in self._devices:
            raise DeviceError("unknown_device", f"Unknown device '{device_id}'.")
        return self._devices[device_id]

    def require_output(self, device_id: str) -> Device:
        """Return device only if it is an output; raise DeviceError('wrong_direction') otherwise."""
        device = self.get(device_id)
        if device.kind != "output":
            raise DeviceError(
                "wrong_direction",
                f"Device '{device_id}' is not an output device.",
            )
        return device

    def require_input(self, device_id: str) -> Device:
        """Return device only if it is an input; raise DeviceError('wrong_direction') otherwise."""
        device = self.get(device_id)
        if device.kind != "input":
            raise DeviceError(
                "wrong_direction",
                f"Device '{device_id}' is not an input device.",
            )
        return device


_SUPPORTED_KINDS = set(_CAPABILITIES)


def build_registry(config: dict[str, Any]) -> DeviceRegistry:
    """Build a DeviceRegistry from a loaded config dict."""
    pin_numbering = config.get("gpio", {}).get("numbering", "BCM")
    raw_devices = config.get("devices", [])
    devices = []
    for raw in raw_devices:
        kind = raw["kind"]
        if kind not in _SUPPORTED_KINDS:
            raise ValueError(
                f"Unsupported device kind '{kind}' for device '{raw.get('id')}'; "
                f"expected one of: {sorted(_SUPPORTED_KINDS)}."
            )
        devices.append(
            Device(
                id=raw["id"],
                name=raw["name"],
                kind=kind,
                pin_numbering=pin_numbering,
                pin=raw["pin"],
                capabilities=list(_CAPABILITIES[kind]),
                safe_default=raw.get("safe_default", 0),
                pull=raw.get("pull"),
            )
        )
    return DeviceRegistry(devices)
