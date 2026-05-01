#!/usr/bin/env bash
# install.sh — Pi-side install/upgrade/uninstall/status for rpi-io-mcp.
#
# Usage (run on the Raspberry Pi):
#   sudo ./scripts/install.sh install [--user <name>]
#   sudo ./scripts/install.sh upgrade
#   sudo ./scripts/install.sh uninstall [--purge]
#        ./scripts/install.sh status
#
# Requirements: DEP-FR-001 through DEP-FR-011
# Design: specs/features/deployment/design.md :: Script: scripts/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/lib.sh"

# ── Constants ─────────────────────────────────────────────────────────────────

INSTALL_DIR="/opt/raspberry-smarthome"
UNIT_SRC="${INSTALL_DIR}/deploy/systemd/rpi-io-mcp.service"
UNIT_DST="/etc/systemd/system/rpi-io-mcp.service"
APT_PREREQS=(libffi-dev python3-dev build-essential swig liblgpio-dev)
SERVICE="rpi-io-mcp.service"

# ── Helpers ───────────────────────────────────────────────────────────────────

# resolve_user [--user <name>] → sets DEPLOY_USER.
# Priority: --user flag > SUDO_USER env > "pi" default.
resolve_user() {
  local flag_user=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --user) flag_user="${2:?'--user requires a name'}"; shift 2 ;;
      *) shift ;;
    esac
  done

  if [[ -n "${flag_user}" ]]; then
    DEPLOY_USER="${flag_user}"
  elif [[ -n "${SUDO_USER:-}" ]]; then
    DEPLOY_USER="${SUDO_USER}"
  else
    DEPLOY_USER="pi"
  fi

  if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
    die "Deploy user '${DEPLOY_USER}' does not exist on this host. Pass --user <name> with a valid account."
  fi
}

# read_unit_user → reads User= from the installed systemd unit.
read_unit_user() {
  local unit_user
  unit_user="$(grep -E '^User=' "${UNIT_DST}" | head -1 | cut -d= -f2 | tr -d '[:space:]')"
  if [[ -z "${unit_user}" ]]; then
    die "Cannot read User= from ${UNIT_DST}. File may be corrupt."
  fi
  echo "${unit_user}"
}

# wait_active [timeout_seconds] → waits until the service is active.
wait_active() {
  local timeout="${1:-30}"
  local elapsed=0
  while [[ "${elapsed}" -lt "${timeout}" ]]; do
    if systemctl is-active --quiet "${SERVICE}" 2>/dev/null; then
      return 0
    fi
    sleep 2
    (( elapsed += 2 )) || true
  done
  return 1
}

# ── Subcommand: install ────────────────────────────────────────────────────────

