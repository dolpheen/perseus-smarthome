# Deployment Optimization Tasks

Status: Approved
Last reviewed: 2026-05-01  
Owner: Vadim  
Requirements: requirements.md  
Design: design.md

## Acceptance Gate

This feature is complete when:

- A fresh Pi can be brought from clean Trixie image to running service in
  one Mac-side command.
- An existing install can be re-deployed and uninstalled idempotently
  through the same entrypoint.
- A `.deb` artifact can be built on the Pi, installed via `apt`, removed
  via `apt remove`, and purged via `apt purge` with the correct semantics.
- Both paths satisfy the existing Milestone 1 acceptance behavior: systemd
  autostart on reboot, GPIO23 safe-default 0 at every service start.
- `docs/deployment.md` is rewritten around the new flow and the legacy
  `scripts/deploy_rpi_io_mcp.sh` is removed.

## Implementation Strategy

The work splits into three roughly disjoint scopes that can run in parallel
worktrees per `AGENTS.md::Parallel Worktree Workflow`:

- **scripts**: `scripts/install.sh`, `scripts/remote-install.sh`,
  `scripts/lib.sh`, plus the systemd unit `ExecStart` change.
- **packaging**: `packaging/debian/`, `packaging/build-deb.sh`.
- **docs + makefile**: `Makefile`, `docs/deployment.md`, removal of the
  legacy script.

Each scope ends with a verification step. The integration verification
(reboot persistence, E2E rerun, deb cycle on a real Pi) happens last and
gates spec status flip from Approved to Implemented.

## GitHub Implementation Issues

Opened 2026-05-01 after owner approved the specs:

- `#43`: Refactor systemd unit `ExecStart` to `.venv/bin/rpi-io-mcp` and
  drop the per-user `/home/<user>/` PATH dependency. Also expands
  `.github/copilot-instructions.md` so subsequent deployment issues see
  the new specs in the standing required-reading list. Lands first.
- `#44`: Add `scripts/install.sh`, `scripts/lib.sh`, and the
  `install`/`upgrade`/`uninstall`/`status` subcommands per `design.md`.
  Blocked by `#43`.
- `#45`: Replace `scripts/deploy_rpi_io_mcp.sh` with
  `scripts/remote-install.sh`. Deletes the legacy script in the same PR.
  Blocked by `#44`.
- `#46`: Add top-level `Makefile` exposing all targets per
  `design.md::Makefile`. Blocked by `#44` and `#45`.
- `#47`: Add `packaging/debian/` and `packaging/build-deb.sh`. Verifies
  the drift-check between packaged and canonical units. Blocked by `#43`.
- `#48`: Closeout — full acceptance run on a real Pi for both install
  paths, then flip Status from Approved to Implemented. Blocked by `#43`,
  `#44`, `#45`, `#46`, `#47` all merged.

Dependency graph:

```text
#43 ── #44 ── #45 ── #46 ─┐
  │                       │
  └── #47 ────────────────┴── #48
```

Each issue carries the standard SDD-style shape: scope, files, spec
requirement IDs, acceptance, verify command. See
`AGENTS.md::Issue And Task Shape`.

## Implementation Tasks

1. Refactor systemd `ExecStart` (issue `#43`)

   - Update `deploy/systemd/rpi-io-mcp.service`:
     - `ExecStart=/opt/raspberry-smarthome/.venv/bin/rpi-io-mcp`.
     - Drop the `Environment="PATH=..."` line.
     - `User=pi` remains the canonical default; sed-substitution at install
       time still varies it per host.
   - Update `scripts/deploy_rpi_io_mcp.sh` to also run `uv sync --no-dev`
     against `/opt/raspberry-smarthome` (it already does — verify) and to
     no longer rewrite `/home/pi/` paths in the unit.
   - Verify on the Pi: `systemctl restart rpi-io-mcp.service`, run the E2E
     suite, confirm the journal shows the new ExecStart line.
   - Spec refs: `DEP-FR-027`, `DEP-FR-028`; `design.md::Resolved Design
     Decisions::2`.

