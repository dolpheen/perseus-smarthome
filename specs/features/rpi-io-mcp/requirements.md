# Raspberry Pi I/O MCP Server

Status: Approved
Last reviewed: 2026-05-01  
Owner: Vadim  
Parent spec: ../../project.spec.md  
Related code: ../../../config/rpi-io.toml; ../../../pyproject.toml; ../../../src/perseus_smarthome/config.py; ../../../src/perseus_smarthome/devices.py; ../../../src/perseus_smarthome/gpio.py; ../../../src/perseus_smarthome/service.py; ../../../src/perseus_smarthome/server.py; ../../../deploy/systemd/rpi-io-mcp.service; ../../../scripts/deploy_rpi_io_mcp.sh; ../../../docs/deployment.md; ../../../docs/manual-smoke-tests.md; ../../../tools/find_raspberry.py; ../../../tools/smoke_meter.py  
Related tests: ../../../tests/test_config.py; ../../../tests/test_devices.py; ../../../tests/test_gpio.py; ../../../tests/test_service.py; ../../../tests/test_mcp_server.py; ../../../tests/test_find_raspberry.py; ../../../tests/e2e/test_rpi_io_mcp.py

## Summary

The first project milestone is a Raspberry Pi I/O MCP server running on a Raspberry Pi 2. It exposes MCP tools for basic GPIO output control and GPIO input reading. The server must run persistently on the Raspberry Pi and automatically recover after reboot.

This milestone does not implement an LLM agent. It proves the hardware-facing MCP layer with end-to-end tests run from a MacBook.

The canonical first test configuration uses BCM numbering, GPIO23 as the output test pin, and GPIO24 as the input test pin.

## Source Material Reviewed

- Raspberry Pi GPIO documentation, checked 2026-04-30: https://www.raspberrypi.com/documentation/hardware/raspberrypi/
- Raspberry Pi OS downloads, checked 2026-04-30: https://www.raspberrypi.com/software/operating-systems/
- MCP Python SDK `pyproject.toml`, checked 2026-04-30: https://github.com/modelcontextprotocol/python-sdk
- GPIO Zero installation documentation, checked 2026-04-30: https://gpiozero.readthedocs.io/en/latest/installing.html

## Goals

- Run an MCP server on Raspberry Pi 2 for GPIO I/O control.
- Expose a safe MCP tool contract for turning a configured output on and off.
- Expose a safe MCP tool contract for reading a configured input as `0` or `1`.
- Start automatically after Raspberry Pi reboot.
- Pass end-to-end MCP tests from a MacBook against the Raspberry Pi.

## Non-Goals

- No LLM agent implementation.
- No CC2531, Zigbee, WiFi, BLE, or Z-Wave implementation in this milestone.
- No unrestricted GPIO access.
- No home automation rule engine.
- No human UI unless required for diagnostics.

## Users And Actors

- Home operator: configures allowed GPIO pins and verifies wiring.
- MacBook test runner: runs E2E tests against the Raspberry Pi MCP server.
- Raspberry Pi MCP server: exposes MCP tools and performs GPIO operations.
- GPIO output: a configured pin connected to a test output device or loopback circuit.
- GPIO input: a configured pin connected to a test input device or loopback circuit.

## Functional Requirements

- IO-MCP-FR-001: The server must expose an MCP tool that sets a configured output to logical `1`.
- IO-MCP-FR-002: The server must expose an MCP tool that sets a configured output to logical `0`.
- IO-MCP-FR-003: The server must expose an MCP tool that reads a configured input and returns logical `0` or `1`.
- IO-MCP-FR-004: The server must expose a way to list configured I/O devices or pins available to the MCP client.
- IO-MCP-FR-005: The server must reject attempts to access unconfigured or disallowed pins.
- IO-MCP-FR-006: The server must report GPIO access failures as structured MCP errors.
- IO-MCP-FR-007: The server must be reachable from the MacBook test runner over the selected MCP transport.
- IO-MCP-FR-008: The server must be installed as a service or equivalent startup mechanism that starts after Raspberry Pi reboot.
- IO-MCP-FR-009: End-to-end tests from the MacBook must verify output `on`, output `off`, input reads `1`, and input reads `0`.
- IO-MCP-FR-010: The test suite must fail clearly if the MCP server is unreachable, the configured pins are unavailable, or observed I/O values do not match expected values.
- IO-MCP-FR-011: The first E2E loopback test must use BCM GPIO23 as output and BCM GPIO24 as input.
- IO-MCP-FR-012: A manual smoke test must verify GPIO23 output behavior with LED and relay wiring, checked by meter or direct observation.
- IO-MCP-FR-013: A manual smoke test must verify GPIO24 input behavior with physical input wiring or meter-supported setup.
- IO-MCP-FR-014: The server must expose streamable HTTP MCP over the trusted LAN for first milestone testing.
- IO-MCP-FR-015: The systemd service must reset GPIO23 to low/off when the service starts after restart or reboot.
- IO-MCP-FR-016: The project must provide a MacBook-side discovery tool that can find candidate Raspberry Pi hosts on the LAN when the device is headless and only SSH is open.

