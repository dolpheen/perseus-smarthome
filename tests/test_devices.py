"""Tests for perseus_smarthome.devices."""

from __future__ import annotations

import pytest

from perseus_smarthome.config import load_config, ConfigError
from perseus_smarthome.devices import Device, DeviceError, DeviceRegistry, build_registry


def _make_output(device_id: str = "gpio23_output") -> Device:
    return Device(
        id=device_id,
        name="GPIO23 Output",
        kind="output",
        pin_numbering="BCM",
        pin=23,
        capabilities=["set_output"],
        safe_default=0,
    )


def _make_input(device_id: str = "gpio24_input") -> Device:
    return Device(
        id=device_id,
        name="GPIO24 Input",
        kind="input",
        pin_numbering="BCM",
        pin=24,
        capabilities=["read_input"],
        pull="down",
    )


# ---------------------------------------------------------------------------
# Device dataclass
# ---------------------------------------------------------------------------


def test_device_output_has_correct_fields() -> None:
    d = _make_output()
    assert d.id == "gpio23_output"
    assert d.kind == "output"
    assert d.pin_numbering == "BCM"
    assert d.pin == 23
    assert d.capabilities == ["set_output"]
    assert d.safe_default == 0
    assert d.state == 0


def test_device_input_has_correct_fields() -> None:
    d = _make_input()
    assert d.id == "gpio24_input"
    assert d.kind == "input"
    assert d.pin_numbering == "BCM"
    assert d.pin == 24
    assert d.capabilities == ["read_input"]
    assert d.pull == "down"
    assert d.state == 0


# ---------------------------------------------------------------------------
# DeviceRegistry
# ---------------------------------------------------------------------------


def test_list_devices_returns_all_configured_devices() -> None:
    registry = DeviceRegistry([_make_output(), _make_input()])
    ids = {d.id for d in registry.list_devices()}
    assert ids == {"gpio23_output", "gpio24_input"}


def test_get_returns_device_for_known_id() -> None:
    registry = DeviceRegistry([_make_output()])
    device = registry.get("gpio23_output")
    assert device.id == "gpio23_output"


def test_get_raises_unknown_device_for_missing_id() -> None:
    registry = DeviceRegistry([_make_output()])
    with pytest.raises(DeviceError) as exc_info:
        registry.get("nonexistent")
    assert exc_info.value.code == "unknown_device"


def test_require_output_returns_output_device() -> None:
    registry = DeviceRegistry([_make_output()])
    device = registry.require_output("gpio23_output")
    assert device.kind == "output"


def test_require_output_raises_wrong_direction_for_input_device() -> None:
    registry = DeviceRegistry([_make_input()])
    with pytest.raises(DeviceError) as exc_info:
        registry.require_output("gpio24_input")
    assert exc_info.value.code == "wrong_direction"


def test_require_input_returns_input_device() -> None:
    registry = DeviceRegistry([_make_input()])
    device = registry.require_input("gpio24_input")
    assert device.kind == "input"


def test_require_input_raises_wrong_direction_for_output_device() -> None:
    registry = DeviceRegistry([_make_output()])
    with pytest.raises(DeviceError) as exc_info:
        registry.require_input("gpio23_output")
    assert exc_info.value.code == "wrong_direction"


def test_require_output_raises_unknown_device_for_missing_id() -> None:
    registry = DeviceRegistry([_make_output()])
    with pytest.raises(DeviceError) as exc_info:
        registry.require_output("nonexistent")
    assert exc_info.value.code == "unknown_device"


def test_require_input_raises_unknown_device_for_missing_id() -> None:
    registry = DeviceRegistry([_make_input()])
    with pytest.raises(DeviceError) as exc_info:
        registry.require_input("nonexistent")
    assert exc_info.value.code == "unknown_device"


# ---------------------------------------------------------------------------
# build_registry from real config
# ---------------------------------------------------------------------------


def test_build_registry_rejects_unknown_device_kind() -> None:
    config = {
        "gpio": {"numbering": "BCM"},
        "devices": [{"id": "mystery", "name": "Mystery", "kind": "sensor", "pin": 5}],
    }
    with pytest.raises(ConfigError, match="Unsupported device kind"):
        build_registry(config)


def test_build_registry_from_real_config() -> None:
    data = load_config()
    registry = build_registry(data)
    ids = {d.id for d in registry.list_devices()}
    assert ids == {"gpio23_output", "gpio24_input"}


def test_build_registry_output_device_has_set_output_capability() -> None:
    data = load_config()
    registry = build_registry(data)
    device = registry.get("gpio23_output")
    assert "set_output" in device.capabilities
    assert device.pin_numbering == "BCM"
    assert device.pin == 23


def test_build_registry_input_device_has_read_input_capability() -> None:
    data = load_config()
    registry = build_registry(data)
    device = registry.get("gpio24_input")
    assert "read_input" in device.capabilities
    assert device.pin_numbering == "BCM"
    assert device.pin == 24
    assert device.pull == "down"