cmd_install() {
  # DEP-FR-011: root required — must be the first check so operators see a
  # clear permission error before any state is mutated.
  require_root

  # Parse args
  resolve_user "$@"

  log "Starting install (deploy user: ${DEPLOY_USER})"

  # Cross-path coexistence guard (design.md::Resolved Design Decisions::4):
  # Refuse if the deb-managed package is installed.
  local pkg_status
  pkg_status="$(dpkg-query -W -f='${Status}' perseus-smarthome 2>/dev/null || true)"
  if [[ "${pkg_status}" == "install ok installed" ]]; then
    die "perseus-smarthome is managed by apt/dpkg. Run 'sudo apt remove perseus-smarthome' first, then retry this script."
  fi

  # Step 1: Preflight — OS check (warn only)
  if [[ -f /etc/debian_version ]]; then
    local deb_ver
    deb_ver="$(cat /etc/debian_version)"
    if ! grep -qE 'trixie|13' /etc/os-release 2>/dev/null && \
       ! echo "${deb_ver}" | grep -qE '^13|trixie'; then
      log "WARNING: Host OS does not appear to be Debian Trixie (detected: ${deb_ver}). Continuing anyway."
    fi
  fi

  # Step 2: apt prereqs (DEP-FR-003)
  log "Checking apt prerequisites"
  # shellcheck disable=SC2046
  mapfile -t missing < <(apt_missing "${APT_PREREQS[@]}")
  if [[ ${#missing[@]} -gt 0 ]]; then
    log "Installing missing apt packages: ${missing[*]}"
    apt-get install -y --no-install-recommends "${missing[@]}" \
      || die "apt-get install failed. Ensure the Pi has network access and try again."
  else
    log "All apt prerequisites already installed"
  fi

  # Step 3: uv (DEP-FR-004)
  log "Checking uv for user ${DEPLOY_USER}"
  if ! sudo -u "${DEPLOY_USER}" bash -lc 'command -v uv' >/dev/null 2>&1; then
    log "Installing uv for ${DEPLOY_USER}"
    # The upstream installer is fetched over HTTPS and piped to sh.
    # No checksum is verified — this matches DEP-FR-004 and the trusted-LAN
    # posture; see specs/features/deployment/requirements.md::DEP-FR-004.
    sudo -u "${DEPLOY_USER}" bash -lc \
      'curl -LsSf https://astral.sh/uv/install.sh | sh' \
      || die "uv installation failed. Check network access or proxy settings and retry."
  else
    log "uv already installed for ${DEPLOY_USER}"
  fi

  # Step 4: gpio group membership (DEP-FR-005)
  log "Checking gpio group membership for ${DEPLOY_USER}"
  if ! id -nG "${DEPLOY_USER}" | grep -qw gpio; then
    usermod -aG gpio "${DEPLOY_USER}" \
      || die "Failed to add ${DEPLOY_USER} to gpio group."
    log "WARNING: ${DEPLOY_USER} was added to the gpio group. A reboot or re-login is required before the service can access GPIO."
  else
    log "${DEPLOY_USER} is already in the gpio group"
  fi

  # Step 5: Stage source (DEP-FR-006)
  log "Staging source to ${INSTALL_DIR}"
  mkdir -p "${INSTALL_DIR}"

  # Determine source: if we're already inside INSTALL_DIR, skip the copy.
  local canonical_install
  canonical_install="$(cd "${INSTALL_DIR}" 2>/dev/null && pwd || true)"
  local canonical_repo
  canonical_repo="$(cd "${REPO_ROOT}" && pwd)"

  if [[ "${canonical_repo}" != "${canonical_install}" ]]; then
    rsync -a --delete \
      --exclude=".git" \
      --exclude=".env" \
      --exclude=".venv" \
      --exclude="__pycache__" \
      --exclude="*.pyc" \
      --exclude=".pytest_cache" \
      "${REPO_ROOT}/" "${INSTALL_DIR}/" \
      || die "rsync failed while staging source to ${INSTALL_DIR}."
  else
    log "Source is already at ${INSTALL_DIR}, skipping rsync"
  fi

  chown -R "${DEPLOY_USER}:gpio" "${INSTALL_DIR}" \
    || die "chown failed on ${INSTALL_DIR}."

  # Step 6: uv sync
  log "Running uv sync --no-dev"
  sudo -u "${DEPLOY_USER}" bash -lc \
    "cd '${INSTALL_DIR}' && uv sync --no-dev" \
    || die "uv sync --no-dev failed. Check the log above for details."

  # Step 7: Render and install systemd unit
  log "Rendering and installing systemd unit"
  if [[ ! -f "${UNIT_SRC}" ]]; then
    die "Unit source file not found: ${UNIT_SRC}. Ensure the source was staged correctly."
  fi
  sed "s|^User=.*|User=${DEPLOY_USER}|" "${UNIT_SRC}" \
    > "${UNIT_DST}" \
    || die "Failed to write ${UNIT_DST}."

  # Step 8: Activate (DEP-FR-006)
  log "Running systemctl daemon-reload"
  systemctl daemon-reload || die "systemctl daemon-reload failed."
  log "Enabling and starting ${SERVICE}"
  systemctl enable --now "${SERVICE}" || die "systemctl enable --now ${SERVICE} failed."

  # Step 9: Verify
  log "Waiting for service to become active (up to 30 s)"
  if wait_active 30; then
    log "Service is active"
  else
    log "WARNING: Service did not become active within 30 s. Check: journalctl -u ${SERVICE}"
  fi

  cmd_status
  log "Install complete"
}

# ── Subcommand: upgrade ────────────────────────────────────────────────────────

cmd_upgrade() {
  log "Starting upgrade"

  # DEP-FR-011: root required
  require_root

  # DEP-FR-007: fail clearly if no prior install exists
  if [[ ! -d "${INSTALL_DIR}" ]]; then
    die "No existing install found at ${INSTALL_DIR}. Run 'sudo ./scripts/install.sh install' first."
  fi
  if [[ ! -f "${UNIT_DST}" ]]; then
    die "No systemd unit at ${UNIT_DST}. Run 'sudo ./scripts/install.sh install' first."
  fi

  # Read deploy user from existing unit (design.md::Behavior — upgrade)
  DEPLOY_USER="$(read_unit_user)"
  log "Deploy user from existing unit: ${DEPLOY_USER}"

  # Step 5: Stage source (same logic as install, skipped if already in place)
  log "Staging source to ${INSTALL_DIR}"
  local canonical_install
  canonical_install="$(cd "${INSTALL_DIR}" && pwd)"
  local canonical_repo
  canonical_repo="$(cd "${REPO_ROOT}" && pwd)"

  if [[ "${canonical_repo}" != "${canonical_install}" ]]; then
    rsync -a --delete \
      --exclude=".git" \
      --exclude=".env" \
      --exclude=".venv" \
      --exclude="__pycache__" \
      --exclude="*.pyc" \
      --exclude=".pytest_cache" \
      "${REPO_ROOT}/" "${INSTALL_DIR}/" \
      || die "rsync failed while staging source to ${INSTALL_DIR}."
  else
    log "Source is already at ${INSTALL_DIR}, skipping rsync"
  fi

  chown -R "${DEPLOY_USER}:gpio" "${INSTALL_DIR}" \
    || die "chown failed on ${INSTALL_DIR}."

  # Step 6: uv sync
  log "Running uv sync --no-dev"
  sudo -u "${DEPLOY_USER}" bash -lc \
    "cd '${INSTALL_DIR}' && uv sync --no-dev" \
    || die "uv sync --no-dev failed."

  # Step 7: Re-render and reinstall systemd unit
  log "Rendering and installing systemd unit"
  if [[ ! -f "${UNIT_SRC}" ]]; then
    die "Unit source file not found: ${UNIT_SRC}. The staged source may be incomplete — re-run install."
  fi
  sed "s|^User=.*|User=${DEPLOY_USER}|" "${UNIT_SRC}" \
    > "${UNIT_DST}" \
    || die "Failed to write ${UNIT_DST}."

  # Reload and restart
  log "Reloading systemd and restarting ${SERVICE}"
  systemctl daemon-reload || die "systemctl daemon-reload failed."
  systemctl restart "${SERVICE}" || die "systemctl restart ${SERVICE} failed."

  log "Waiting for service to become active (up to 30 s)"
  if wait_active 30; then
    log "Service is active"
  else
    log "WARNING: Service did not become active within 30 s. Check: journalctl -u ${SERVICE}"
  fi

  cmd_status
  log "Upgrade complete"
}

# ── Subcommand: uninstall ──────────────────────────────────────────────────────

cmd_uninstall() {
  local purge=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge) purge=1; shift ;;
      *) shift ;;
    esac
  done

  local purge_label=""
  if [[ "${purge}" -eq 1 ]]; then
    purge_label=" (--purge)"
  fi
  log "Starting uninstall${purge_label}"

  # DEP-FR-011: root required
  require_root

  # Step 1: stop (ignore "not loaded")
  log "Stopping ${SERVICE}"
  systemctl stop "${SERVICE}" 2>/dev/null || true

  # Step 2: disable (ignore "not enabled")
  log "Disabling ${SERVICE}"
  systemctl disable "${SERVICE}" 2>/dev/null || true

  # Step 3: remove unit file
  log "Removing ${UNIT_DST}"
  rm -f "${UNIT_DST}"

  # Step 4: daemon-reload
  log "Running systemctl daemon-reload"
  systemctl daemon-reload || true

  # Step 5: purge install dir
  if [[ "${purge}" -eq 1 ]]; then
    log "Removing ${INSTALL_DIR}"
    rm -rf "${INSTALL_DIR}"
  fi

  log "Uninstall complete"
}

# ── Subcommand: status ─────────────────────────────────────────────────────────

cmd_status() {
  echo "--- rpi-io-mcp status ---"

  local is_active is_enabled
  is_active="$(systemctl is-active "${SERVICE}" 2>/dev/null || echo "inactive")"
  is_enabled="$(systemctl is-enabled "${SERVICE}" 2>/dev/null || echo "disabled")"
  echo "active:  ${is_active}"
  echo "enabled: ${is_enabled}"

  # Version from pyproject.toml
  local version="(unknown)"
  if [[ -f "${INSTALL_DIR}/pyproject.toml" ]]; then
    version="$(awk -F '"' '/^version\s*=/{print $2; exit}' "${INSTALL_DIR}/pyproject.toml" || echo "(parse error)")"
  fi
  echo "version: ${version}"

  # Reachability check
  local port="8000"
  if [[ -f "${INSTALL_DIR}/config/rpi-io.toml" ]]; then
    local toml_port
    toml_port="$(awk -F'=' '/^\s*port\s*=/{gsub(/[[:space:]]/, "", $2); print $2; exit}' \
      "${INSTALL_DIR}/config/rpi-io.toml" || true)"
    if [[ -n "${toml_port}" ]]; then
      port="${toml_port}"
    fi
  fi

  local http_code
  if command -v curl >/dev/null 2>&1; then
    http_code="$(curl -sS -o /dev/null -w '%{http_code}' \
      --max-time 5 "http://localhost:${port}/mcp" 2>/dev/null || echo "000")"
    # 405/406 from MCP server is treated as reachable
    if [[ "${http_code}" =~ ^(200|201|204|405|406)$ ]]; then
      echo "reachable: yes (HTTP ${http_code}) at http://localhost:${port}/mcp"
    else
      echo "reachable: no (HTTP ${http_code}) at http://localhost:${port}/mcp"
    fi
  else
    echo "reachable: (curl not available)"
  fi

  echo "-------------------------"
}

# ── Entry point ────────────────────────────────────────────────────────────────

usage() {
  cat >&2 <<EOF
Usage:
  sudo $0 install [--user <name>]
  sudo $0 upgrade
  sudo $0 uninstall [--purge]
       $0 status

Subcommands:
  install    Idempotent install of rpi-io-mcp (apt, uv, gpio group, systemd unit).
  upgrade    Update an existing install in place and restart the service.
  uninstall  Stop/disable the service and remove the systemd unit.
             Pass --purge to also remove ${INSTALL_DIR}.
  status     Print service active/enabled state, version, and reachability.

Options for install:
  --user <name>  Deploy user (default: \$SUDO_USER, else 'pi').
EOF
  exit 1
}

SUBCOMMAND="${1:-}"
shift || true

case "${SUBCOMMAND}" in
  install)   cmd_install   "$@" ;;
  upgrade)   cmd_upgrade   "$@" ;;
  uninstall) cmd_uninstall "$@" ;;
  status)    cmd_status    "$@" ;;
  *)         usage ;;
esac
