"""
Smoke tests for scripts/lib.sh helper functions.

These tests run bash in a subprocess; they do NOT require Raspberry Pi
hardware and are always included in the default pytest run.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_SH = REPO_ROOT / "scripts" / "lib.sh"
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


# ---------------------------------------------------------------------------
# Syntax checks
# ---------------------------------------------------------------------------


def test_lib_sh_syntax():
    """bash -n scripts/lib.sh must exit 0."""
    result = subprocess.run(
        ["bash", "-n", str(LIB_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_install_sh_syntax():
    """bash -n scripts/install.sh must exit 0."""
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# apt_missing helper
# ---------------------------------------------------------------------------


def _run_apt_missing(*packages: str) -> subprocess.CompletedProcess:
    """Source lib.sh and call apt_missing with the given packages."""
    pkg_args = " ".join(packages)
    script = f"""
set -euo pipefail
source "{LIB_SH}"
apt_missing {pkg_args}
"""
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="apt_missing requires dpkg (Linux only)",
)
def test_apt_missing_with_certainly_absent_package():
    """apt_missing must echo a package name that is certainly not installed."""
    fake_pkg = "this-package-does-not-exist-perseus-test"
    result = _run_apt_missing(fake_pkg)
    assert result.returncode == 0
    assert fake_pkg in result.stdout


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="apt_missing requires dpkg (Linux only)",
)
def test_apt_missing_with_installed_package():
    """apt_missing must be silent for a package that dpkg reports installed."""
    # bash is always present on the CI image that runs this test.
    result = _run_apt_missing("bash")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="apt_missing requires dpkg (Linux only)",
)
def test_apt_missing_mixed():
    """apt_missing echoes only the missing subset when given mixed input."""
    fake_pkg = "this-package-does-not-exist-perseus-test"
    result = _run_apt_missing("bash", fake_pkg)
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert fake_pkg in lines
    assert "bash" not in lines


# ---------------------------------------------------------------------------
# log helper
# ---------------------------------------------------------------------------


def test_log_output():
    """log must print '==> <message>' to stdout."""
    script = f"""
source "{LIB_SH}"
log "hello world"
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "==> hello world"


# ---------------------------------------------------------------------------
# die helper
# ---------------------------------------------------------------------------


def test_die_exits_nonzero():
    """die must exit with code 1."""
    script = f"""
source "{LIB_SH}"
die "something went wrong"
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 1


def test_die_writes_to_stderr():
    """die must write the error message to stderr."""
    script = f"""
source "{LIB_SH}"
die "fatal error occurred"
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert "fatal error occurred" in result.stderr


# ---------------------------------------------------------------------------
# require_root helper
# ---------------------------------------------------------------------------


def test_require_root_fails_as_non_root():
    """require_root must fail when not running as UID 0."""
    # In CI we are not root; this should always hit the error path.
    if subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip() == "0":
        pytest.skip("Running as root; cannot test require_root failure path")

    script = f"""
source "{LIB_SH}"
require_root
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# install.sh: no-subcommand usage
# ---------------------------------------------------------------------------


def test_install_sh_no_subcommand_exits_nonzero():
    """install.sh with no subcommand must print usage and exit non-zero."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Usage" in result.stderr or "usage" in result.stderr.lower()


def test_install_sh_unknown_subcommand_exits_nonzero():
    """install.sh with an unknown subcommand must exit non-zero."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "bogus"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
