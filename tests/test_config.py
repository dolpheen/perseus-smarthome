"""Tests for perseus_smarthome.config."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from perseus_smarthome import config as config_module
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


def test_load_config_rejects_device_missing_id(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            name = "GPIO23 Output"
            kind = "output"
            pin = 23
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing required field 'id'"):
        load_config(cfg)


def test_load_config_rejects_device_missing_name(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            kind = "output"
            pin = 23
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing required field 'name'"):
        load_config(cfg)


def test_load_config_rejects_device_missing_kind(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            pin = 23
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing required field 'kind'"):
        load_config(cfg)


def test_load_config_rejects_device_missing_pin(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "output"
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing required field 'pin'"):
        load_config(cfg)


def test_load_config_rejects_device_non_integer_pin(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "output"
            pin = "23"
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="non-integer pin"):
        load_config(cfg)


def test_load_config_rejects_device_boolean_pin(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "output"
            pin = true
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="non-integer pin"):
        load_config(cfg)


def _write_minimal_config(path: Path) -> None:
    path.write_text(
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


def test_default_config_path_prefers_repo_relative_when_available(tmp_path: Path) -> None:
    """Editable install layout: parents[2]/config/rpi-io.toml exists -> wins."""
    fake_module_file = tmp_path / "src" / "perseus_smarthome" / "config.py"
    fake_module_file.parent.mkdir(parents=True)
    fake_module_file.touch()
    repo_config = tmp_path / "config" / "rpi-io.toml"
    repo_config.parent.mkdir()
    _write_minimal_config(repo_config)
    with patch.object(config_module, "__file__", str(fake_module_file)):
        assert config_module._default_config_path() == repo_config


def test_default_config_path_falls_back_to_cwd_for_wheel_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wheel install layout: parents[2] is python3.13/, no repo config -> CWD branch."""
    wheel_module_file = (
        tmp_path / "venv" / "lib" / "python3.13" / "site-packages" /
        "perseus_smarthome" / "config.py"
    )
    wheel_module_file.parent.mkdir(parents=True)
    wheel_module_file.touch()
    cwd_root = tmp_path / "service-cwd"
    cwd_config = cwd_root / "config" / "rpi-io.toml"
    cwd_config.parent.mkdir(parents=True)
    _write_minimal_config(cwd_config)
    monkeypatch.chdir(cwd_root)
    with patch.object(config_module, "__file__", str(wheel_module_file)):
        assert config_module._default_config_path() == cwd_config


def test_default_config_path_falls_back_to_canonical_install_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No repo-local, no CWD-local -> canonical /opt/raspberry-smarthome path."""
    wheel_module_file = (
        tmp_path / "venv" / "lib" / "python3.13" / "site-packages" /
        "perseus_smarthome" / "config.py"
    )
    wheel_module_file.parent.mkdir(parents=True)
    wheel_module_file.touch()
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    with patch.object(config_module, "__file__", str(wheel_module_file)):
        assert config_module._default_config_path() == Path(
            "/opt/raspberry-smarthome/config/rpi-io.toml"
        )


def test_load_config_rejects_device_unsupported_kind(tmp_path: Path) -> None:
    cfg = tmp_path / "rpi-io.toml"
    cfg.write_text(
        textwrap.dedent("""\
            [gpio]
            numbering = "BCM"

            [[devices]]
            id = "gpio23_output"
            name = "GPIO23 Output"
            kind = "sensor"
            pin = 23
        """),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Unsupported device kind"):
        load_config(cfg)
