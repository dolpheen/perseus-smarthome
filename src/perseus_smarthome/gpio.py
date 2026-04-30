"""GPIO adapter boundary for Perseus Smarthome.

Defines a mockable interface for GPIO output writes and input reads.
Provides a mock adapter for unit tests and a GPIO Zero adapter for
Raspberry Pi runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class GPIOError(Exception):
    """Structured GPIO access error with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class GPIOAdapter(ABC):
    """Abstract GPIO adapter interface."""

    @abstractmethod
    def setup_output(self, pin: int, safe_default: int = 0) -> None:
        """Configure a pin as digital output and apply safe_default value."""

    @abstractmethod
    def setup_input(self, pin: int, pull: str = "down") -> None:
        """Configure a pin as digital input with the given pull direction.

        pull: "up", "down", or "floating".
        """

    @abstractmethod
    def write_output(self, pin: int, value: int) -> None:
        """Write logical 0 or 1 to a configured output pin.

        Raises GPIOError with code "wrong_direction" if pin is not an output.
        Raises GPIOError with code "invalid_value" if value is not 0 or 1.
        Raises GPIOError with code "hardware_error" on hardware failure.
        """

    @abstractmethod
    def read_input(self, pin: int) -> int:
        """Read logical 0 or 1 from a configured input pin.

        Returns integer 0 or 1.
        Raises GPIOError with code "wrong_direction" if pin is not an input.
        Raises GPIOError with code "hardware_error" on hardware failure.
        """

    @abstractmethod
    def close(self) -> None:
        """Release all GPIO resources."""


class MockGPIOAdapter(GPIOAdapter):
    """In-memory GPIO adapter for unit tests.  No hardware required."""

    def __init__(self) -> None:
        self._outputs: dict[int, int] = {}  # pin -> current value
        self._inputs: dict[int, int] = {}   # pin -> current value

    def setup_output(self, pin: int, safe_default: int = 0) -> None:
        if safe_default not in (0, 1):
            raise GPIOError("invalid_value", f"safe_default must be 0 or 1, got {safe_default}")
        self._outputs[pin] = safe_default

    def setup_input(self, pin: int, pull: str = "down") -> None:
        self._inputs[pin] = 0

    def write_output(self, pin: int, value: int) -> None:
        if pin not in self._outputs:
            raise GPIOError("wrong_direction", f"Pin {pin} is not configured as output")
        if value not in (0, 1):
            raise GPIOError("invalid_value", f"Value must be 0 or 1, got {value}")
        self._outputs[pin] = value

    def read_input(self, pin: int) -> int:
        if pin not in self._inputs:
            raise GPIOError("wrong_direction", f"Pin {pin} is not configured as input")
        return self._inputs[pin]

    def set_mock_input(self, pin: int, value: int) -> None:
        """Test helper: set the state returned by read_input for a configured input pin."""
        self._inputs[pin] = value

    def close(self) -> None:
        self._outputs.clear()
        self._inputs.clear()


class GPIOZeroAdapter(GPIOAdapter):
    """GPIO Zero adapter for Raspberry Pi runtime.

    Imports gpiozero lazily so the module can be loaded on non-Pi platforms
    without raising ImportError.  Call setup_output / setup_input before any
    reads or writes.
    """

    def __init__(self) -> None:
        self._outputs: dict[int, object] = {}
        self._inputs: dict[int, object] = {}

    def setup_output(self, pin: int, safe_default: int = 0) -> None:
        if safe_default not in (0, 1):
            raise GPIOError("invalid_value", f"safe_default must be 0 or 1, got {safe_default}")
        try:
            from gpiozero import DigitalOutputDevice  # type: ignore[import-untyped]

            device = DigitalOutputDevice(pin, initial_value=bool(safe_default))
            self._outputs[pin] = device
        except GPIOError:
            raise
        except Exception as exc:
            raise GPIOError(
                "gpio_unavailable",
                f"Failed to configure output on pin {pin}: {exc}",
            ) from exc

    def setup_input(self, pin: int, pull: str = "down") -> None:
        if pull not in ("up", "down", "floating"):
            raise GPIOError("invalid_value", f"pull must be 'up', 'down', or 'floating', got {pull!r}")
        try:
            from gpiozero import DigitalInputDevice  # type: ignore[import-untyped]

            pull_up: bool | None
            if pull == "up":
                pull_up = True
            elif pull == "down":
                pull_up = False
            else:
                pull_up = None

            device = DigitalInputDevice(pin, pull_up=pull_up)
            self._inputs[pin] = device
        except GPIOError:
            raise
        except Exception as exc:
            raise GPIOError(
                "gpio_unavailable",
                f"Failed to configure input on pin {pin}: {exc}",
            ) from exc

    def write_output(self, pin: int, value: int) -> None:
        if pin not in self._outputs:
            raise GPIOError("wrong_direction", f"Pin {pin} is not configured as output")
        if value not in (0, 1):
            raise GPIOError("invalid_value", f"Value must be 0 or 1, got {value}")
        try:
            device = self._outputs[pin]
            if value:
                device.on()  # type: ignore[attr-defined]
            else:
                device.off()  # type: ignore[attr-defined]
        except GPIOError:
            raise
        except Exception as exc:
            raise GPIOError("hardware_error", f"Failed to write pin {pin}: {exc}") from exc

    def read_input(self, pin: int) -> int:
        if pin not in self._inputs:
            raise GPIOError("wrong_direction", f"Pin {pin} is not configured as input")
        try:
            device = self._inputs[pin]
            return int(device.value)  # type: ignore[attr-defined]
        except GPIOError:
            raise
        except Exception as exc:
            raise GPIOError("hardware_error", f"Failed to read pin {pin}: {exc}") from exc

    def close(self) -> None:
        for device in self._outputs.values():
            try:
                device.off()  # type: ignore[attr-defined]
                device.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        for device in self._inputs.values():
            try:
                device.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._outputs.clear()
        self._inputs.clear()
