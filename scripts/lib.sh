#!/usr/bin/env bash
# lib.sh — shared helpers for scripts/install.sh and scripts/remote-install.sh
#
# Source this file; do not execute it directly.
#
# Provides: log, die, require_root, apt_missing

# log "step description" → prints "==> step description" to stdout.
log() {
  printf '==> %s\n' "$*"
}

# die "message" → prints "ERROR: message" to stderr and exits with code 1.
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# require_root → exits with a clear error when not running as UID 0.
require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "This script must be run as root or with sudo."
  fi
}

# apt_missing pkg [pkg ...] → echoes only the package names that are not
# currently installed according to dpkg.  Outputs nothing when all are present.
apt_missing() {
  local missing=()
  for pkg in "$@"; do
    if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
      missing+=("${pkg}")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    printf '%s\n' "${missing[@]}"
  fi
}
