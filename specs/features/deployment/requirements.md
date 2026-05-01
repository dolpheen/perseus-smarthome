# Deployment Optimization

Status: Approved
Last reviewed: 2026-05-01  
Owner: Vadim  
Parent spec: ../../project.spec.md  
Related feature: ../rpi-io-mcp/requirements.md  
Related code: ../../../scripts/install.sh (planned, `#44`); ../../../scripts/lib.sh (planned, `#44`); ../../../scripts/remote-install.sh (planned, `#45`, replaces `scripts/deploy_rpi_io_mcp.sh`); ../../../Makefile (planned, `#46`); ../../../packaging/build-deb.sh (planned, `#47`); ../../../packaging/debian/ (planned, `#47`); ../../../deploy/systemd/rpi-io-mcp.service (modified, `#43`); ../../../docs/deployment.md (modified across `#43`/`#45`/`#46`)  
Related tests: ../../../tests/scripts/ (planned, `#44`); existing `tests/e2e/test_rpi_io_mcp.py` is the verification harness for both install paths under `#48` (no functional changes — re-run with `--run-hardware` against each freshly installed Pi)

## Summary

Replace the single Mac-side deploy script with two first-class install paths and
a Makefile front-end. The two paths are:

1. **Script install** — a Pi-side bash entrypoint that handles fresh install,
   in-place upgrade, and uninstall, with explicit error messages and
   idempotent behavior. Driven by `make install`. Optionally invoked over SSH
   from the Mac through a thin remote wrapper that supersedes the current
   `scripts/deploy_rpi_io_mcp.sh`.
2. **Debian package** — a `.deb` artifact built on the Pi (armv7l) that
   bundles a self-contained virtualenv so apt installs are offline-capable
   and atomic. Standard `apt install` and `apt remove`/`apt purge` semantics.

Both paths must produce the same end state: the `rpi-io-mcp` systemd service
running from `/opt/raspberry-smarthome`, autostarted on boot, with the GPIO23
safe-default behavior already verified for Milestone 1.

This feature is deployment infrastructure only; it does not change the MCP
tool contract, the GPIO behavior, or the trusted-LAN security posture.

## Source Material Reviewed

- Debian Policy Manual `dpkg-deb` and maintainer scripts, checked 2026-05-01:
  https://www.debian.org/doc/debian-policy/
- `dh_systemd_enable` and `systemd.unit` behavior on Trixie, checked
  2026-05-01.
- `uv` deployment patterns (`uv sync --no-dev`, prebuilt venv portability),
  checked 2026-05-01: https://docs.astral.sh/uv/
- Existing Milestone 1 deployment artifacts:
  `scripts/deploy_rpi_io_mcp.sh`, `deploy/systemd/rpi-io-mcp.service`,
  `docs/deployment.md`.

## Goals

- Make a fresh-Pi install reachable from a single command without the operator
  pre-installing apt build dependencies, `uv`, or fixing group membership by
  hand.
- Make in-place upgrade safe: re-running install must not break a working
  service or leave it in a half-upgraded state.
- Make uninstall complete and reversible: the operator can return the Pi to a
  clean state, with `--purge` semantics that match Debian conventions.
- Provide a packaging artifact (`.deb`) so the project can be installed and
  removed with the operator's existing apt workflow.
- Expose both paths through one Makefile so the operator does not have to
  remember script names.
- Preserve the Milestone 1 acceptance posture: GPIO23 safe-default on every
  start, systemd autostart on boot, structured journald logging, no public
  network exposure.

## Non-Goals

- Cross-distribution support. The script and package target Raspberry Pi OS
  Lite 32-bit (Debian Trixie) on Pi 2 only.
- Cross-architecture build of the `.deb`. The package is built on armv7l
  hardware (Pi 2) or an armv7l container by the maintainer; cross-build from
  the Mac is out of scope for this iteration.
