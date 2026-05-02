#!/usr/bin/env bash
# install.sh — Pi-side install/upgrade/uninstall/status for rpi-io-mcp.
#
# Usage (run on the Raspberry Pi):
#   sudo ./scripts/install.sh install [--user <name>]
#   sudo ./scripts/install.sh upgrade
#   sudo ./scripts/install.sh uninstall [--purge]
#        ./scripts/install.sh status
#
# The service always runs as User=perseus-smarthome (created at install time).
# The --user flag is accepted for backwards compatibility but is ignored.
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
SERVICE_USER="perseus-smarthome"

# ── Helpers ───────────────────────────────────────────────────────────────────

# resolve_user [--user <name>] → sets DEPLOY_USER (operator user for uv operations).
# --user is accepted for backwards compatibility but the value is ignored; the
# service always runs as SERVICE_USER (perseus-smarthome) regardless of this flag.
# Priority for uv operations: SUDO_USER env > "pi" default.
resolve_user() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --user)
        # Accepted for backwards compatibility; the value is ignored.
        # Validate that an argument is present so `set -e` gives a clear error.
        if [[ $# -lt 2 ]]; then
          die "--user requires a name argument (accepted for backwards compat, value is ignored)"
        fi
        shift 2
        ;;
      *) shift ;;
    esac
  done

  if [[ -n "${SUDO_USER:-}" ]]; then
    DEPLOY_USER="${SUDO_USER}"
  else
    DEPLOY_USER="pi"
  fi

  if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
    die "Operator user '${DEPLOY_USER}' does not exist on this host."
  fi
}

# ensure_service_user → creates SERVICE_USER system user if missing and adds to gpio.
# Mirrors packaging/debian/postinst so both install paths share the same user model.
ensure_service_user() {
  if ! getent passwd "${SERVICE_USER}" >/dev/null 2>&1; then
    log "Creating system user ${SERVICE_USER}"
    adduser --system --group --home "${INSTALL_DIR}" \
            --shell /usr/sbin/nologin --no-create-home \
            "${SERVICE_USER}" \
      || die "Failed to create ${SERVICE_USER} system user."
  else
    log "${SERVICE_USER} system user already exists"
  fi

  # Add to gpio for /dev/gpio* access; fail fast if gpio group is absent —
  # the unit declares Group=gpio and the later chown :gpio would also fail.
  if ! getent group gpio >/dev/null 2>&1; then
    die "gpio group does not exist on this host. Ensure the gpio group is present before installing."
  fi
  if ! id -nG "${SERVICE_USER}" | tr ' ' '\n' | grep -Fx gpio >/dev/null 2>&1; then
    usermod -aG gpio "${SERVICE_USER}" \
      || die "Failed to add ${SERVICE_USER} to gpio group."
    log "${SERVICE_USER} added to gpio group"
  else
    log "${SERVICE_USER} is already in the gpio group"
  fi
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

  log "Starting install (service user: ${SERVICE_USER}, operator: ${DEPLOY_USER})"

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

  # Step 4: Create service user and add to gpio (DEP-FR-005)
  # Create the install dir first so the service user's home directory exists
  # when adduser records it in /etc/passwd.
  mkdir -p "${INSTALL_DIR}"
  log "Ensuring ${SERVICE_USER} system user"
  ensure_service_user

  # Step 5: Stage source (DEP-FR-006)
  log "Staging source to ${INSTALL_DIR}"

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

  # Transfer ownership to service user after venv is built (DEP-FR-006).
  chown -R "${SERVICE_USER}:gpio" "${INSTALL_DIR}" \
    || die "chown to ${SERVICE_USER}:gpio failed on ${INSTALL_DIR}."

  # Step 7: Install systemd unit (User=perseus-smarthome is already in the file)
  log "Installing systemd unit"
  if [[ ! -f "${UNIT_SRC}" ]]; then
    die "Unit source file not found: ${UNIT_SRC}. Ensure the source was staged correctly."
  fi
  cp "${UNIT_SRC}" "${UNIT_DST}" \
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

  # Determine operator user for uv sync (same logic as install; no --user flag in upgrade).
  if [[ -n "${SUDO_USER:-}" ]]; then
    DEPLOY_USER="${SUDO_USER}"
  else
    DEPLOY_USER="pi"
  fi
  if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
    die "Operator user '${DEPLOY_USER}' does not exist on this host."
  fi
  log "Operator user: ${DEPLOY_USER}"

  # Ensure service user exists (idempotent; also handles migration from old installs).
  ensure_service_user

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

  # Transfer ownership to service user after venv is built.
  chown -R "${SERVICE_USER}:gpio" "${INSTALL_DIR}" \
    || die "chown to ${SERVICE_USER}:gpio failed on ${INSTALL_DIR}."

  # Step 7: Reinstall systemd unit (User=perseus-smarthome is already in the file)
  log "Installing systemd unit"
  if [[ ! -f "${UNIT_SRC}" ]]; then
    die "Unit source file not found: ${UNIT_SRC}. The staged source may be incomplete — re-run install."
  fi
  cp "${UNIT_SRC}" "${UNIT_DST}" \
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
  install    Idempotent install of rpi-io-mcp (apt, uv, service user, systemd unit).
  upgrade    Update an existing install in place and restart the service.
  uninstall  Stop/disable the service and remove the systemd unit.
             Pass --purge to also remove ${INSTALL_DIR}.
  status     Print service active/enabled state, version, and reachability.

Options for install:
  --user <name>  Accepted for backwards compatibility; ignored. The service
                 always runs as User=${SERVICE_USER}.
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
