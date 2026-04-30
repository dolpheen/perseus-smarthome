# Copilot Instructions

Read `AGENTS.md` before making changes. This repository uses Specification-Driven Development: behavior-changing implementation must match an approved spec or update the relevant spec in the same PR.

Current implementation scope:

- Milestone 1 is approved (issue `#1` closed 2026-04-30). Implementation issues `#2`–`#9` are the work units.
- Milestone 1 scope is Raspberry Pi I/O MCP server only.
- No LLM agent implementation in Milestone 1.
- Target board is Raspberry Pi 2 on Raspberry Pi OS Lite 32-bit based on Debian Trixie.
- Runtime is Python 3.13, package manager is `uv`, and `uv.lock` must be committed.
- MCP transport is streamable HTTP over trusted LAN.
- GPIO numbering is BCM, with GPIO23 as the output test pin and GPIO24 as the input test pin.
- Local Raspberry Pi access belongs in `.env` only; never commit secrets.

Required reading for implementation PRs:

- `docs/sdd-workflow.md`
- `specs/project.spec.md`
- `specs/features/rpi-io-mcp/requirements.md`
- `specs/features/rpi-io-mcp/design.md`
- `specs/features/rpi-io-mcp/tasks.md`

Work from the assigned GitHub issue only. Keep changes surgical, do not refactor unrelated code, and do not implement future CC2531, Zigbee, WiFi, BLE, Z-Wave, UI, or LLM-agent behavior.

For each PR:

- **The PR body MUST contain `Closes #<N>`** (or `Fixes #<N>` / `Resolves #<N>`) referencing the GitHub issue you are implementing. This is how GitHub auto-closes the issue on merge and how the Claude reviewer locates the acceptance criteria. Without it the reviewer flags a Blocking finding and the issue stays open after merge.
- List the specs read.
- List files changed.
- Run the issue's `Verify` commands where possible.
- If hardware verification cannot run, say so explicitly and keep unit tests hardware-free.
- Preserve Raspberry Pi safety constraints: no arbitrary GPIO access, no 5V on GPIO inputs, GPIO23 resets low/off on service start, and GPIO24 is input-only.
- When asked for fix commits, address both the Claude reviewer's punch list and any substantive `copilot-pull-request-reviewer[bot]` inline review comments in the same push, so round 2 sees a clean diff. See `docs/agent-pr-workflow.md` (Parallel Reviewers).
