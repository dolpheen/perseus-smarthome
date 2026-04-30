"""Unit tests for perseus_smarthome.service.

All tests use MockGPIOAdapter and do not require Raspberry Pi hardware.
"""

from __future__ import annotations

import pytest

from perseus_smarthome.config import load_config
from perseus_smarthome.devices import build_registry
from perseus_smarthome.gpio import MockGPIOAdapter
from perseus_smarthome.service import GPIOService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> tuple[GPIOService, MockGPIOAdapter]:
    """Return a service and the underlying mock adapter for test inspection."""
    config = load_config()
    registry = build_registry(config)
    adapter = MockGPIOAdapter()
    service = GPIOService(registry, adapter)
    return service, adapter


# ---------------------------------------------------------------------------
# Startup – GPIO pin initialisation
# ---------------------------------------------------------------------------


def test_service_init_configures_output_pin() -> None:
    """GPIO23 must be set up as output with safe_default 0 on startup."""
    _, adapter = _make_service()
    assert 23 in adapter._outputs
    assert adapter._outputs[23] == 0


def test_service_init_configures_input_pin() -> None:
    """GPIO24 must be set up as input on startup."""
    _, adapter = _make_service()
    assert 24 in adapter._inputs


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def test_health_returns_ok_true() -> None:
    service, _ = _make_service()
    result = service.health()
    assert result["ok"] is True


def test_health_returns_service_name() -> None:
    service, _ = _make_service()
    result = service.health()
    assert result["service"] == "rpi-io-mcp"


def test_health_returns_streamable_http_transport() -> None:
    service, _ = _make_service()
    result = service.health()
    assert result["transport"] == "streamable-http"


# ---------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------


def test_list_devices_returns_both_configured_devices() -> None:
    service, _ = _make_service()
    result = service.list_devices()
    ids = {d["id"] for d in result["devices"]}
    assert ids == {"gpio23_output", "gpio24_input"}


def test_list_devices_output_has_set_output_capability() -> None:
    service, _ = _make_service()
    result = service.list_devices()
    output = next(d for d in result["devices"] if d["id"] == "gpio23_output")
    assert "set_output" in output["capabilities"]


def test_list_devices_input_has_read_input_capability() -> None:
    service, _ = _make_service()
    result = service.list_devices()
    input_dev = next(d for d in result["devices"] if d["id"] == "gpio24_input")
    assert "read_input" in input_dev["capabilities"]


def test_list_devices_output_state_default_zero() -> None:
    service, _ = _make_service()
    result = service.list_devices()
    output = next(d for d in result["devices"] if d["id"] == "gpio23_output")
    assert output["state"] == 0


def test_list_devices_state_updates_after_set_output() -> None:
    service, _ = _make_service()
    service.set_output("gpio23_output", 1)
    result = service.list_devices()
    output = next(d for d in result["devices"] if d["id"] == "gpio23_output")
    assert output["state"] == 1


def test_list_devices_state_updates_after_read_input() -> None:
    service, adapter = _make_service()
    adapter.set_mock_input(24, 1)
    service.read_input("gpio24_input")
    result = service.list_devices()
    input_dev = next(d for d in result["devices"] if d["id"] == "gpio24_input")
    assert input_dev["state"] == 1


# ---------------------------------------------------------------------------
# set_output – success paths
# ---------------------------------------------------------------------------


def test_set_output_to_one_returns_ok() -> None:
    service, _ = _make_service()
    result = service.set_output("gpio23_output", 1)
    assert result["ok"] is True
    assert result["device_id"] == "gpio23_output"
    assert result["value"] == 1


def test_set_output_to_zero_returns_ok() -> None:
    service, _ = _make_service()
    service.set_output("gpio23_output", 1)
    result = service.set_output("gpio23_output", 0)
    assert result["ok"] is True
    assert result["value"] == 0


def test_set_output_drives_gpio_adapter() -> None:
    service, adapter = _make_service()
    service.set_output("gpio23_output", 1)
    assert adapter._outputs[23] == 1


# ---------------------------------------------------------------------------
# set_output – error paths
# ---------------------------------------------------------------------------


def test_set_output_unknown_device_returns_error() -> None:
    service, _ = _make_service()
    result = service.set_output("nonexistent", 1)
    assert result["ok"] is False
    assert result["error"] == "unknown_device"


def test_set_output_input_device_returns_wrong_direction() -> None:
    service, _ = _make_service()
    result = service.set_output("gpio24_input", 1)
    assert result["ok"] is False
    assert result["error"] == "wrong_direction"


def test_set_output_invalid_value_returns_error() -> None:
    service, _ = _make_service()
    result = service.set_output("gpio23_output", 2)
    assert result["ok"] is False
    assert result["error"] == "invalid_value"


def test_set_output_negative_value_returns_error() -> None:
    service, _ = _make_service()
    result = service.set_output("gpio23_output", -1)
    assert result["ok"] is False
    assert result["error"] == "invalid_value"


# ---------------------------------------------------------------------------
# read_input – success paths
# ---------------------------------------------------------------------------


def test_read_input_returns_zero_by_default() -> None:
    service, _ = _make_service()
    result = service.read_input("gpio24_input")
    assert result["ok"] is True
    assert result["value"] == 0
    assert isinstance(result["value"], int)


def test_read_input_returns_one_after_mock_set() -> None:
    service, adapter = _make_service()
    adapter.set_mock_input(24, 1)
    result = service.read_input("gpio24_input")
    assert result["ok"] is True
    assert result["value"] == 1


def test_read_input_value_is_integer() -> None:
    service, _ = _make_service()
    result = service.read_input("gpio24_input")
    assert isinstance(result["value"], int)


def test_read_input_returns_device_id() -> None:
    service, _ = _make_service()
    result = service.read_input("gpio24_input")
    assert result["device_id"] == "gpio24_input"


# ---------------------------------------------------------------------------
# read_input – error paths
# ---------------------------------------------------------------------------


def test_read_input_unknown_device_returns_error() -> None:
    service, _ = _make_service()
    result = service.read_input("nonexistent")
    assert result["ok"] is False
    assert result["error"] == "unknown_device"


def test_read_input_output_device_returns_wrong_direction() -> None:
    service, _ = _make_service()
    result = service.read_input("gpio23_output")
    assert result["ok"] is False
    assert result["error"] == "wrong_direction"


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_releases_adapter() -> None:
    service, adapter = _make_service()
    service.close()
    # After close, the mock adapter no longer knows about any pins.
    assert adapter._outputs == {}
    assert adapter._inputs == {}
