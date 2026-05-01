# Raspberry Pi I/O MCP Server Design

Status: Implemented
Last reviewed: 2026-05-01  
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
RPI_DISCOVERY_SUBNET
RPI_MCP_HOST
RPI_MCP_PORT
RPI_MCP_URL
```

The systemd install path on the Pi is fixed at `/opt/raspberry-smarthome` —
no `RPI_PROJECT_DIR` override — so the unit file, deploy script, and docs all
agree without templating.

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
- Loopback testing must avoid direct contention. A current-limiting resistor is preferred; a bare jumper is acceptable while `service.py` and the GPIO adapter enforce GPIO24 as input-only — any write to it returns `wrong_direction`, so misconfiguration requires a code-level regression rather than a wiring choice.
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

## Resolved Design Decisions

- Listen address: `0.0.0.0` on trusted LAN, MCP endpoint at `http://<raspberry-pi-ip>:8000/mcp`. Approved 2026-04-30 with the rest of Milestone 1.

## Decisions Discovered During Implementation

These were not in the original approved spec; they surfaced during Milestone 1
implementation and hardware verification on 2026-04-30/2026-05-01 and are
recorded here per the issue #9 closeout requirement to capture work-discovered
decisions.

- **Loopback wiring relaxed to allow a bare jumper.** Original spec (this file
  and `requirements.md:90`) required a current-limiting resistor on the
  GPIO23↔GPIO24 link. Owner-approved revision in PR #35: a bare jumper is also
  acceptable, because contention safety is upheld at the software level —
  `service.py` and the GPIO adapter both reject any write to a device with
  `kind: input`, so misconfiguration that could create CMOS-driver contention
  requires a code-level regression rather than a wiring choice. The resistor
  remains the recommended option; the jumper unblocks operators without one.
- **systemd unit User= is templated at install time.** Default Raspbian
  installs use a `pi` user (UID 1000), but Bookworm-and-later installers
  prompt for an arbitrary username, and operators sometimes rename the
  primary user. The unit file in `deploy/systemd/rpi-io-mcp.service` keeps
  `User=pi` as the canonical default; `scripts/deploy_rpi_io_mcp.sh`
  sed-substitutes `User=pi` and `/home/pi/` paths to match `RPI_SSH_USER`
  before installing into `/etc/systemd/system/`. Avoids an opaque
  status=203/EXEC failure when the deploy user isn't `pi`. Documented in
  `docs/deployment.md`.
- **systemd ExecStart uses an absolute path to `uv`.** systemd's ExecStart
  binary lookup uses its own internal PATH and does not consult the unit's
  `Environment="PATH=..."` line; a relative `uv run rpi-io-mcp` failed with
  status=203/EXEC when uv was installed under `~/.local/bin` (the default for
  pipx-installed uv). The unit now invokes
  `/home/pi/.local/bin/uv run --no-dev rpi-io-mcp`, sed-substituted at
  install time. The `--no-dev` matches `uv sync --no-dev` in the deploy
  script so dev dependencies are not silently re-synced on first start.
- **SIGTERM handler in `server.py:main()`.** systemd's default behavior
  terminates the process on `systemctl stop`/`restart` without running
  Python `finally` blocks. Without explicit handling, `service.close()`
  would not run and GPIO23 could remain at its last driven value until the
  next service start. `main()` now installs a SIGTERM handler that raises
  `SystemExit(0)`, which propagates through `try/finally` and ensures
  `service.close()` drives outputs low. `TimeoutStopSec=10` in the unit
  caps the SIGTERM-to-SIGKILL window so a hung shutdown cannot silently
  bypass GPIO teardown. The setup block is wrapped in the same try/finally
  so that a SIGTERM during config load or adapter init still releases the
  adapter.
- **Partial-init cleanup in `GPIOService.__init__`.** If `_init_pins`
  succeeds for GPIO23 but raises for GPIO24, `__init__` now best-effort
  calls `self.close()` before re-raising so GPIO23 is not left configured
  without a teardown path. design.md Safety Rules require GPIO23 not stay
  driven without a release path on shutdown; this extends that discipline
  to partial-init failures.
- **E2E hardware tests skipped by default; `--run-hardware` opts in.**
  `tests/e2e/conftest.py` auto-skips `@pytest.mark.hardware` tests unless
  the operator passes `--run-hardware`. Lets `uv run pytest tests/e2e/`
  succeed when the operator only has the server reachable but no loopback
  wiring; the loopback tests still gate Milestone 1 acceptance when the
  jumper is present.
- **Apt prerequisites for `lgpio` source build are wider than originally
  documented.** `pyproject.toml`'s comment listed `libffi-dev`,
  `python3-dev`, and `build-essential`. Source-building `lgpio` on armv7l
  also needs **`swig`** (codegen) and **`liblgpio-dev`** (system C library
  to link against). `docs/deployment.md` Prerequisites now includes both;
  see Change Log there.

## Change Log

- 2026-04-30: Clarified the proposed listen-address default as `0.0.0.0` on trusted LAN, pending owner review.
- 2026-04-30: Owner approved the listen-address decision with the rest of Milestone 1 (issue `#1` closed). Section retitled "Resolved Design Decisions".
- 2026-05-01: Implementation landed (#32, #35, #36, #38). Added "Decisions Discovered During Implementation" section capturing the loopback-wiring revision, systemd User= templating, absolute uv ExecStart, SIGTERM handler, partial-init cleanup, hardware-skip conftest, and the wider apt prereq list. Status remains Approved pending Pi reboot persistence and Codex MCP smoke per `tasks.md` task 10.
- 2026-05-01: Closeout (issue #9) complete. Pi reboot persistence and Codex MCP smoke both passed. Status flipped from Approved to Implemented; Last reviewed bumped to 2026-05-01.
