"""Tests for perseus_smarthome.config."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perseus_smarthome.config import ConfigError, load_config


def test_load_config_returns_both_devices(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "output"
            pin = 23
            safe_default = 0

            [[devices]]
            id = "gpio24_input"
            name = "GPIO24 Input"
            kind = "input"
            pin = 24
            pull = "down"
        """),
        encoding="utf-8",
    )
    data = load_config(cfg)
    ids = [d["id"] for d in data["devices"]]
    assert "gpio23_output" in ids
    assert "gpio24_input" in ids


def test_load_config_reads_actual_config_file() -> None:
    """load_config() with no argument must parse the real config/rpi-io.toml."""
    data = load_config()
    ids = [d["id"] for d in data["devices"]]
    assert "gpio23_output" in ids
    assert "gpio24_input" in ids


def test_load_config_rejects_duplicate_device_ids(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "output"
            pin = 23

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output Duplicate"
            kind = "output"
            pin = 23
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Duplicate device ID"):
        load_config(cfg)


def test_load_config_rejects_unsupported_pin_numbering(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BOARD"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "output"
            pin = 23
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Unsupported pin numbering"):
        load_config(cfg)


def test_load_config_accepts_bcm_numbering(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "output"
            pin = 23
        """),
        encoding="utf-8",
    )
    data = load_config(cfg)
    assert data["gpio"]["numbering"] == "BCM"
