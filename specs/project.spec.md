# Raspberry Pi Smart Home LLM Control

Status: Draft  
Last reviewed: 2026-04-30  
Owner: Vadim  
Related code: config/rpi-io.toml; tools/find_raspberry.py; implementation TBD  
Related tests: tests/test_find_raspberry.py; implementation tests TBD

## Summary

This project is a Raspberry Pi smart home control system where an LLM agent can observe and control supported home devices through Model Context Protocol (MCP) tools.

The initial target board is Raspberry Pi 2. Initial connectivity includes Raspberry Pi I/O and a CC2531 USB stick. Future connectivity may include WiFi, BLE, and Z-Wave.

The first implementation milestone is MCP-only Raspberry Pi I/O control. LLM agent behavior is explicitly out of scope for the first milestone.

## Goals

- Provide a clear MCP interface that lets an LLM agent interact with smart home devices.
- Support direct Raspberry Pi I/O for local hardware control and sensing.
- Deliver a Raspberry Pi I/O MCP server that runs on the Raspberry Pi 2 and survives reboot.
- Verify Raspberry Pi I/O behavior from a MacBook with end-to-end MCP tests.
- Support CC2531-based smart home connectivity in the initial system scope.
- Keep protocol-specific device control behind stable, typed MCP tools.
- Make hardware control safe enough for unattended or semi-attended agent use.
- Keep the architecture extensible for future WiFi, BLE, and Z-Wave device support.

## Non-Goals

- The system will not expose unrestricted hardware or shell access to the LLM agent.
- The first milestone will not implement the LLM agent itself; it only implements and verifies the MCP layer for Raspberry Pi I/O.
- The system will not assume all future connectivity protocols are implemented in the first release.
- The system will not treat generated code as the primary source of truth; specifications and reviewed implementation both remain authoritative.

## Users And Actors

- Home operator: the human owner who configures devices, reviews permissions, and approves dangerous capabilities.
- LLM agent: the software actor that calls MCP tools to inspect and control the smart home.
- MacBook test runner: the development machine that runs end-to-end MCP tests against the Raspberry Pi.
- Raspberry Pi host: the runtime environment for hardware-facing services.
- Smart home devices: GPIO-connected devices, CC2531-connected devices, and future WiFi, BLE, or Z-Wave devices.
- MCP client: the local or remote system that connects the LLM agent to the MCP server.

## Functional Requirements

- FR-001: The system must expose smart home capabilities to the LLM agent through MCP tools.
- FR-002: The system must support Raspberry Pi I/O as an initial connectivity path.
- FR-003: The system must support CC2531 USB stick connectivity as an initial smart home path.
- FR-004: The system must represent devices with stable identifiers, human-readable names, connectivity type, capabilities, and current state when available.
- FR-005: The system must allow the agent to discover available devices and their supported actions.
- FR-006: The system must enforce an allowlist or permission model so the agent can only control approved devices and actions.
- FR-007: The system must report command success, command failure, and device-unavailable states in a structured way.
- FR-008: The system must be designed so WiFi, BLE, and Z-Wave support can be added without changing the MCP contract for existing devices.
- FR-009: The first milestone must provide Raspberry Pi I/O MCP tools for setting an output on/off and reading an input as `0` or `1`.
- FR-010: The first milestone MCP server must be installed and running on the Raspberry Pi 2.
- FR-011: The first milestone MCP server must automatically start after Raspberry Pi reboot.
- FR-012: The first milestone must pass end-to-end MCP tests run from a MacBook against the Raspberry Pi.

## Constraints