## Acceptance Criteria

- Given the Raspberry Pi has booted, when no manual command has been run after boot, then the MCP server is running and reachable from the MacBook.
- Given BCM GPIO23 is configured as an allowed output, when the MacBook E2E test calls the MCP output-on tool, then GPIO23 is set to logical `1`.
- Given BCM GPIO23 is configured as an allowed output, when the MacBook E2E test calls the MCP output-off tool, then GPIO23 is set to logical `0`.
- Given BCM GPIO23 is safely looped back to BCM GPIO24 and GPIO23 is set to logical `1`, when the MacBook E2E test reads GPIO24, then the MCP result is `1`.
- Given BCM GPIO23 is safely looped back to BCM GPIO24 and GPIO23 is set to logical `0`, when the MacBook E2E test reads GPIO24, then the MCP result is `0`.
- Given GPIO23 is connected to the LED/relay smoke setup, when the output is toggled by MCP, then the operator can verify the expected output state by meter or direct observation.
- Given GPIO24 is connected to the input smoke setup, when the input state changes physically, then the operator can verify the MCP input read matches the expected `0` or `1`.
- Given the MCP server URL is registered in Codex, when Codex starts a new session, then Codex can discover the Raspberry Pi I/O MCP tools.
- Given the Raspberry Pi is connected to the same LAN and SSH is open, when the operator runs the discovery tool against the LAN subnet, then the tool lists SSH candidates and highlights Raspberry Pi-like candidates when possible.
- Given exactly one Raspberry Pi candidate is selected, when the operator runs the discovery tool with env update enabled, then the tool updates local `.env` host fields without writing secrets.
- Given a disallowed pin is requested, when any MCP I/O tool is called, then the server rejects the request without changing hardware state.

## Constraints

- Hardware target: Raspberry Pi 2.
- Test client: MacBook.
- The server must not require an LLM to run tests.
- GPIO pin numbering mode: BCM.
- Output test pin: GPIO23.
- Input test pin: GPIO24.
- Loopback test wiring must avoid unsafe direct contention if a pin is misconfigured. A current-limiting resistor between GPIO23 and GPIO24 is preferred; a bare jumper is acceptable because the service layer and GPIO adapter enforce GPIO24 as input-only (any write to it returns `wrong_direction`), so contention requires a code-level regression that the reviewer would block.
- LED smoke wiring must include a current-limiting resistor.
- Relay smoke wiring must use a relay module or driver circuit appropriate for Raspberry Pi GPIO; relay coils must not be connected directly to a GPIO pin.
- GPIO inputs must not receive 5V.
- MCP transport: streamable HTTP over LAN.
- Service manager: systemd.
- Network exposure: trusted LAN only.
- Authentication: no authentication for first milestone.
- Raspberry Pi SSH access for deployment and remote checks must be configured through local `.env` values or SSH agent state.
- `.env` must be gitignored; `.env.example` documents required variable names without real secrets.
- Output state after service restart or Raspberry Pi reboot: reset GPIO23 to low/off.
- Codex MCP testing is a separate manual smoke test and must not replace deterministic MacBook E2E tests.
- Raspberry Pi OS: Raspberry Pi OS Lite 32-bit based on Debian Trixie.
- Python runtime: Python 3.13 from Debian Trixie.
- MCP SDK runtime lower bound: Python 3.10+.
- Package manager: `uv`.
- Dependency lock: `uv.lock`.
- Test runner: pytest.
- GPIO configuration: `config/rpi-io.toml`.

## Interfaces