- Adding authentication, TLS, or any expansion of the network exposure model.
- Adding new MCP tools, GPIO behavior, or device support.
- Maintaining a public apt repository. The `.deb` is distributed as a release
  artifact (or built locally); apt repository hosting is a later concern.
- Replacing systemd as the service manager.
- Configurable install path. `/opt/raspberry-smarthome` remains fixed so unit,
  scripts, and docs stay in sync.

## Users And Actors

- Home operator: installs, upgrades, and removes the service on the Pi. May
  drive installs from the Mac or directly on the Pi.
- Maintainer: builds the `.deb` artifact on a Pi or armv7l container.
- Raspberry Pi: runtime target.
- systemd: service manager that hosts `rpi-io-mcp.service`.
- apt / dpkg: package manager that consumes the `.deb`.

## Functional Requirements

### Script install

- DEP-FR-001: The repository must provide `scripts/install.sh` with explicit
  subcommands: `install`, `upgrade`, `uninstall`, `status`.
- DEP-FR-002: `scripts/install.sh install` must be idempotent. Re-running on
  an already-installed system must converge to the desired state without
  failure and without unnecessary downtime.
- DEP-FR-003: `scripts/install.sh install` must install the apt build
  prerequisites required by the `lgpio` and `cffi` source builds when they
  are not already present (`libffi-dev`, `python3-dev`, `build-essential`,
  `swig`, `liblgpio-dev`).
- DEP-FR-004: `scripts/install.sh install` must install `uv` if it is not
  already on PATH for the deploy user, using the upstream installer.
- DEP-FR-005: `scripts/install.sh install` must add the deploy user to the
  `gpio` group if not already a member, and warn the operator that they must
  re-login or reboot before the service can access GPIO if the group was
  newly added.
- DEP-FR-006: `scripts/install.sh install` must stage the project under
  `/opt/raspberry-smarthome` with ownership matching the deploy user and the
  `gpio` group, run `uv sync --no-dev`, render and install the systemd unit
  to `/etc/systemd/system/rpi-io-mcp.service`, run `systemctl daemon-reload`,
  and `systemctl enable --now rpi-io-mcp.service`.
- DEP-FR-007: `scripts/install.sh upgrade` must update an existing install in
  place without changing the deploy user, then restart the service. It must
  fail clearly if no install is detected.
- DEP-FR-008: `scripts/install.sh uninstall` must stop and disable the
  service and remove `/etc/systemd/system/rpi-io-mcp.service`. With `--purge`
  it must also remove `/opt/raspberry-smarthome`.
- DEP-FR-009: `scripts/install.sh status` must print `systemctl is-active`,
  `systemctl is-enabled`, the service version (from
  `/opt/raspberry-smarthome/pyproject.toml`), and a local reachability
  check against `http://localhost:<port>/mcp`.
- DEP-FR-010: All subcommands must produce structured, prefixed log lines
  (`==> step description`) and non-zero exit on any failure with a clear
  message naming the failed step and the suggested remediation.
- DEP-FR-011: All subcommands must require root or sudo where needed and
  fail with a clear error if neither is available.

### Remote install wrapper

- DEP-FR-012: The repository must provide `scripts/remote-install.sh` that
  reads `.env` for `RPI_SSH_*` values, copies the working tree to the Pi
  with `rsync` (matching the existing exclude list), and invokes
  `scripts/install.sh <subcommand>` on the Pi over SSH.
- DEP-FR-013: `scripts/remote-install.sh` must accept the same subcommands as
  `scripts/install.sh` and pass through arguments such as `--purge` so the
  Mac-side caller is the only entrypoint operators need to remember.
- DEP-FR-014: `scripts/remote-install.sh` must replace the existing
  `scripts/deploy_rpi_io_mcp.sh`. The legacy script must be removed in the
  same change to prevent two parallel deployment paths from drifting.

### Debian package

- DEP-FR-015: The repository must provide `packaging/debian/` with the files
  required to build `perseus-smarthome_<version>_armhf.deb` using
  `dpkg-deb -b` (no debhelper dependency on the Pi).
