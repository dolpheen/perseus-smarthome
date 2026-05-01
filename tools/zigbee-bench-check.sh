#!/usr/bin/env bash

set -uo pipefail

expected_usb_id="0451:16a8"

print_kv() {
  printf '%-18s %s\n' "$1:" "$2"
}

print_section() {
  printf '\n## %s\n' "$1"
}

run_lsusb_probe() {
  local output

  if ! command -v lsusb >/dev/null 2>&1; then
    printf '(lsusb not found; install usbutils to inspect USB devices)\n'
    return
  fi

  output="$(lsusb)"

  if ! printf '%s\n' "$output" | grep -Ei "(${expected_usb_id}|Texas Instruments|CC2531)"; then
    printf '(no TI / CC2531 USB device found; expected USB ID %s)\n' "$expected_usb_id"
  fi

  if printf '%s\n' "$output" | grep -Fqi "$expected_usb_id"; then
    printf '(expected USB ID %s present)\n' "$expected_usb_id"
  else
    printf '(expected USB ID %s not found)\n' "$expected_usb_id"
  fi
}

run_tty_acm_probe() {
  local devices=()
  local device

  shopt -s nullglob
  devices=(/dev/ttyACM*)
  shopt -u nullglob

  if ((${#devices[@]} == 0)); then
    printf '(no /dev/ttyACM* devices found)\n'
    return
  fi

  ls -l "${devices[@]}"
  for device in "${devices[@]}"; do
    printf '%s -> %s\n' "$device" "$(readlink -f "$device" 2>/dev/null || printf 'unresolved')"
  done
}

read_dmesg() {
  local output

  if output="$(dmesg 2>&1)"; then
    printf '%s\n' "$output"
    return 0
  fi

  printf '(dmesg failed: %s)\n' "$output"

  if command -v sudo >/dev/null 2>&1; then
    if output="$(sudo -n dmesg 2>&1)"; then
      printf '%s\n' "$output"
      return 0
    fi
    printf '(sudo -n dmesg failed: %s)\n' "$output"
  fi

  return 1
}

run_dmesg_probe() {
  local output

  if ! output="$(read_dmesg)"; then
    printf '%s\n' "$output"
    return
  fi

  if ! printf '%s\n' "$output" | grep -Ei '(cdc_acm|cdc-acm|ttyACM|CDC ACM)' | tail -n 50; then
    printf '(no CDC ACM / ttyACM lines found in dmesg)\n'
  fi
}

printf '```text\n'
printf '# Zigbee / CC2531 bench check\n'
print_kv "timestamp_utc" "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf 'unknown')"
print_kv "host" "$(hostname 2>/dev/null || printf 'unknown')"
print_kv "kernel" "$(uname -a 2>/dev/null || printf 'unknown')"
print_kv "expected_usb_id" "$expected_usb_id"

print_section "lsusb filtered for TI / CC2531"
run_lsusb_probe

print_section "/dev/ttyACM* devices"
run_tty_acm_probe

print_section "dmesg CDC ACM enumeration (last 50 matching lines)"
run_dmesg_probe
printf '```\n'
