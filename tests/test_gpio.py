"""Unit tests for the GPIO adapter boundary.

All tests use MockGPIOAdapter and do not require Raspberry Pi hardware.
"""

import pytest

from perseus_smarthome.gpio import GPIOAdapter, GPIOError, GPIOZeroAdapter, MockGPIOAdapter


# ---------------------------------------------------------------------------
# MockGPIOAdapter – interface conformance
# ---------------------------------------------------------------------------


def test_mock_adapter_is_gpio_adapter():
    assert isinstance(MockGPIOAdapter(), GPIOAdapter)


# ---------------------------------------------------------------------------
# setup_output – safe default applied on startup
# ---------------------------------------------------------------------------


def test_setup_output_applies_safe_default_zero():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23, safe_default=0)
    # Safe default 0: reading back via write path would be 0
    adapter.write_output(23, 0)  # should not raise
    assert adapter._outputs[23] == 0


def test_setup_output_applies_safe_default_one():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23, safe_default=1)
    assert adapter._outputs[23] == 1


def test_setup_output_default_safe_default_is_zero():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23)
    assert adapter._outputs[23] == 0


def test_setup_output_invalid_safe_default_raises():
    adapter = MockGPIOAdapter()
    with pytest.raises(GPIOError) as exc_info:
        adapter.setup_output(23, safe_default=2)
    assert exc_info.value.code == "invalid_value"


# ---------------------------------------------------------------------------
# write_output
# ---------------------------------------------------------------------------


def test_write_output_sets_value_to_one():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23, safe_default=0)
    adapter.write_output(23, 1)
    assert adapter._outputs[23] == 1


def test_write_output_sets_value_to_zero():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23, safe_default=1)
    adapter.write_output(23, 0)
    assert adapter._outputs[23] == 0


def test_write_output_unconfigured_pin_raises_wrong_direction():
    adapter = MockGPIOAdapter()
    with pytest.raises(GPIOError) as exc_info:
        adapter.write_output(23, 1)
    assert exc_info.value.code == "wrong_direction"


def test_write_output_to_input_pin_raises_wrong_direction():
    adapter = MockGPIOAdapter()
    adapter.setup_input(24)
    with pytest.raises(GPIOError) as exc_info:
        adapter.write_output(24, 1)
    assert exc_info.value.code == "wrong_direction"


def test_write_output_invalid_value_raises():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23)
    with pytest.raises(GPIOError) as exc_info:
        adapter.write_output(23, 2)
    assert exc_info.value.code == "invalid_value"


# ---------------------------------------------------------------------------
# setup_input and read_input
# ---------------------------------------------------------------------------


def test_setup_input_default_state_is_zero():
    adapter = MockGPIOAdapter()
    adapter.setup_input(24)
    assert adapter.read_input(24) == 0


def test_read_input_returns_int():
    adapter = MockGPIOAdapter()
    adapter.setup_input(24)
    result = adapter.read_input(24)
    assert isinstance(result, int)
    assert result in (0, 1)


def test_read_input_returns_one_after_mock_set():
    adapter = MockGPIOAdapter()
    adapter.setup_input(24)
    adapter.set_mock_input(24, 1)
    assert adapter.read_input(24) == 1


def test_read_input_returns_zero_after_mock_set():
    adapter = MockGPIOAdapter()
    adapter.setup_input(24)
    adapter.set_mock_input(24, 1)
    adapter.set_mock_input(24, 0)
    assert adapter.read_input(24) == 0


def test_read_input_unconfigured_pin_raises_wrong_direction():
    adapter = MockGPIOAdapter()
    with pytest.raises(GPIOError) as exc_info:
        adapter.read_input(24)
    assert exc_info.value.code == "wrong_direction"


def test_setup_input_invalid_pull_raises():
    adapter = MockGPIOAdapter()
    with pytest.raises(GPIOError) as exc_info:
        adapter.setup_input(24, pull="sideways")
    assert exc_info.value.code == "invalid_value"


def test_set_mock_input_unregistered_pin_raises_wrong_direction():
    adapter = MockGPIOAdapter()
    with pytest.raises(GPIOError) as exc_info:
        adapter.set_mock_input(24, 1)
    assert exc_info.value.code == "wrong_direction"


def test_read_input_from_output_pin_raises_wrong_direction():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23)
    with pytest.raises(GPIOError) as exc_info:
        adapter.read_input(23)
    assert exc_info.value.code == "wrong_direction"


# ---------------------------------------------------------------------------
# GPIO23 / GPIO24 specific startup constraints
# ---------------------------------------------------------------------------


def test_gpio23_output_starts_low_after_setup():
    """GPIO23 must be low/off after service startup (IO-MCP-FR-015)."""
    adapter = MockGPIOAdapter()
    adapter.setup_output(23, safe_default=0)
    assert adapter._outputs[23] == 0


def test_gpio24_configured_as_input_only():
    """GPIO24 must be configured only as input; writing must be rejected."""
    adapter = MockGPIOAdapter()
    adapter.setup_input(24)
    with pytest.raises(GPIOError) as exc_info:
        adapter.write_output(24, 1)
    assert exc_info.value.code == "wrong_direction"


# ---------------------------------------------------------------------------
# GPIOError attributes
# ---------------------------------------------------------------------------


def test_gpio_error_exposes_code_and_message():
    err = GPIOError("hardware_error", "something went wrong")
    assert err.code == "hardware_error"
    assert err.message == "something went wrong"
    assert str(err) == "something went wrong"


def test_gpio_error_is_exception():
    with pytest.raises(GPIOError):
        raise GPIOError("gpio_unavailable", "no hardware")


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_clears_adapter_state():
    adapter = MockGPIOAdapter()
    adapter.setup_output(23)
    adapter.setup_input(24)
    adapter.close()
    with pytest.raises(GPIOError):
        adapter.write_output(23, 0)
    with pytest.raises(GPIOError):
        adapter.read_input(24)


# ---------------------------------------------------------------------------
# GPIOZeroAdapter – importable (no hardware required)
# ---------------------------------------------------------------------------


def test_gpiozero_adapter_is_gpio_adapter():
    assert issubclass(GPIOZeroAdapter, GPIOAdapter)


def test_gpiozero_setup_output_invalid_safe_default_raises():
    adapter = GPIOZeroAdapter()
    with pytest.raises(GPIOError) as exc_info:
        adapter.setup_output(23, safe_default=5)
    assert exc_info.value.code == "invalid_value"


def test_gpiozero_setup_input_invalid_pull_raises():
    adapter = GPIOZeroAdapter()
    with pytest.raises(GPIOError) as exc_info:
        adapter.setup_input(24, pull="sideways")
    assert exc_info.value.code == "invalid_value"
