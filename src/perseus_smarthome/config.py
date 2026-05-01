"""Load GPIO device configuration from config/rpi-io.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def _default_config_path() -> Path:
    # Editable install: parents[2] is the repo root (and dev-tree CWDs).
    # Wheel install (e.g. .deb): parents[2] is python3.13/, so fall back to
    # the systemd unit's WorkingDirectory and finally the canonical install root.
    repo_local = Path(__file__).resolve().parents[2] / "config" / "rpi-io.toml"
    if repo_local.is_file():
        return repo_local
    cwd_local = Path.cwd() / "config" / "rpi-io.toml"
    if cwd_local.is_file():
        return cwd_local
    return Path("/opt/raspberry-smarthome/config/rpi-io.toml")


DEFAULT_CONFIG_PATH = _default_config_path()

_SUPPORTED_NUMBERING = {"BCM"}
_SUPPORTED_DEVICE_KINDS = {"output", "input"}
_REQUIRED_DEVICE_FIELDS = ("id", "name", "kind", "pin")


class ConfigError(Exception):
    """Raised when the configuration file is invalid."""


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load and validate the TOML config file.

    Returns the parsed config dict on success.
    Raises ConfigError for invalid configuration.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    _validate(data)
    return data


def _validate(data: dict[str, Any]) -> None:
    gpio = data.get("gpio", {})
    numbering = gpio.get("numbering", "BCM")
    if numbering not in _SUPPORTED_NUMBERING:
        raise ConfigError(
            f"Unsupported pin numbering '{numbering}'; only BCM is supported."
        )

    devices = data.get("devices", [])
    seen_ids: set[str] = set()
    for i, device in enumerate(devices):
        for field_name in _REQUIRED_DEVICE_FIELDS:
            if field_name not in device:
                raise ConfigError(
                    f"Device entry {i} is missing required field '{field_name}'."
                )
        if not isinstance(device["pin"], int) or isinstance(device["pin"], bool):
            device_label = device.get("id", f"entry {i}")
            raise ConfigError(
                f"Device '{device_label}' has non-integer pin value."
            )
        if device["kind"] not in _SUPPORTED_DEVICE_KINDS:
            device_label = device.get("id", f"entry {i}")
            raise ConfigError(
                f"Unsupported device kind '{device['kind']}' for device '{device_label}'; "
                f"expected one of: {sorted(_SUPPORTED_DEVICE_KINDS)}."
            )
        device_id = device["id"]
        if device_id in seen_ids:
            raise ConfigError(f"Duplicate device ID '{device_id}'.")
        seen_ids.add(device_id)
