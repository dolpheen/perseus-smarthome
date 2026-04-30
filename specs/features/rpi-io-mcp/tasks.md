# Raspberry Pi I/O MCP Server Tasks

Status: Draft  
Last reviewed: 2026-04-30  
Owner: Vadim  
Requirements: requirements.md  
Design: design.md

## Milestone 1 Acceptance

This milestone is complete when:

- The MCP server runs on Raspberry Pi 2.
- The server starts automatically after Raspberry Pi reboot.
- MacBook E2E loopback tests are green.
- Manual output smoke test is completed for GPIO23.
- Manual input smoke test is completed for GPIO24.
- Separate manual Codex MCP smoke test is completed.

## Implementation Tasks

1. Project scaffold

- Create Python project metadata and dependency management.
- Use `uv` as the package manager.
- Commit `uv.lock`.
- Add MCP Python SDK dependency.
- Add GPIO dependency strategy for Raspberry Pi runtime and mock tests.
- Add pytest as the test dependency.

2. Device registry

- Define configured devices `gpio23_output` and `gpio24_input`.
- Load configured devices from `config/rpi-io.toml`.
- Enforce BCM numbering.
- Reject unknown device IDs.
- Prevent output operations on input devices and input reads on output devices.

3. GPIO adapter

- Implement GPIO adapter interface.
- Implement GPIO Zero adapter for Raspberry Pi runtime.
- Implement mock adapter for unit tests.
- Ensure GPIO23 resets to low/off on startup.
- Ensure GPIO24 is configured only as input.

4. MCP server

- Implement streamable HTTP MCP server.
- Add `health` tool.
- Add `list_devices` tool.
- Add `set_output` tool.
- Add `read_input` tool.
- Return structured success and error results.

5. Unit tests

- Test tool schemas and structured result shape.
- Test allowed output on/off.
- Test input read `0` and `1`.
- Test unknown device rejection.
- Test wrong-direction rejection.
- Test invalid value rejection.
- Test startup safe default for GPIO23.

6. MacBook E2E tests

- Implement E2E test file `tests/e2e/test_rpi_io_mcp.py`.
- Read target URL from `RPI_MCP_URL`.
- Verify `list_devices`.
- Verify loopback: GPIO23 high maps to GPIO24 read `1`.
- Verify loopback: GPIO23 low maps to GPIO24 read `0`.
- Verify disallowed access rejection.
- Use canonical command:

```bash
RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py
```

7. systemd deployment

- Add systemd unit file.
- Add install/update instructions.
- Add helper scripts or documented commands that can read Raspberry Pi SSH connection values from local `.env`.
- Ensure service starts on boot.
- Ensure service restarts on failure.
- Document logs via `journalctl`.

8. Raspberry Pi discovery tool

- Implement `tools/find_raspberry.py`.
- Support hostname lookup, explicit subnet scanning, SSH probing, ARP/MAC enrichment, JSON output, and safe `.env` updates.
- Add unit tests for discovery helper parsing and `.env` update logic.
- Ensure discovery tests run through pytest.
- Document discovery command:

```bash
python3 tools/find_raspberry.py --subnet <lan-cidr>
```

- Document safe `.env` update command:

```bash
python3 tools/find_raspberry.py --subnet <lan-cidr> --select <ip> --update-env
```

9. Manual smoke tests

- Document GPIO23 LED/relay output smoke wiring and check steps.
- Document GPIO24 input smoke wiring and check steps.
- Document Codex MCP smoke test:

```bash
codex mcp add rpi-io --url http://<raspberry-pi-ip>:8000/mcp
codex mcp list
codex mcp get rpi-io
```

- Record that a new Codex session is required before tools are available.

10. Documentation closeout

- Update `specs/project.spec.md` with related code and tests.
- Update `specs/features/rpi-io-mcp/requirements.md` with related code and tests.
- Move spec status from `Draft` to `Approved` only after owner review.
- Move spec status from `Approved` to `Implemented` only after acceptance is complete.

## Remaining Decisions Before Code

None for Milestone 1 implementation.