- DEP-FR-016: The package build step must produce a self-contained virtualenv
  inside the package payload at `/opt/raspberry-smarthome/.venv` so the
  installed package has no install-time network requirement and no
  install-time source build.
- DEP-FR-017: The package `Depends:` line must include the runtime apt
  packages required by the bundled venv (e.g. `liblgpio1`, `libffi8`) but
  must not depend on `-dev` packages or compilers, since the venv is
  prebuilt.
- DEP-FR-018: The package `postinst` must add the service user to the `gpio`
  group, run `systemctl daemon-reload`, and `systemctl enable --now
  rpi-io-mcp.service`. It must be safe to re-run.
- DEP-FR-019: The package `prerm` must `systemctl stop` and `systemctl
  disable` the service so apt can remove unit and venv files cleanly.
- DEP-FR-020: The package `postrm` must `systemctl daemon-reload` on
  `remove`. On `purge` it must additionally remove `/opt/raspberry-smarthome`
  (the install root) and any package-created system user.
- DEP-FR-021: The package must declare a service user and create it in
  `postinst` if it does not already exist (Debian convention: a system user
  with home `/opt/raspberry-smarthome` and shell `/usr/sbin/nologin`).
- DEP-FR-022: `apt install ./dist/perseus-smarthome_<version>_armhf.deb`,
  `apt remove perseus-smarthome`, and `apt purge perseus-smarthome` must
  each succeed and converge the system to the expected state without manual
  cleanup.
- DEP-FR-023: The repository must provide `packaging/build-deb.sh` that
  performs the venv build, stages `_build/`, and runs `dpkg-deb -b` to
  produce the `.deb` in `dist/`. The script must be runnable on the Pi
  itself.

### Makefile

- DEP-FR-024: A top-level `Makefile` must expose at least the following
  targets: `help`, `install`, `upgrade`, `uninstall`, `status`,
  `remote-install`, `remote-upgrade`, `remote-uninstall`, `deb`,
  `deb-install`, `deb-uninstall`, `deb-purge`, `clean`, `test`.
- DEP-FR-025: `make help` must print a one-line description for every target
  and must be the default goal so the operator gets discoverable usage.
- DEP-FR-026: Make targets must be thin wrappers around the underlying
  scripts, not reimplementations. The script remains the source of truth for
  install logic.

### Compatibility with existing requirements

- DEP-FR-027: Both install paths must satisfy the existing
  `IO-MCP-FR-008` (service starts after Pi reboot) and `IO-MCP-FR-015`
  (GPIO23 reset to safe-default 0 on every service start).
- DEP-FR-028: Both install paths must keep the install root fixed at
  `/opt/raspberry-smarthome` so the unit file, scripts, and docs do not have
  to template paths beyond `User=`.

## Acceptance Criteria

- Given a fresh Raspberry Pi OS Lite 32-bit (Trixie) image with only the
  default user account and SSH enabled, when the operator runs
  `make remote-install` from the Mac with a populated `.env`, then the
  service is running, `systemctl is-active rpi-io-mcp.service` returns
  `active`, and the MCP endpoint answers on the configured LAN address.
- Given an existing install at `/opt/raspberry-smarthome`, when the operator
  re-runs `make install` (or `make remote-install`), then the install
  succeeds without errors, the service is restarted at most once, and the
  endpoint is reachable again within 30 seconds of the install command
  completing.
- Given an existing install, when the operator runs `make uninstall` followed
  by `make uninstall PURGE=1` (or the underlying `--purge`), then
  `systemctl status rpi-io-mcp.service` reports the unit as not loaded and
  `/opt/raspberry-smarthome` no longer exists.
- Given a maintainer running `make deb` on a Pi, when the build completes,
  then `dist/perseus-smarthome_<version>_armhf.deb` exists, `dpkg-deb -I`
  shows the expected `Depends:` line, and `dpkg-deb -c` shows
  `/opt/raspberry-smarthome/.venv/bin/rpi-io-mcp` in the payload.
