# Raspberry Pi I/O MCP Server Tasks

Status: Implemented
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

- Milestone 1 requirements, design, and task plan are Implemented (issue `#1` closed 2026-04-30; closeout #9 closed 2026-05-01).
- Tasks 1–9 implemented and merged to `main` across PRs #18, #21, #22, #28, #29, #31, #32, #35, #36, #38; closeout (task 10) merged via the issue #9 PR on 2026-05-01.
- All four hardware/client acceptance gates passed on the live Pi (172.16.0.101, user `perseus`):
  - Automated MacBook E2E loopback (jumper-wired): 12/12 PASS via `--run-hardware`.
  - Manual multimeter smoke (`tools/smoke_meter.py`): 5/5 PASS.
  - Pi reboot persistence: `sudo reboot`; systemd autostarted the service with GPIO23 at safe-default 0; E2E rerun green.
  - Codex MCP smoke: `codex mcp add rpi-io --url http://172.16.0.101:8000/mcp`; fresh Codex session invoked `rpi-io.list_devices` and received both devices with capabilities and states. The Codex TUI `/mcp` panel does not render user-registered streamable HTTP servers in this CLI version (0.125.0); discoverability and invocation work — verified via tool call.
- systemd service: installed, `systemctl is-active` → `active`, MCP endpoint reachable across reboot.

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

Per-task status as of 2026-05-01: tasks 1–10 are **Done** on `main`. All four
acceptance gates (automated E2E, manual GPIO smoke, Pi reboot persistence,
Codex MCP smoke) signed off on 2026-05-01.

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

10. Documentation closeout (Done — issue #9, 2026-05-01)

Closeout work landed in the issue #9 PR:

- `specs/project.spec.md` — Related code/tests fields populated; Change Log entry records Milestone 1 final verification. Project spec stays `Approved` (project scope still includes future-milestone CC2531/Zigbee/WiFi/BLE/Z-Wave work and the LLM agent layer, none of which are implemented yet).
- `specs/features/rpi-io-mcp/requirements.md` — Status flipped to `Implemented`; Related code/tests already populated; Change Log entry added.
- `specs/features/rpi-io-mcp/design.md` — Status flipped to `Implemented`; Last reviewed bumped; "Decisions Discovered During Implementation" section already captured work-time choices (loopback-wiring revision, systemd User= templating, absolute uv ExecStart, SIGTERM handler, partial-init cleanup, hardware-skip conftest, wider apt prereqs).
- `specs/features/rpi-io-mcp/tasks.md` — Status flipped to `Implemented`; Current Status records all four gates green.
- `AGENTS.md` — Current Status section updated from "Implementation is in progress" to Milestone 1 implemented + verified; "Not implemented yet" list converted to a Milestone 1 completion summary.
- `docs/deployment.md` — apt prereqs corrected to include `swig` and `liblgpio-dev` (already merged via PR #39).

Acceptance gates signed off on 2026-05-01:

- Automated MacBook E2E `--run-hardware`: 12/12 PASS.
- Manual GPIO smoke (multimeter via `tools/smoke_meter.py`): 5/5 PASS.
- Pi reboot persistence: `sudo reboot`; systemd autostart confirmed; GPIO23 reset to 0; E2E rerun green.
- Codex MCP smoke: `codex mcp add rpi-io --url http://172.16.0.101:8000/mcp`; fresh Codex session called `rpi-io.list_devices` and received both configured devices with capabilities and states.

Issue #9 closed on merge.

## Remaining Decisions Before Code

None for Milestone 1 implementation.

## Change Log

- 2026-04-30: Added GitHub issue mapping and clarified that implementation remains blocked until owner approval.
- 2026-04-30: Owner approved Milestone 1 specs (issue `#1` closed). Status flipped to Approved; implementation begins with `#2`.
- 2026-05-01: Tasks 1–9 implemented and merged. Per-task PR pointers and "Done" markers added. Task 10 in progress; spec status flip to Implemented deferred until Pi reboot persistence and Codex MCP smoke are signed off (issue #9).
- 2026-05-01: Closeout (task 10) complete. All four acceptance gates green (automated E2E 12/12, multimeter smoke 5/5, Pi reboot persistence, Codex MCP smoke). Status flipped from Approved to Implemented. Issue #9 closed.