- MCP tool for output control.
- MCP tool for input reading.
- MCP tool or resource for available configured I/O.
- Raspberry Pi GPIO library or system interface: prefer GPIO Zero for first implementation, with a mockable adapter boundary for tests.
- Reboot-persistent systemd service.
- MacBook E2E test command: `RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py`.
- Codex MCP client configuration using `codex mcp add <name> --url <URL>`.
- Local Raspberry Pi access configuration through `.env` variables documented in `.env.example`.
- Raspberry Pi discovery command: `python3 tools/find_raspberry.py --subnet <lan-cidr>`.
- Raspberry Pi discovery may also use `RPI_DISCOVERY_SUBNET` from local `.env`.

## Error Handling And Edge Cases

- MCP server unreachable from MacBook.
- GPIO library unavailable or missing permissions.
- Requested pin is not configured.
- Requested pin is configured for the wrong direction.
- Input is floating or unstable because the loopback is disconnected or pull state is not configured.
- Loopback wiring is unsafe because both pins are accidentally configured as outputs driving opposite values.
- Relay wiring draws more current than GPIO can safely supply.
- Service fails to start after reboot.
- Server restarts while output state is active.
- Raspberry Pi is disconnected from LAN; the discovery tool must report no SSH candidates without changing `.env`.
- Multiple SSH hosts are found; the discovery tool must not update `.env` unless a single likely candidate exists or the operator selects one explicitly.

## Verification

- E2E test: MacBook connects to the Raspberry Pi MCP server and lists available I/O.
- E2E loopback test: MacBook turns BCM GPIO23 on and verifies BCM GPIO24 reads `1`.
- E2E loopback test: MacBook turns BCM GPIO23 off and verifies BCM GPIO24 reads `0`.
- Manual smoke test: operator connects LED/relay smoke wiring to GPIO23 and verifies the expected output by meter or direct observation.
- Manual smoke test: operator connects input smoke wiring to GPIO24 and verifies MCP reads the expected `0` and `1`.
- Reboot test: reboot Raspberry Pi, wait for service startup, then rerun the MacBook E2E tests.
- Negative test: attempt to access a disallowed pin and verify rejection.
- Separate manual Codex smoke test: register the HTTP MCP URL with Codex, start a new Codex session, list or invoke safe I/O tools, and do not treat this as a substitute for automated E2E tests.
- Unit test: LAN discovery helper parsing and `.env` update logic.
- Unit tests must run through pytest.
- Manual discovery test: connect the Raspberry Pi to LAN, run `python3 tools/find_raspberry.py --subnet <lan-cidr>`, and verify the correct SSH candidate is reported.
- Manual discovery env test: run `python3 tools/find_raspberry.py --subnet <lan-cidr> --select <ip> --update-env` and verify only local `.env` host fields are updated.

## Open Questions

None for Milestone 1 implementation.

## Change Log

- 2026-04-30: Initial feature requirements created from owner clarification.
- 2026-04-30: Set BCM GPIO23 as output, BCM GPIO24 as input, loopback as automated E2E verification, and LED/relay as manual smoke verification.
- 2026-04-30: Added input smoke verification and accepted first milestone defaults: streamable HTTP over trusted LAN, systemd, no auth, GPIO23 reset low/off after restart or reboot, and separate manual Codex MCP client smoke test.
- 2026-04-30: Set first milestone runtime to Raspberry Pi OS Lite 32-bit based on Debian Trixie, Python 3.13, GPIO Zero, and a canonical MacBook E2E test command.
- 2026-04-30: Set `uv` and `uv.lock` as dependency management, `config/rpi-io.toml` as GPIO config, and `.env` as gitignored local Raspberry Pi access configuration.
- 2026-04-30: Added headless Raspberry Pi LAN discovery tool requirement using SSH probing and safe local `.env` updates.
- 2026-04-30: Set pytest as the project test runner.
- 2026-04-30: Owner approved Milestone 1 requirements (issue `#1` closed). Status flipped to Approved.
- 2026-05-01: Implementation landed across PRs #32 (#5), #35 (#6), #36 (#7), and #38 (#8). Related code and Related tests fields populated. Loopback wiring constraint (line 90) revised in PR #35 to permit a bare jumper alongside the preferred current-limiting resistor — the safety guarantee comes from the device-direction enforcement in `service.py` and the GPIO adapter, not from the wiring choice. Status remains Approved; flips to Implemented after Pi reboot persistence and Codex MCP smoke are verified per `tasks.md` task 10.
