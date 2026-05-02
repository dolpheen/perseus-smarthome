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
# the Pi, then SSHs and runs scripts/install.sh <subcommand>. The service
# always runs as User=perseus-smarthome; no --user flag is passed.
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

trim_env_value() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "${value}"
}

read_env_value() {
  local key="$1"
  local env_path="${REPO_ROOT}/.env"
  local line value

  [[ -f "${env_path}" ]] || return 1

  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    [[ "${line}" =~ ^[[:space:]]*($|#) ]] && continue
    if [[ "${line}" =~ ^[[:space:]]*export[[:space:]]+(.+)$ ]]; then
      line="${BASH_REMATCH[1]}"
    fi
    if [[ "${line}" =~ ^[[:space:]]*${key}[[:space:]]*= ]]; then
      value="${line#*=}"
      trim_env_value "${value}"
      return 0
    fi
  done < "${env_path}"

  return 1
}

RPI_SSH_HOST="$(read_env_value RPI_SSH_HOST || true)"
RPI_SSH_PORT="$(read_env_value RPI_SSH_PORT || true)"
RPI_SSH_USER="$(read_env_value RPI_SSH_USER || true)"
RPI_SSH_KEY_PATH="$(read_env_value RPI_SSH_KEY_PATH || true)"

RPI_SSH_HOST="${RPI_SSH_HOST:-raspberrypi.local}"
RPI_SSH_PORT="${RPI_SSH_PORT:-22}"
RPI_SSH_USER="${RPI_SSH_USER:-pi}"
if [[ "${RPI_SSH_KEY_PATH}" == "~/"* ]]; then
  RPI_SSH_KEY_PATH="${HOME}/${RPI_SSH_KEY_PATH#"~/"}"
fi
REMOTE_DIR="/opt/raspberry-smarthome"

# Build SSH options
SSH_OPTS=(-p "${RPI_SSH_PORT}" -o StrictHostKeyChecking=accept-new)
if [[ -n "${RPI_SSH_KEY_PATH:-}" ]]; then
  SSH_OPTS+=(-i "${RPI_SSH_KEY_PATH}")
fi
SSH_TARGET="${RPI_SSH_USER}@${RPI_SSH_HOST}"

# Approved agent-runtime keys copied from local .env to the Pi-side
# EnvironmentFile. RPI_* and AGENT_* variables stay on the operator machine.
AGENT_ENV_KEYS=(
  OPENROUTER_API_KEY
  OPENAI_API_KEY
  ANTHROPIC_API_KEY
  LANGSMITH_TRACING_V2
  LANGSMITH_ENDPOINT
  LANGSMITH_API_KEY
  LANGSMITH_PROJECT
  LLM_API_BASE_URL
  LLM_MODEL
  LLM_API_KEY
)

collect_agent_env() {
  local key value
  for key in "${AGENT_ENV_KEYS[@]}"; do
    if value="$(read_env_value "${key}")"; then
      printf '%s=%s\n' "${key}" "${value}"
    fi
  done
}

# deploy_agent_env: filter approved agent-runtime keys from local .env and
# write the result to /etc/perseus-smarthome/agent.env on the Pi as root:root
# mode 0600. Re-runs overwrite the file deterministically.
deploy_agent_env() {
  local env_path="${REPO_ROOT}/.env"
  if [[ ! -f "${env_path}" ]]; then
    echo "==> Skipping agent.env deployment: ${env_path} not present"
    return 0
  fi

  local filtered
  filtered="$(collect_agent_env)"
  if [[ -z "${filtered}" ]]; then
    echo "==> Skipping agent.env deployment: no approved agent keys in ${env_path}"
    return 0
  fi

  echo "==> Deploying /etc/perseus-smarthome/agent.env (agent keys, 0600 root:root)"
  printf '%s\n' "${filtered}" | ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "sudo install -d -m 0755 -o root -g root /etc/perseus-smarthome && \
     sudo install -m 0600 -o root -g root /dev/null /etc/perseus-smarthome/agent.env && \
     sudo tee /etc/perseus-smarthome/agent.env >/dev/null"
}

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
  # Ensure the remote directory exists and is writable by the SSH user for rsync.
  # install.sh will chown the tree to perseus-smarthome:gpio after staging.
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "sudo mkdir -p '${REMOTE_DIR}' && sudo chown -R '${RPI_SSH_USER}:gpio' '${REMOTE_DIR}'"

  rsync "${RSYNC_OPTS[@]}" "${REPO_ROOT}/" "${SSH_TARGET}:${REMOTE_DIR}/"

  # Deploy agent env before install.sh enables/restarts rpi-io-agent.service
  # so the unit picks up provider keys on first start.
  deploy_agent_env

  echo "==> Running install.sh ${SUBCOMMAND} on Pi"
  ssh -t "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "sudo /opt/raspberry-smarthome/scripts/install.sh '${SUBCOMMAND}'"
else
  # uninstall / status — SSH only, no rsync.
  echo "==> Running install.sh ${SUBCOMMAND} on Pi"
  if [[ "${SUBCOMMAND}" == "status" ]]; then
    # status is read-only; no sudo needed.
    ssh -t "${SSH_OPTS[@]}" "${SSH_TARGET}" \
      "/opt/raspberry-smarthome/scripts/install.sh '${SUBCOMMAND}'"
  else
    REMOTE_CMD="sudo /opt/raspberry-smarthome/scripts/install.sh '${SUBCOMMAND}'"
    if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
      for _extra in "${EXTRA_ARGS[@]}"; do
        REMOTE_CMD+=" $(printf '%q' "${_extra}")"
      done
    fi
    ssh -t "${SSH_OPTS[@]}" "${SSH_TARGET}" "${REMOTE_CMD}"
  fi
fi
