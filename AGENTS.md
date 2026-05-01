# AGENTS.md

This repo uses Specification-Driven Development (SDD). Do not start coding a behavior change until the relevant spec is read and either already approved for the current scope or updated first.

## Project Context

Project: Raspberry Pi smart home control through MCP.

Milestone 1: Raspberry Pi I/O MCP server only. No LLM agent implementation yet.

Target:

- Board: Raspberry Pi 2.
- OS: Raspberry Pi OS Lite 32-bit based on Debian Trixie.
- Runtime: Python 3.13.
- Package manager: `uv`; commit `uv.lock`.
- Test runner: `pytest`.
- MCP transport: streamable HTTP over trusted LAN.
- Service manager: systemd.
- GPIO numbering: BCM.
- Output test pin: GPIO23.
- Input test pin: GPIO24.
- GPIO config: `config/rpi-io.toml`.
- Local Raspberry Pi access: `.env` only; never commit secrets. See `.env.example`.

## Required Reading

Before implementation, read:

- `docs/sdd-workflow.md`
- `docs/agent-pr-workflow.md`
- `specs/project.spec.md`
- `specs/features/rpi-io-mcp/requirements.md`
- `specs/features/rpi-io-mcp/design.md`
- `specs/features/rpi-io-mcp/tasks.md`

## Current Status

Milestone 1 (Raspberry Pi I/O MCP server) is **Implemented** on `main` as of
2026-05-01. The feature spec under `specs/features/rpi-io-mcp/` is at
`Status: Implemented`. The project-level spec at `specs/project.spec.md`
remains `Status: Approved` because broader project scope (CC2531/Zigbee,
future WiFi/BLE/Z-Wave connectivity, and the LLM agent layer) is not yet
implemented.

GitHub issues `#1` through `#9` are closed. All four Milestone 1 acceptance
gates passed on the live Pi (host coordinates in local `.env`):

- Automated MacBook E2E loopback: 12/12 PASS via `--run-hardware`.
- Manual multimeter smoke (`tools/smoke_meter.py`): 5/5 PASS.
- Pi reboot persistence: `sudo reboot`; systemd autostarted the service with
  GPIO23 reset to safe-default 0; E2E rerun green.
- Codex MCP smoke: `codex mcp add rpi-io --url http://<raspberry-pi-ip>:8000/mcp`;
  fresh Codex session called `rpi-io.list_devices` and received both
  configured devices.

Repository infrastructure in place:

- SDD workflow and specs.
- Claude Code reviewer workflow + Copilot inline reviewer; both gate auto-merge.
- CI workflow running `uv run pytest -m "not e2e and not hardware"` on PRs and pushes to `main`.
- Auto-merge workflow gated on `pytest` + `claude-review` + zero unresolved Copilot review threads, opt-out via `critical`, `needs-manual-verification`, or `do-not-merge` labels on the PR or any linked issue. See `docs/agent-pr-workflow.md`.
- `.gitignore`, `.env.example`, `config/rpi-io.toml`, `tools/find_raspberry.py`, `tools/smoke_meter.py`.

Implemented for Milestone 1:

- Python project scaffold with `uv` and `uv.lock`.
- `src/perseus_smarthome/` — `config.py`, `devices.py`, `gpio.py` (mock + GPIO Zero adapter), `service.py`, `server.py` (FastMCP streamable HTTP).
- 118 unit tests across config, devices, gpio, service, mcp_server, find_raspberry.
- MacBook E2E suite at `tests/e2e/test_rpi_io_mcp.py` with `--run-hardware` opt-in for loopback tests.
- systemd service at `deploy/systemd/rpi-io-mcp.service`, remote wrapper at `scripts/remote-install.sh`, deployment guide at `docs/deployment.md`, manual smoke guide at `docs/manual-smoke-tests.md`.

## What To Do Next

Milestone 1 is complete. Future milestones (not yet specified or scheduled)
will likely cover:

- CC2531 USB stick connectivity and Zigbee device support (see `specs/project.spec.md` Open Questions).
- Additional connectivity protocols: WiFi, BLE, Z-Wave.
- LLM agent layer that consumes the MCP tool contract.
- Persistence of device state and action history (currently process-local).
- Optional human UI for diagnostics.

When a new milestone is opened, follow the SDD workflow in
`docs/sdd-workflow.md`: write or extend the spec first, get owner approval,
then break into small implementation issues.

To re-verify the deployed Milestone 1 stack on the Pi:

```bash
python3 tools/find_raspberry.py --subnet <lan-cidr>
RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/ --run-hardware
codex mcp add rpi-io --url http://<raspberry-pi-ip>:8000/mcp
```

## Parallel Worktree Workflow

For implementation work, prefer parallel git worktrees when tasks can be split cleanly by ownership. This is especially useful for Milestone 1 because scaffold/config, MCP server behavior, tests, and deployment docs can be developed independently.

Use worktrees when:

- Multiple agents or parallel tasks are working at once.
- The write scopes are disjoint.
- The task is more than a trivial doc or single-line edit.
- Parallel work will shorten feedback time without creating merge conflicts.

Avoid worktrees when:

- The task is trivial.
- The change is spec-only and can be made directly.
- The task touches the same files as another active worktree.
- The coordination overhead is larger than the work.

Suggested pattern:

```bash
git worktree add ../perseus-smarthome-<task> -b <task-branch>
```

Each worktree must have an explicit responsibility, for example:

- `scaffold-config`: `pyproject.toml`, package layout, config loader, related tests.
- `mcp-server`: MCP tool implementation and server entrypoint.
- `gpio-adapter`: GPIO adapter interface, GPIO Zero adapter, mock adapter.
- `deployment`: systemd unit, deploy docs/scripts, smoke test docs.

Before merging worktree results:

- Run the relevant tests in that worktree.
- Summarize changed files and verification.
- Do not revert or overwrite changes from other worktrees.
- Integrate through normal git merges or patches after reviewing conflicts.

## Issue And Task Shape

Write implementation issues so weaker coding LLMs can complete them reliably.

Prefer small, concrete issues:

- One behavior change per issue.
- One clear owner or worktree.
- Explicit files or modules likely to be touched.
- Explicit inputs, outputs, and edge cases.
- Explicit verification command.
- Links to the relevant spec requirement IDs.

Avoid broad issues:

- "Implement MCP server"
- "Make deployment work"
- "Add tests"
- "Clean up architecture"

Better issue shape:

```text
Title: Load GPIO devices from config/rpi-io.toml
Scope: config loader and device registry only
Files: src/perseus_smarthome/config.py, tests/test_config.py
Spec: IO-MCP-FR-004, IO-MCP-FR-005
Acceptance:
- loads gpio23_output and gpio24_input
- rejects duplicate device IDs
- rejects unsupported pin numbering
Verify: uv run pytest tests/test_config.py
```

If an issue cannot be described this concretely, split it or ask for clarification before implementation.

## SDD Rules

- Specs are durable project memory. Keep them fresh.
- Any behavior-changing code change must update the related spec in the same work cycle.
- If code and spec disagree, treat it as a defect.
- Keep project-wide behavior in `specs/project.spec.md`.
- Keep Milestone 1 I/O MCP details in `specs/features/rpi-io-mcp/`.
- Move specs from `Draft` to `Approved` only after owner review.
- Move specs to `Implemented` only after acceptance criteria are verified.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