- Hardware: the first test board is Raspberry Pi 2.
- Hardware: first Raspberry Pi I/O tests use BCM numbering, output GPIO23, and input GPIO24.
- Hardware safety: Raspberry Pi GPIO logical high is 3.3V and logical low is 0V; test wiring must not apply 5V to GPIO inputs.
- Hardware safety: LEDs must use current-limiting resistors, and relay coils must not be driven directly from GPIO pins.
- Hardware: initial non-GPIO smart home connectivity uses a CC2531 USB stick.
- Runtime: first milestone MCP transport is HTTP over LAN.
- Runtime: first milestone deployment uses a systemd service on the Raspberry Pi.
- Runtime: first milestone target OS is Raspberry Pi OS Lite 32-bit based on Debian Trixie.
- Runtime: first milestone implementation language is Python.
- Runtime: first milestone target Python version is Python 3.13 from Debian Trixie, with the MCP Python SDK requirement of Python 3.10+ as the lower bound.
- Testing: pytest is the project test runner.
- Developer workflow: a MacBook-side LAN discovery tool must help find the headless Raspberry Pi by probing SSH candidates.
- Safety: the agent must not be able to toggle arbitrary GPIO pins or unregistered devices.
- Safety: first milestone output state must reset to low/off after service restart or Raspberry Pi reboot.
- Security: first milestone is trusted LAN only with no authentication.
- Security: Raspberry Pi SSH credentials must be kept in local gitignored environment files or the SSH agent, never in committed specs or code.
- Reliability: the first milestone MCP server must survive Raspberry Pi reboot by running under a reboot-persistent service mechanism.

## Interfaces

- MCP server interface for LLM agent control.
- Raspberry Pi I/O interface for local pins, sensors, and actuators.
- MacBook-to-Raspberry-Pi MCP test interface for first milestone verification.
- CC2531 integration interface, exact stack TBD.
- Future extension interfaces for WiFi, BLE, and Z-Wave.

## Error Handling And Edge Cases

- Unknown device identifier must return a structured error.
- Unsupported action for a device must return a structured error.
- Unapproved or unsafe action must be rejected before touching hardware.
- Disconnected CC2531 stick or unavailable smart home backend must be reported clearly.
- Raspberry Pi I/O access failures must include enough diagnostic context for operator troubleshooting.
- Raspberry Pi LAN discovery must report no candidates clearly when the Raspberry Pi is disconnected and must not write credentials to the repository.

## Verification

- Unit tests for MCP tool schemas, device registry behavior, permission checks, and error responses.
- Local tests run through pytest.
- Integration tests or smoke tests for Raspberry Pi I/O on the Raspberry Pi 2.
- End-to-end MCP loopback tests from a MacBook that turn GPIO23 on/off and verify GPIO24 reads `1` and `0`.
- Manual smoke tests with GPIO23 output and GPIO24 input, including LED/relay output verification by meter or direct observation.
- Separate manual client smoke test through Codex after deterministic MCP E2E tests are green.
- Manual Raspberry Pi discovery test using `tools/find_raspberry.py` when the headless board is connected to LAN.
- Manual or automated smoke test for CC2531-connected devices once the target stack is selected.
- Regression checks that existing MCP tool contracts remain compatible when new connectivity types are added.

## Open Questions

1. For CC2531, should the project integrate through Zigbee2MQTT, direct serial/Zigbee libraries, Home Assistant, or another stack?
2. Should device state and action history be persisted across restarts?
3. Should the project provide a human UI, or is agent/MCP control enough for the first version?
4. What future protocol should influence the architecture most: WiFi, BLE, or Z-Wave?

## Change Log

- 2026-04-30: Initial draft created from project discussion. Details still require owner clarification before implementation.
- 2026-04-30: Added first milestone scope: Raspberry Pi I/O MCP server only, reboot persistence, and MacBook E2E tests.
- 2026-04-30: Set first I/O test configuration to BCM GPIO23 output and BCM GPIO24 input, with loopback E2E and LED/relay smoke verification.
- 2026-04-30: Accepted first milestone defaults: HTTP over LAN, systemd service, trusted LAN without auth, output reset low/off after restart or reboot, and separate manual Codex MCP smoke test.
- 2026-04-30: Set first milestone runtime to Raspberry Pi OS Lite 32-bit based on Debian Trixie and Python 3.13.
- 2026-04-30: Set `uv` as the default package manager, `config/rpi-io.toml` as first milestone GPIO config, and `.env` as gitignored local Raspberry Pi access configuration.
- 2026-04-30: Added MacBook-side headless Raspberry Pi LAN discovery tool based on SSH probing.
- 2026-04-30: Set pytest as the project test runner.
