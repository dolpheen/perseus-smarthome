# Raspberry Pi I/O MCP Server Design

Status: Approved
Last reviewed: 2026-04-30  
Owner: Vadim  
Requirements: requirements.md

## Summary

Implement a Python MCP server that runs on Raspberry Pi 2, exposes a small GPIO I/O tool contract over streamable HTTP, and starts automatically through systemd. The first milestone is intentionally narrow: configured GPIO output control, configured GPIO input reading, and deterministic E2E verification from a MacBook.

## Runtime

- Target board: Raspberry Pi 2.
- Target OS: Raspberry Pi OS Lite 32-bit based on Debian Trixie.
- Python: 3.13 from Debian Trixie.
- Package manager: `uv`.
- Dependency lock file: `uv.lock`.
- Test runner: pytest.
- MCP SDK: official Python SDK, v1.x/stable line.
- GPIO access: GPIO Zero behind an internal adapter interface.
- Service manager: systemd.
- MCP transport: streamable HTTP.
- Default listen address: `0.0.0.0`.
- Default port: `8000`.
- MCP URL: `http://<raspberry-pi-ip>:8000/mcp`.

## Architecture

```text
MacBook tests / Codex MCP client
  -> streamable HTTP MCP
  -> Raspberry Pi I/O MCP server
  -> GPIO service layer
  -> GPIO adapter
  -> GPIO Zero
  -> Raspberry Pi GPIO23/GPIO24
```

The MCP tool layer must not access GPIO directly. It calls a service layer that validates device IDs, direction, and allowed actions before calling the GPIO adapter.

## Device Model

The first milestone uses configured logical devices instead of exposing arbitrary pins.

```text
id: gpio23_output
name: GPIO23 Output
kind: output
pin_numbering: BCM
pin: 23
safe_default: 0

id: gpio24_input
name: GPIO24 Input
kind: input
pin_numbering: BCM
pin: 24
pull: down
```

Configuration is stored in `config/rpi-io.toml`. The rest of the code should treat it as a device registry so future protocols can use the same shape.

## Local Environment

Deployment and remote test helpers may read local Raspberry Pi connection details from `.env`. The file is gitignored and must not be committed.

`.env.example` documents the expected variables:

```text
RPI_SSH_HOST
RPI_SSH_PORT
RPI_SSH_USER
RPI_SSH_KEY_PATH
RPI_SSH_PASSWORD
RPI_PROJECT_DIR
RPI_DISCOVERY_SUBNET
RPI_MCP_HOST
RPI_MCP_PORT
RPI_MCP_URL
```

Prefer SSH keys or `ssh-agent` over password-based automation. Password values, if used during development, must remain local.

## Raspberry Pi Discovery Tool

`tools/find_raspberry.py` is a MacBook-side helper for finding a headless Raspberry Pi when the IP address is unknown and SSH is the only open service.

The tool uses standard-library Python only, so it can run before project dependencies are installed.

Discovery behavior:

- Resolve common hostnames such as `raspberrypi.local`.
- Infer local networks from system interfaces and ARP cache when possible.
- Accept explicit CIDR ranges through `--subnet`.
- Use `RPI_DISCOVERY_SUBNET` from `.env` when no `--subnet` is passed.
- Probe TCP port 22 by default.
- Read SSH banners when available.
- Parse ARP cache after probing and mark known Raspberry Pi MAC OUIs as higher-confidence candidates.
- Print candidate SSH hosts in a human-readable table or JSON.
- Refuse to update `.env` if multiple candidates exist unless the operator passes `--select <ip>`.

Primary commands:

```bash
python3 tools/find_raspberry.py --subnet 172.16.0.0/24
python3 tools/find_raspberry.py --subnet 172.16.0.0/24 --select 172.16.0.50 --update-env
```

If the Raspberry Pi is not connected, the tool should report no SSH candidates and leave `.env` unchanged.

## MCP Tool Contract

### `list_devices`

Returns configured devices and their available actions.

Expected structured result:

```json
{
  "devices": [
    {
      "id": "gpio23_output",
      "name": "GPIO23 Output",
      "kind": "output",
      "capabilities": ["set_output"],
      "state": 0
    },
    {
      "id": "gpio24_input",
      "name": "GPIO24 Input",
      "kind": "input",
      "capabilities": ["read_input"],
      "state": 0
    }
  ]
}
```

### `set_output`

Sets an allowed output device to `0` or `1`.

Inputs:

```json
{
  "device_id": "gpio23_output",
  "value": 1
}
```

Expected structured result:

```json
{
  "device_id": "gpio23_output",
  "value": 1,
  "ok": true
}
```

### `read_input`

Reads an allowed input device and returns `0` or `1`.

Inputs:

```json
{
  "device_id": "gpio24_input"
}
```

Expected structured result:

```json
{
  "device_id": "gpio24_input",
  "value": 1,
  "ok": true
}
```

### `health`

Returns service health and basic runtime details without changing hardware state.

Expected structured result:

```json
{
  "ok": true,
  "service": "rpi-io-mcp",
  "transport": "streamable-http"
}
```

## Safety Rules

- Only configured devices may be accessed.
- GPIO23 must be set low/off during service startup.
- GPIO23 must be released or driven low during service shutdown when possible.
- GPIO24 must be configured as input and must not be driven by the service.
- Input reads must return integer `0` or `1`, not truthy strings.
- Loopback testing must use current-limiting protection.
- Relay coils must be driven through an appropriate relay module or driver circuit.
- The first milestone assumes trusted LAN only; do not expose the service to the public internet.

## Error Model

Errors should be structured and stable enough for tests and future agents.

Suggested error codes:

- `unknown_device`
- `wrong_direction`
- `invalid_value`
- `gpio_unavailable`
- `permission_denied`
- `hardware_error`

Each error should include a human-readable message and enough diagnostic context for troubleshooting without exposing shell access or secrets.

## Tests

Unit tests should use a mock GPIO adapter and must not require Raspberry Pi hardware.

MacBook E2E tests connect to the real Raspberry Pi MCP server:

```bash
RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py
```

The E2E loopback test assumes GPIO23 is safely connected to GPIO24. It verifies:

- `list_devices` returns `gpio23_output` and `gpio24_input`.
- `set_output(gpio23_output, 1)` succeeds.
- `read_input(gpio24_input)` returns `1`.
- `set_output(gpio23_output, 0)` succeeds.
- `read_input(gpio24_input)` returns `0`.
- disallowed device or pin access is rejected.

Manual smoke tests:

- Output smoke: connect LED/relay smoke wiring to GPIO23 and verify state by meter or direct observation.
- Input smoke: connect input smoke wiring to GPIO24 and verify MCP reads expected `0` and `1`.
- Codex smoke: add the HTTP MCP URL to Codex, start a new session, and verify Codex can discover and safely call the I/O tools.

## Deployment

Install the server as a systemd service on the Raspberry Pi.

Required behavior:

- Service starts on boot.
- Service restarts on failure.
- Service logs to journald.
- Service runs as a non-root user that has GPIO permissions, if feasible.
- The service process binds the HTTP MCP endpoint on the trusted LAN.

## Open Design Questions

Pending owner review. The current draft proposes `0.0.0.0` on trusted LAN, with the MCP endpoint at `http://<raspberry-pi-ip>:8000/mcp`.

## Change Log

- 2026-04-30: Clarified the proposed listen-address default as `0.0.0.0` on trusted LAN, pending owner review.