- Given the built `.deb`, when the operator runs
  `sudo apt install ./dist/perseus-smarthome_<version>_armhf.deb`, then the
  service is installed, the systemd unit is enabled and active, and the MCP
  endpoint responds.
- Given an installed package, when the operator runs `sudo apt remove
  perseus-smarthome`, then the service is stopped and disabled, the unit
  file is removed, but configuration under `/opt/raspberry-smarthome` is
  retained per Debian convention. When the operator then runs `sudo apt
  purge perseus-smarthome`, the install root and any created system user
  are removed.
- Given either install path was used, when the Pi is rebooted, then the
  service autostarts within 60 seconds of boot completion and GPIO23 is at
  logical 0 before the service accepts requests
  (re-verifies `IO-MCP-FR-015`).
- Given either install path was used, when the operator runs
  `RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run pytest tests/e2e/`
  from the Mac, then the existing E2E suite passes (with `--run-hardware`
  when loopback wiring is present).

## Constraints

- Hardware target: Raspberry Pi 2 (armv7l).
- OS target: Raspberry Pi OS Lite 32-bit based on Debian Trixie.
- Service manager: systemd.
- Install path: `/opt/raspberry-smarthome` (fixed; no per-host override).
- Package name: `perseus-smarthome` (matches `pyproject.toml::project.name`).
- Package architecture: `armhf`.
- Package build host: Pi 2 hardware or armv7l container; cross-build out of
  scope.
- Network exposure remains trusted-LAN only with no authentication, matching
  Milestone 1.
- `.env` and SSH credentials must never be embedded in the script, the
  package, or any built artifact.
- The systemd service must continue to run with GPIO group access; root is
  not required at runtime.
- Both install paths must coexist without one leaving state that confuses the
  other (e.g. dpkg's database vs. script-managed files in the same
  directory).

## Interfaces

- Operator (Mac, fresh install): `make remote-install`.
- Operator (Pi, fresh install): `sudo make install` or
  `sudo apt install ./dist/<deb>`.
- Operator (Mac, upgrade): `make remote-upgrade`.
- Operator (Pi, upgrade): `sudo make upgrade` or
  `sudo apt install ./dist/<deb>` for a newer version.
- Operator (uninstall): `sudo make uninstall` /
  `sudo make uninstall PURGE=1` /
  `sudo apt remove perseus-smarthome` /
  `sudo apt purge perseus-smarthome`.
- Maintainer (build deb): `make deb` on a Pi, producing `dist/*.deb`.
- Configuration via `.env` (Mac side only): existing `RPI_SSH_*` variables.
- systemd unit name: `rpi-io-mcp.service` (unchanged).

## Error Handling And Edge Cases

- Operator runs `install.sh` without sudo or root: fail clearly before any
  state change.
- Operator runs `install.sh upgrade` on a system that has no prior install:
  fail clearly with a hint to use `install`.
- apt prerequisite install fails because the Pi is offline: fail clearly,
  do not partially configure the service.
- `uv` install script fails or is blocked by a proxy: fail clearly, do not
  leave a half-installed `uv`.
- Operator is added to `gpio` group during install but has not re-logged in:
  warn explicitly that the service may fail to access GPIO until the next
  login or reboot.
- `dpkg-deb` build fails because the venv build failed: leave no partial
  `.deb` in `dist/`.
- `.deb` install fails partway through `postinst`: dpkg's standard behavior
  applies (package remains in `iF` state); the postinst must be safe to
  re-run after the operator fixes the underlying cause (e.g. missing apt
  dependency).
- Operator installs the `.deb` on top of a script-managed install: the
  `.deb` must either reuse `/opt/raspberry-smarthome` cleanly or refuse with
  a clear message. The chosen behavior must be documented in the design and
  validated.
- Operator runs `make install` on top of a `.deb`-managed install: same
  concern in the other direction.
