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
- `specs/project.spec.md`
- `specs/features/rpi-io-mcp/requirements.md`
- `specs/features/rpi-io-mcp/design.md`
- `specs/features/rpi-io-mcp/tasks.md`

## Current Status

Milestone 1 implementation is not approved yet. The owner still needs to review the specs.

GitHub issue `#1`, "Approve Milestone 1 Raspberry Pi I/O MCP specs", is the active gate. Do not start implementation until `#1` is closed. After approval, use GitHub issue `#2`, "Scaffold Python project with uv and dependencies", as the first implementation task. GitHub issues `#2` through `#9` have native issue Relationships configured from their `Blocked by:` notes.

Already created:

- SDD workflow and specs.
- Draft Milestone 1 Raspberry Pi I/O MCP requirements, design, and task plan.
- GitHub implementation issues `#1` through `#9`.
- Claude Code reviewer workflows and repository review guidance.
- `.gitignore`
- `.env.example`
- `config/rpi-io.toml`
- `tools/find_raspberry.py`
- `tests/test_find_raspberry.py`

Verified:

```bash
python3 -m pytest tests/test_find_raspberry.py
python3 -m py_compile tools/find_raspberry.py tests/test_find_raspberry.py
python3 tools/find_raspberry.py --help
```

Not implemented yet:

- Python project scaffold and dependencies.
- MCP server.
- Device registry.
- GPIO adapter.
- Unit tests for MCP/GPIO behavior.
- MacBook E2E MCP tests.
- systemd service and deployment docs/scripts.
- Manual smoke test docs.

## What To Do Next

First review and approve `specs/features/rpi-io-mcp/requirements.md`, `specs/features/rpi-io-mcp/design.md`, and `specs/features/rpi-io-mcp/tasks.md`. Then follow `specs/features/rpi-io-mcp/tasks.md` and GitHub issue Relationships in order.

Recommended next implementation plan:

1. Close issue `#1` after owner approval.
2. Implement issue `#2`: scaffold Python project with `uv` -> verify: `uv run pytest` works.
3. Implement config/device registry -> verify: unit tests for `config/rpi-io.toml` and wrong-device cases.
4. Implement GPIO adapter boundary and mock adapter -> verify: unit tests without Raspberry Pi hardware.
5. Implement MCP HTTP server tools -> verify: unit tests for `health`, `list_devices`, `set_output`, `read_input`.
6. Add E2E tests -> verify: command accepts `RPI_MCP_URL`.
7. Add systemd/deploy docs/scripts -> verify: static review locally, runtime check later on Pi.

Full acceptance later requires the Raspberry Pi to be connected and wired:

```bash
python3 tools/find_raspberry.py --subnet <lan-cidr>
RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py
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
