"""Unit tests for perseus_smarthome.service.

All tests use MockGPIOAdapter and do not require Raspberry Pi hardware.
"""

from __future__ import annotations

from perseus_smarthome.config import load_config
from perseus_smarthome.devices import build_registry
from perseus_smarthome.gpio import GPIOAdapter, GPIOError, MockGPIOAdapter
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


class HistoryMockAdapter(MockGPIOAdapter):
    """MockGPIOAdapter that records every write_output call."""

    def __init__(self) -> None:
        super().__init__()
        self.write_history: list[tuple[int, int]] = []

    def write_output(self, pin: int, value: int) -> None:
        super().write_output(pin, value)
        self.write_history.append((pin, value))


def _make_service_with_history() -> tuple[GPIOService, HistoryMockAdapter]:
    """Return a service backed by a HistoryMockAdapter."""
    config = load_config()
    registry = build_registry(config)
    adapter = HistoryMockAdapter()
    service = GPIOService(registry, adapter)
    return service, adapter


class PartialInitFailingAdapter(MockGPIOAdapter):
    """MockGPIOAdapter where setup_output succeeds but setup_input raises.

    Records write_output history and whether close() was invoked, so tests
    can verify the __init__ cleanup path drives outputs low and releases
    the adapter before re-raising.
    """

    def __init__(self) -> None:
        super().__init__()
        self.write_history: list[tuple[int, int]] = []
        self.close_called = False

    def setup_input(self, pin: int, pull: str = "down") -> None:
        raise GPIOError("gpio_unavailable", f"Simulated failure on input pin {pin}")

    def write_output(self, pin: int, value: int) -> None:
        super().write_output(pin, value)
        self.write_history.append((pin, value))

    def close(self) -> None:
        self.close_called = True
        super().close()


class FailingMockAdapter(GPIOAdapter):
    """Adapter that raises GPIOError on write_output and read_input calls."""

    def __init__(self, write_error_code: str, read_error_code: str) -> None:
        self._write_error_code = write_error_code
        self._read_error_code = read_error_code

    def setup_output(self, pin: int, safe_default: int = 0) -> None:
        pass

    def setup_input(self, pin: int, pull: str = "down") -> None:
        pass

    def write_output(self, pin: int, value: int) -> None:
        raise GPIOError(self._write_error_code, f"Simulated {self._write_error_code} on pin {pin}")

    def read_input(self, pin: int) -> int:
        raise GPIOError(self._read_error_code, f"Simulated {self._read_error_code} on pin {pin}")

    def close(self) -> None:
        pass


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


def test_partial_init_failure_releases_adapter_and_drives_outputs_low() -> None:
    """If _init_pins fails partway, __init__ must drive outputs low and
    release the adapter before re-raising (design.md Safety Rules)."""
    config = load_config()
    registry = build_registry(config)
    adapter = PartialInitFailingAdapter()
    try:
        GPIOService(registry, adapter)
    except GPIOError as exc:
        assert exc.code == "gpio_unavailable"
    else:
        raise AssertionError("Expected GPIOError to propagate from __init__")
    assert adapter.close_called, "Expected adapter.close() on partial init failure"
    pin23_writes = [(pin, val) for pin, val in adapter.write_history if pin == 23]
    assert pin23_writes, "Expected at least one write to pin 23 during cleanup"
    assert pin23_writes[-1] == (23, 0), (
        f"Expected final write to pin 23 to be 0, got {pin23_writes[-1]}"
    )


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


def test_set_output_bool_true_returns_error() -> None:
    service, _ = _make_service()
    result = service.set_output("gpio23_output", True)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["error"] == "invalid_value"


def test_set_output_bool_false_returns_error() -> None:
    service, _ = _make_service()
    result = service.set_output("gpio23_output", False)  # type: ignore[arg-type]
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


def test_close_resets_gpio23_low_before_releasing() -> None:
    """GPIO23 must be driven low during service shutdown (design.md Safety Rules)."""
    service, adapter = _make_service_with_history()
    service.set_output("gpio23_output", 1)
    service.close()
    # The last recorded write to pin 23 before close() must be 0.
    pin23_writes = [(pin, val) for pin, val in adapter.write_history if pin == 23]
    assert pin23_writes, "Expected at least one write to pin 23 during close()"
    assert pin23_writes[-1] == (23, 0), f"Expected final write to pin 23 to be 0, got {pin23_writes[-1]}"


# ---------------------------------------------------------------------------
# GPIO adapter failure – set_output
# ---------------------------------------------------------------------------


def _make_service_with_failing_adapter(
    write_code: str = "hardware_error",
    read_code: str = "hardware_error",
) -> GPIOService:
    config = load_config()
    registry = build_registry(config)
    adapter = FailingMockAdapter(write_code, read_code)
    return GPIOService(registry, adapter)


def test_set_output_hardware_error_returns_structured_error() -> None:
    service = _make_service_with_failing_adapter(write_code="hardware_error")
    result = service.set_output("gpio23_output", 1)
    assert result["ok"] is False
    assert result["error"] == "hardware_error"
    assert "message" in result


def test_set_output_gpio_unavailable_returns_structured_error() -> None:
    service = _make_service_with_failing_adapter(write_code="gpio_unavailable")
    result = service.set_output("gpio23_output", 1)
    assert result["ok"] is False
    assert result["error"] == "gpio_unavailable"
    assert "message" in result


# ---------------------------------------------------------------------------
# GPIO adapter failure – read_input
# ---------------------------------------------------------------------------


def test_read_input_hardware_error_returns_structured_error() -> None:
    service = _make_service_with_failing_adapter(read_code="hardware_error")
    result = service.read_input("gpio24_input")
    assert result["ok"] is False
    assert result["error"] == "hardware_error"
    assert "message" in result


def test_read_input_gpio_unavailable_returns_structured_error() -> None:
    service = _make_service_with_failing_adapter(read_code="gpio_unavailable")
    result = service.read_input("gpio24_input")
    assert result["ok"] is False
    assert result["error"] == "gpio_unavailable"
    assert "message" in result