2. Add `scripts/lib.sh` and `scripts/install.sh` (issue `#44`)

   - `scripts/lib.sh` with `log`, `die`, `require_root`, `apt_missing`.
   - `scripts/install.sh` subcommands `install`, `upgrade`, `uninstall`,
     `status` per `design.md::Script: scripts/install.sh`.
   - Idempotent: re-running `install` is a no-op if everything is already
     in the desired state.
   - Add a refusal guard against `dpkg -l perseus-smarthome` showing the
     `.deb`-managed install.
   - Include a `--user` flag for `install` (used by the remote wrapper).
   - Verify on the Pi: fresh-install on a clean image, then re-run
     `install`, then `uninstall`, then `uninstall --purge`. Each must
     succeed.
   - Spec refs: `DEP-FR-001` through `DEP-FR-011`.

3. Replace remote deploy with `scripts/remote-install.sh` (issue `#45`)

   - New `scripts/remote-install.sh` that reads `.env`, rsyncs to the Pi,
     and invokes `scripts/install.sh` on the Pi over SSH.
   - Delete `scripts/deploy_rpi_io_mcp.sh` in the same PR. The legacy
     script must not survive merge — two entrypoints will drift.
   - Update `docs/deployment.md` Option A to reference
     `./scripts/remote-install.sh install` (the script entrypoint), not
     `make remote-install`. The Makefile and `make remote-install` land
     in `#46` and `#46` itself promotes the docs to the `make` form;
     this avoids `#45`'s docs pointing at a target that does not exist
     on `main` until `#46` merges.
   - Verify from the Mac: `./scripts/remote-install.sh install` against a
     working Pi end-to-end.
   - Spec refs: `DEP-FR-012` through `DEP-FR-014`.

4. Add `Makefile` (issue `#46`)

   - Top-level `Makefile` with all targets in `design.md::Makefile`.
   - `help` is the default goal and prints from `## ` annotations on each
     target.
   - Verify: `make help` prints every target with one-line descriptions;
     `make install`, `make uninstall`, `make remote-install`, `make
     remote-uninstall` all delegate correctly.
   - Spec refs: `DEP-FR-024` through `DEP-FR-026`.

5. Add Debian package definition (issue `#47`)

   - `packaging/debian/control`, `changelog`, `conffiles`, `preinst`,
     `postinst`, `prerm`, `postrm` per `design.md::Debian Package`.
   - `packaging/build-deb.sh` produces `dist/perseus-smarthome_<version>_armhf.deb`
     on a Pi and includes the drift-check between the packaged unit and
     the canonical unit.
   - The packaged unit uses `User=perseus-smarthome` and is staged into
     `_build/.../etc/systemd/system/`.
   - Verify on the Pi: `make deb` succeeds; `dpkg-deb -I` shows expected
     `Depends:`; `dpkg-deb -c` shows `.venv/bin/rpi-io-mcp` in the
     payload; `apt install ./dist/*.deb` succeeds; `apt remove` and
     `apt purge` cycle correctly.
   - Spec refs: `DEP-FR-015` through `DEP-FR-023`.

6. Closeout: full acceptance run on a real Pi (issue `#48`)

   - Build the `.deb` on the Pi.
   - Wipe the Pi to a clean state (or use a second Pi). Run `make
     remote-install`. Run the existing E2E suite with `--run-hardware`.
     Reboot the Pi. Confirm autostart and GPIO23 safe-default 0. Rerun
     E2E.
   - Wipe again. `apt install ./dist/*.deb`. Same E2E run. Reboot.
     Same checks.
   - `apt remove`, then `apt purge`. Confirm clean state.
   - Update `requirements.md`, `design.md`, `tasks.md` Status from
     Approved to Implemented and add Change Log entries with the
     verification results.
   - Update `AGENTS.md::Current Status` to mention the new install paths.
   - Spec refs: all `DEP-FR-*` acceptance criteria + `DEP-FR-027`,
     `DEP-FR-028`.

## Remaining Decisions Before Code

None. Owner approved `requirements.md`, `design.md`, and `tasks.md` on
2026-05-01. Implementation issues `#43`–`#48` are open. The next gate is
`#48` (real-Pi acceptance run), which flips the three deployment specs
from Approved to Implemented.

## Change Log

- 2026-05-01: Initial draft. Pending owner approval before issues are
  opened or implementation begins.
- 2026-05-01: Owner approved. Status flipped from Draft to Approved.
  GitHub issues `#43`–`#48` opened.
- 2026-05-01: Spec-PR review punch-list landed inline: task `#45`
  clarified that `docs/deployment.md` references the script entrypoint
  until the Makefile lands in `#46`; "Remaining Decisions Before Code"
  rewritten now that approval has happened.
