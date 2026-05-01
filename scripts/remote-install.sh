#!/usr/bin/env bash
# remote-install.sh — Mac-side wrapper to install/manage rpi-io-mcp on the Pi.
#
# Usage:
#   ./scripts/remote-install.sh install
#   ./scripts/remote-install.sh upgrade
#   ./scripts/remote-install.sh uninstall [--purge]
#   ./scripts/remote-install.sh status
#
# Reads connection details from .env in the repository root (never committed).
# Supported variables:
#   RPI_SSH_HOST     — hostname or IP of the Raspberry Pi (default: raspberrypi.local)
#   RPI_SSH_PORT     — SSH port (default: 22)
#   RPI_SSH_USER     — SSH user (default: pi)
#   RPI_SSH_KEY_PATH — path to SSH private key, or leave blank to use ssh-agent
#
# For install/upgrade: rsyncs the working tree to /opt/raspberry-smarthome on
# the Pi, then SSHs and runs scripts/install.sh <subcommand> --user <user>.
# For uninstall/status: SSH only — no rsync needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SUBCOMMAND="${1:-}"
shift || true
EXTRA_ARGS=("$@")

if [[ -z "${SUBCOMMAND}" ]]; then
  echo "Usage: $(basename "$0") {install|upgrade|uninstall|status} [--purge]" >&2
  exit 1
fi

case "${SUBCOMMAND}" in
  install|upgrade|uninstall|status) ;;
  *)
    echo "Unknown subcommand: ${SUBCOMMAND}" >&2
    echo "Usage: $(basename "$0") {install|upgrade|uninstall|status} [--purge]" >&2
    exit 1
    ;;
esac

# Load .env if present
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -o allexport
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/.env"
  set +o allexport
fi

RPI_SSH_HOST="${RPI_SSH_HOST:-raspberrypi.local}"
RPI_SSH_PORT="${RPI_SSH_PORT:-22}"
RPI_SSH_USER="${RPI_SSH_USER:-pi}"
REMOTE_DIR="/opt/raspberry-smarthome"

# Build SSH options
SSH_OPTS=(-p "${RPI_SSH_PORT}" -o StrictHostKeyChecking=accept-new)
if [[ -n "${RPI_SSH_KEY_PATH:-}" ]]; then
  SSH_OPTS+=(-i "${RPI_SSH_KEY_PATH}")
fi
SSH_TARGET="${RPI_SSH_USER}@${RPI_SSH_HOST}"

# For install/upgrade: rsync working tree to the Pi, then invoke install.sh.
if [[ "${SUBCOMMAND}" == "install" || "${SUBCOMMAND}" == "upgrade" ]]; then
  # Build the rsync remote-shell command with properly shell-quoted SSH options
  # so paths that contain spaces (e.g. RPI_SSH_KEY_PATH) are handled correctly.
  _ssh_rsh="ssh"
  for _arg in "${SSH_OPTS[@]}"; do
    _ssh_rsh+=" $(printf '%q' "${_arg}")"
  done

  RSYNC_OPTS=(
    -az --delete
    --exclude=".git"
    --exclude=".env"
    --exclude=".venv"
    --exclude="__pycache__"
    --exclude="*.pyc"
    --exclude=".pytest_cache"
    -e "${_ssh_rsh}"
  )

  echo "==> Syncing project to ${SSH_TARGET}:${REMOTE_DIR}"
  # Ensure the remote directory exists and is owned by the deploy user
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "sudo mkdir -p '${REMOTE_DIR}' && sudo chown '${RPI_SSH_USER}:gpio' '${REMOTE_DIR}'"

  rsync "${RSYNC_OPTS[@]}" "${REPO_ROOT}/" "${SSH_TARGET}:${REMOTE_DIR}/"

  echo "==> Running install.sh ${SUBCOMMAND} on Pi"
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "sudo /opt/raspberry-smarthome/scripts/install.sh '${SUBCOMMAND}' --user '${RPI_SSH_USER}'"
else
  # uninstall / status — SSH only, no rsync.
  echo "==> Running install.sh ${SUBCOMMAND} on Pi"
  REMOTE_CMD="sudo /opt/raspberry-smarthome/scripts/install.sh '${SUBCOMMAND}'"
  if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    for _extra in "${EXTRA_ARGS[@]}"; do
      REMOTE_CMD+=" $(printf '%q' "${_extra}")"
    done
  fi
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "${REMOTE_CMD}"
fi