- Pi has the legacy `rpi-io-mcp.service` from the old deploy script and is
  upgraded to the new install path: the new install must replace the legacy
  unit cleanly without leaving two units enabled.

## Verification

- Fresh-install acceptance test: provision a Pi from a clean Trixie image,
  run `make remote-install`, then run the existing E2E suite with
  `--run-hardware`. Document this run in the closeout entry.
- Re-install idempotency test: run `make install` twice in a row on the
  same Pi; assert that the second run completes and the service stays
  reachable across both runs.
- Uninstall test: run `make uninstall PURGE=1` and assert the unit is gone,
  `/opt/raspberry-smarthome` is gone, and `systemctl status
  rpi-io-mcp.service` reports the unit as not loaded.
- Deb build test: `make deb` produces a `.deb`; `dpkg-deb -I` and
  `dpkg-deb -c` outputs are inspected against expectations.
- Deb install/remove/purge cycle test: install the `.deb`, verify service,
  `apt remove`, verify service stopped but install root preserved,
  `apt purge`, verify clean state.
- Reboot persistence test: reboot the Pi from each install path, verify
  systemd autostart and GPIO23 safe-default 0 on entry, rerun the E2E
  suite.
- Cross-path coexistence test: install via script, then attempt
  `apt install` of the `.deb`; record observed behavior and document the
  supported mode.
- Manual smoke: `make help` prints all targets with one-line descriptions.
- Unit-test-able pieces: any non-trivial bash helper in `scripts/lib.sh`
  should have at least a smoke test or `bats`-style runner if introduced;
  tracking decision deferred to design.

## Open Questions

All four questions raised against the Draft were resolved in
`design.md::Resolved Design Decisions` and are recorded here for
traceability. They are no longer open.

1. **Resolved.** Service user model for the `.deb`: divergent by design.
   Script path runs the service as the deploy user; `.deb` creates a
   dedicated `perseus-smarthome` system user in `postinst`. Both are
   added to the `gpio` group. Mixing the two paths on the same Pi is
   explicitly unsupported. See `design.md::Resolved Design Decisions::1`
   and `Cross-Path Coexistence`.
2. **Resolved.** systemd `ExecStart` form: switched to
   `/opt/raspberry-smarthome/.venv/bin/rpi-io-mcp`. Drops the runtime
   `uv` dependency and the per-user `~/.local/bin` path. See
   `design.md::Resolved Design Decisions::2`.
3. **Resolved.** Unit location: canonical unit stays at
   `deploy/systemd/rpi-io-mcp.service`. The `.deb` ships its own copy
   under `packaging/debian/perseus-smarthome.service` and the build
   script asserts the two are equal after `User=` substitution. See
   `design.md::Resolved Design Decisions::3`.
4. **Resolved.** Cross-path coexistence: not supported. Both install
   paths refuse with a clear error (script-install via
   `dpkg-query -W -f='${Status}'`; `.deb` `preinst` via the same check
   in reverse) when the other path's install is detected. A documented
   migration recipe is a possible follow-up but is out of scope for this
   iteration. See `design.md::Resolved Design Decisions::4`.

## Change Log

- 2026-05-01: Initial draft created from owner request to add a script
  install path with idempotent install/upgrade/uninstall, a Debian package
  path, and a Makefile front-end. Confirmed: bundle the venv into the
  `.deb`; replace `scripts/deploy_rpi_io_mcp.sh` with
  `scripts/remote-install.sh` that wraps `scripts/install.sh`. Pending
  owner approval before design is locked.
- 2026-05-01: Owner approved requirements, design, and tasks. Status
  flipped from Draft to Approved. Implementation begins under issues
  `#43`–`#48` per `tasks.md`.
- 2026-05-01: Spec-PR review punch-list landed inline: `Related code`
  and `Related tests` headers populated with planned files (per-issue
  attribution); `Open Questions` rewritten to record that all four
  questions were resolved in `design.md`; `#A`–`#F` placeholders
  replaced with the actual issue numbers `#43`–`#48`.
