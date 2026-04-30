# Raspberry Pi I/O MCP Server Tasks

Status: Approved
Last reviewed: 2026-05-01  
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

## Current Status

- Milestone 1 requirements, design, and task plan are approved (issue `#1` closed 2026-04-30).
- Tasks 1–9 implemented and merged to `main` across PRs #18, #21, #22, #28, #29, #31, #32, #35, #36, #38.
- Hardware verification on the live Pi (172.16.0.101, user `perseus`) is partially complete:
  - Automated MacBook E2E loopback (jumper-wired): 12/12 PASS via `--run-hardware`.
  - Manual multimeter smoke (`tools/smoke_meter.py`): 5/5 PASS.
  - systemd service: installed, `systemctl is-active` → `active`, MCP endpoint reachable.
- Two acceptance gates outstanding before flipping spec status to Implemented:
  - **Pi reboot persistence check** — full `sudo reboot`; verify systemd autostarts the service and GPIO23 is at safe-default 0 before E2E tests run.
  - **Codex MCP smoke** — `codex mcp add rpi-io --url ...`, new Codex session, list/call tools.
- Closeout (task 10) lands once both gates are signed off.

## GitHub Implementation Issues

- `#1`: Approve Milestone 1 Raspberry Pi I/O MCP specs.
- `#2`: Scaffold Python project with uv and dependencies.
- `#3`: Load GPIO devices from config/rpi-io.toml.
- `#4`: Add GPIO adapter boundary with mock and GPIO Zero runtime adapter.
- `#5`: Implement streamable HTTP MCP server tools for GPIO I/O.
- `#6`: Add MacBook E2E MCP loopback tests.
- `#7`: Add systemd deployment path for Raspberry Pi MCP server.
- `#8`: Document manual GPIO and Codex MCP smoke tests.
- `#9`: Close out Milestone 1 specs after implementation verification.

## Implementation Tasks

Per-task status as of 2026-05-01: tasks 1–9 are **Done** on `main`. Task 10 is
**In progress** (this work + the Pi reboot persistence and Codex smoke gates).

1. Project scaffold (Done — PR #18)

- Create Python project metadata and dependency management.
- Use `uv` as the package manager.
- Commit `uv.lock`.
- Add MCP Python SDK dependency.
- Add GPIO dependency strategy for Raspberry Pi runtime and mock tests.
- Add pytest as the test dependency.

2. Device registry (Done — PR #21, hardened in PR #29 / #31)

- Define configured devices `gpio23_output` and `gpio24_input`.
- Load configured devices from `config/rpi-io.toml`.
- Enforce BCM numbering.
- Reject unknown device IDs.
- Prevent output operations on input devices and input reads on output devices.

3. GPIO adapter (Done — PR #22, mock-contract gaps fixed in PR #28)

- Implement GPIO adapter interface.
- Implement GPIO Zero adapter for Raspberry Pi runtime.
- Implement mock adapter for unit tests.
- Ensure GPIO23 resets to low/off on startup.
- Ensure GPIO24 is configured only as input.

4. MCP server (Done — PR #32; SIGTERM hardening + partial-init cleanup added inline)

- Implement streamable HTTP MCP server.
- Add `health` tool.
- Add `list_devices` tool.
- Add `set_output` tool.
- Add `read_input` tool.
- Return structured success and error results.

5. Unit tests (Done — PR #32; 116 unit tests across config, devices, gpio, service, mcp_server)

- Test tool schemas and structured result shape.
- Test allowed output on/off.
- Test input read `0` and `1`.
- Test unknown device rejection.
- Test wrong-direction rejection.
- Test invalid value rejection.
- Test startup safe default for GPIO23.

6. MacBook E2E tests (Done — PR #35; auto-skips hardware tests unless `--run-hardware` is passed; loopback wiring permits resistor or jumper)

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

7. systemd deployment (Done — PR #36; deploy script templatizes User= from RPI_SSH_USER and uses absolute uv path with --no-dev)

- Add systemd unit file.
- Add install/update instructions.
- Add helper scripts or documented commands that can read Raspberry Pi SSH connection values from local `.env`.
- Ensure service starts on boot.
- Ensure service restarts on failure.
- Document logs via `journalctl`.

8. Raspberry Pi discovery tool (Done — `tools/find_raspberry.py` shipped before Milestone 1 implementation began; verified on the LAN at 172.16.0.101)

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

9. Manual smoke tests (Done — PR #38; `docs/manual-smoke-tests.md` covers multimeter / LED / relay / GPIO24-input / Codex paths; `tools/smoke_meter.py` automates the multimeter walk-through)

- Document GPIO23 LED/relay output smoke wiring and check steps.
- Document GPIO24 input smoke wiring and check steps.
- Document Codex MCP smoke test:

```bash
codex mcp add rpi-io --url http://<raspberry-pi-ip>:8000/mcp
codex mcp list
codex mcp get rpi-io
```

- Record that a new Codex session is required before tools are available.

10. Documentation closeout (In progress — issue #9)

Already done as of 2026-05-01:

- `specs/project.spec.md` — Related code and Related tests filled with the implemented files.
- `specs/features/rpi-io-mcp/requirements.md` — Related code and Related tests filled.
- `specs/features/rpi-io-mcp/design.md` — "Decisions Discovered During Implementation" section captures work-time choices: loopback-wiring revision, systemd User= templating, absolute uv ExecStart, SIGTERM handler, partial-init cleanup, hardware-skip conftest, and the wider apt prereqs list.
- `docs/deployment.md` — apt prereqs corrected to include `swig` and `liblgpio-dev`.

Pending before flipping `Status: Approved` → `Status: Implemented` on this file
plus `requirements.md` and `design.md`:

- Pi reboot persistence check: `sudo reboot` the Pi, wait for boot, run
  `RPI_MCP_URL=http://<pi>:8000/mcp uv run pytest tests/e2e/ --run-hardware`
  from the MacBook and confirm the systemd unit autostarted the service with
  GPIO23 reset to 0.
- Codex MCP smoke: `codex mcp add rpi-io --url http://<pi>:8000/mcp`,
  `codex mcp list`, `codex mcp get rpi-io`, then start a fresh Codex session
  and confirm the tools list and call cleanly.
- Update Status fields on `requirements.md`, `design.md`, and this `tasks.md`
  to `Implemented`. Update Last reviewed dates. Add Change Log entries.
- Close issue #9.

## Remaining Decisions Before Code

None for Milestone 1 implementation.

## Change Log

- 2026-04-30: Added GitHub issue mapping and clarified that implementation remains blocked until owner approval.
- 2026-04-30: Owner approved Milestone 1 specs (issue `#1` closed). Status flipped to Approved; implementation begins with `#2`.
- 2026-05-01: Tasks 1–9 implemented and merged. Per-task PR pointers and "Done" markers added. Task 10 in progress; spec status flip to Implemented deferred until Pi reboot persistence and Codex MCP smoke are signed off (issue #9).
