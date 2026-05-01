#!/usr/bin/env bash
# deploy_rpi_io_mcp.sh — Install or update the rpi-io-mcp service on the Raspberry Pi.
#
# Usage:
#   ./scripts/deploy_rpi_io_mcp.sh
#
# Reads connection details from .env in the repository root (never committed).
# Required variables:
#   RPI_SSH_HOST     — hostname or IP of the Raspberry Pi
#   RPI_SSH_PORT     — SSH port (default: 22)
#   RPI_SSH_USER     — SSH user (default: pi)
#   RPI_SSH_KEY_PATH — path to SSH private key, or leave blank to use ssh-agent
#
# The remote install path is fixed at /opt/raspberry-smarthome so the
# systemd unit, deploy script, and docs all agree without any templating.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
  "sudo mkdir -p '${REMOTE_DIR}' && sudo chown -R '${RPI_SSH_USER}:gpio' '${REMOTE_DIR}'"

rsync "${RSYNC_OPTS[@]}" "${REPO_ROOT}/" "${SSH_TARGET}:${REMOTE_DIR}/"

# Re-apply ownership recursively after rsync so files copied in pick up the
# pi:gpio ownership the systemd unit expects.
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
  "sudo chown -R '${RPI_SSH_USER}:gpio' '${REMOTE_DIR}'"

echo "==> Installing/updating Python dependencies on Pi"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
  "command -v uv >/dev/null 2>&1 || { echo \"ERROR: 'uv' not found on the Raspberry Pi. Install it first: curl -LsSf https://astral.sh/uv/install.sh | sh\"; exit 1; } && cd '${REMOTE_DIR}' && uv sync --no-dev"

echo "==> Installing systemd service (rendered for User=${RPI_SSH_USER})"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "DEPLOY_USER='${RPI_SSH_USER}' bash -s" <<'EOF'
set -euo pipefail
# Render the unit with the actual deploy user. The repo's unit file uses
# `pi` as the canonical Raspbian default, but a Pi whose primary user is
# something other than `pi` (e.g. `perseus`) needs User= rewritten so
# systemd starts the service as the user that owns /opt/raspberry-smarthome.
sudo sed \
    -e "s|^User=pi$|User=${DEPLOY_USER}|" \
    /opt/raspberry-smarthome/deploy/systemd/rpi-io-mcp.service \
    | sudo tee /etc/systemd/system/rpi-io-mcp.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable rpi-io-mcp.service
sudo systemctl restart rpi-io-mcp.service
echo "Service status:"
sudo systemctl status rpi-io-mcp.service --no-pager
EOF

echo "==> Deploy complete."
echo "    MCP endpoint: http://${RPI_SSH_HOST}:8000/mcp"
