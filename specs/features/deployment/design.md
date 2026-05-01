# Deployment Optimization Design

Status: Approved
Last reviewed: 2026-05-01  
Owner: Vadim  
Requirements: requirements.md

## Summary

Two install paths that converge on the same end state, fronted by a
top-level `Makefile`. The script path is the operator's primary tool and the
on-Pi entrypoint that the remote wrapper drives over SSH. The Debian package
path is the standard apt-managed alternative; it bundles a prebuilt venv so
installs are atomic and offline-capable.

The systemd unit is refactored to invoke the venv's console script directly
(`.venv/bin/rpi-io-mcp`), removing the runtime dependency on `uv` and on
per-user `~/.local/bin` paths. Both install paths use the same unit content
with `User=` rewritten at install time.

## End State

After either install path completes:

```text
/opt/raspberry-smarthome/
├── .venv/
│   └── bin/rpi-io-mcp                 # console script entrypoint
├── config/rpi-io.toml
├── pyproject.toml
├── src/perseus_smarthome/...
├── tools/...
└── (no .git, no .env, no __pycache__)

/etc/systemd/system/rpi-io-mcp.service  # rendered with effective User=
```

The service is `enable`d and `active`. GPIO23 is at logical 0 before the
process starts accepting requests (existing behavior; not changed by this
spec).

## File Layout

```text
Makefile                               # NEW: top-level entrypoint
scripts/
├── install.sh                         # NEW: Pi-side install/upgrade/uninstall/status
├── remote-install.sh                  # NEW: Mac-side SSH wrapper, replaces deploy_rpi_io_mcp.sh
└── lib.sh                             # NEW: shared logging + sudo helpers
deploy/
└── systemd/rpi-io-mcp.service         # MODIFIED: ExecStart -> .venv/bin/rpi-io-mcp
packaging/
├── build-deb.sh                       # NEW: builds the .deb on a Pi
└── debian/                            # NEW: dpkg-deb control + maintainer scripts
    ├── control                        #   metadata, Depends:
    ├── changelog                      #   debian changelog
    ├── conffiles                      #   /opt/raspberry-smarthome/config/rpi-io.toml
    ├── preinst                        #   refuse on top of script-managed install
    ├── postinst                       #   adduser system user, daemon-reload, enable --now
    ├── prerm                          #   stop, disable
    ├── postrm                         #   daemon-reload (remove); rm install root + user (purge)
    └── perseus-smarthome.service      #   packaged unit (User=perseus-smarthome); drift-checked against deploy/systemd/rpi-io-mcp.service at build time
docs/
└── deployment.md                      # MODIFIED: rewritten around the new flow
```

Removed:

```text
scripts/deploy_rpi_io_mcp.sh           # superseded by remote-install.sh
```

## Resolved Design Decisions

These resolve the Open Questions in `requirements.md`:

### 1. Service user

The script-install path runs the service as the deploy user (continuing
Milestone 1 behavior). The `.deb` path creates a dedicated system user
`perseus-smarthome` (UID dynamic, home `/opt/raspberry-smarthome`, shell
`/usr/sbin/nologin`) in `postinst`. Both users are added to the `gpio`
group.

This divergence is intentional and documented:

- The script path is the natural fit for a single-operator Pi. It avoids
  creating an extra account and matches the verified Milestone 1 setup.
- The `.deb` path follows Debian convention (a service-specific system
  user) so apt installs behave like every other system service on the box.

The two paths should not be mixed on the same Pi (see Cross-Path Coexistence
below).

### 2. systemd `ExecStart`

Switch from:

```ini
ExecStart=/home/pi/.local/bin/uv run --no-dev rpi-io-mcp
```

to:

```ini
ExecStart=/opt/raspberry-smarthome/.venv/bin/rpi-io-mcp
```

Reasoning:

- Removes the dependency on `uv` being on systemd's PATH at runtime.
- Removes the per-user `~/.local/bin` path that forced sed-substitution of
  `/home/pi/` to `/home/<user>/` at install time.
- The `.deb` path bundles the venv at exactly this location; the script
  path runs `uv sync --no-dev` which also populates this location.
- `--no-dev` semantics are now applied at install time
  (`uv sync --no-dev`), not at runtime, which matches what was already
  intended.

The `Environment="PATH=..."` line is dropped from the unit. `User=` becomes
the only variable rewritten at install time.

### 3. systemd unit location

`deploy/systemd/rpi-io-mcp.service` stays put. The `.deb` ships its own copy
under `packaging/debian/perseus-smarthome.service` to keep packaging assets
self-contained, and the build script copies the canonical unit into place
during build to avoid drift. Drift is checked by `make deb` failing if the
two diverge — see Build Process below.

### 4. Cross-path coexistence

Mixing the two paths on the same Pi is **not supported**. Both install to
`/opt/raspberry-smarthome` and both manage `rpi-io-mcp.service`. dpkg has
no knowledge of files placed by the script and the script has no knowledge
of dpkg's database, so a co-installed system can confuse either tool's
uninstall.

Mitigations:

- `scripts/install.sh install` runs
  `dpkg-query -W -f='${Status}' perseus-smarthome 2>/dev/null` and refuses
  if the result starts with `install ok installed`, pointing the operator
  at `apt remove perseus-smarthome` before reinstalling via the script.
- The `.deb` `preinst` runs the same check in reverse: if
  `/opt/raspberry-smarthome` exists but `dpkg-query -W -f='${Status}'
  perseus-smarthome` does not return `install ok installed` (i.e. the
  directory is owned by a script-managed install, not a current package),
  it refuses with a clear error pointing at `make uninstall PURGE=1`.
  Using the parsed `Status` field — not `dpkg-query -L`'s exit code —
  avoids a false positive on a package in the
  removed-but-not-purged (`rc`) state, where `-L` exits non-zero even
  though dpkg still owns the conffiles.

A future iteration may add a documented migration recipe; this iteration
keeps the two paths strictly separate.

## Architecture

```text
                   ┌──────────────────────┐
                   │    Repository tree    │
                   └──────────┬────────────┘
                              │
     ┌────────────────────────┼─────────────────────────────┐
     │                        │                             │
     ▼                        ▼                             ▼
make install           make remote-install              make deb
     │                        │                             │
     ▼                        ▼                             ▼
scripts/install.sh    scripts/remote-install.sh    packaging/build-deb.sh
(local, on Pi)        (on Mac, SSHes to Pi)        (on Pi, produces .deb)
     │                        │                             │
     │             rsync + ssh + invoke install.sh          │
     │                        │                             ▼
     │                        │                       dist/perseus-smarthome_*.deb
     │                        │                             │
     └────────────┬───────────┘                             │
                  │                                         │
                  ▼                                         ▼
        Same end state                                sudo apt install ./dist/*.deb
        (script-managed)                              (dpkg-managed)
```

## Script: `scripts/install.sh`

### Subcommands

```bash
sudo ./scripts/install.sh install [--user <name>]
sudo ./scripts/install.sh upgrade
sudo ./scripts/install.sh uninstall [--purge]
./scripts/install.sh status
```

### Behavior — `install`

Idempotent. Each step is a check-then-act:

1. **Preflight.** Verify root/sudo. Verify host is Debian Trixie (warn but
   continue if not). Resolve the deploy user (default: `SUDO_USER` if set,
   else `pi`, else fail with clear message).
2. **apt prereqs.** Run `apt-get install -y --no-install-recommends
   libffi-dev python3-dev build-essential swig liblgpio-dev` only if any
   are missing (checked via `dpkg -s`).
3. **uv.** If `uv` is not on PATH for the deploy user, install via the
   upstream installer into `~/.local/bin`. Skip if present.
4. **gpio group.** If the deploy user is not in `gpio`, run `usermod -aG
   gpio <user>` and warn that re-login or reboot is required.
5. **Stage source.** Detect whether the script is running inside a checkout
   (typical when invoked locally) or whether the source has been rsynced to
   `/opt/raspberry-smarthome` already (typical when invoked by
   `remote-install.sh`). Copy / rsync the source into
   `/opt/raspberry-smarthome` with `chown -R <user>:gpio`, excluding the
   same paths the existing deploy script excludes (`.git`, `.env`, `.venv`,
   `__pycache__`, `*.pyc`, `.pytest_cache`).
6. **uv sync.** As the deploy user: `cd /opt/raspberry-smarthome && uv sync
   --no-dev`. The resulting `.venv/bin/rpi-io-mcp` is the systemd
   ExecStart target.
7. **Render unit.** `sed "s|^User=pi$|User=<user>|"` of
   `/opt/raspberry-smarthome/deploy/systemd/rpi-io-mcp.service` into
   `/etc/systemd/system/rpi-io-mcp.service`.
8. **Activate.** `systemctl daemon-reload && systemctl enable --now
   rpi-io-mcp.service`.
9. **Verify.** Wait up to 30 seconds for `systemctl is-active` to return
   `active`. Print `status` summary.

### Behavior — `upgrade`

Same as `install` but skips steps 2–4 (apt, uv, gpio) and fails fast if
`/opt/raspberry-smarthome` does not exist or `/etc/systemd/system/rpi-io-mcp.service`
is missing. The user is read from the existing unit file's `User=` line, not
from `--user`.

### Behavior — `uninstall`

1. `systemctl stop rpi-io-mcp.service` (ignore "not loaded").
2. `systemctl disable rpi-io-mcp.service` (ignore "not enabled").
3. `rm -f /etc/systemd/system/rpi-io-mcp.service`.
4. `systemctl daemon-reload`.
5. If `--purge`: `rm -rf /opt/raspberry-smarthome`.

Group membership and apt prereqs are intentionally not removed — they're
shared resources and reverting them would be surprising.

### Behavior — `status`

Read-only. Prints:

- `systemctl is-active rpi-io-mcp.service`
- `systemctl is-enabled rpi-io-mcp.service`
- Version from `/opt/raspberry-smarthome/pyproject.toml::project.version`
  (parsed with awk; tolerates the file being missing).
- Local reachability check:
  `curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:<port>/mcp`
  where `<port>` is read from `config/rpi-io.toml::server.port`
  (currently `8000`). The probe is a TCP-OK probe; HTTP code 405/406 from
  the MCP server is treated as reachable.

### Helpers in `scripts/lib.sh`

- `log "step description"` → `printf '==> %s\n' "$*"`.
- `die "msg"` → log to stderr and exit 1.
- `require_root` → ensure UID 0 or re-exec under sudo with confirmation.
- `apt_missing pkg ...` → echo only the packages not currently installed.

## Wrapper: `scripts/remote-install.sh`

Mac-side. Reads `.env`. Subcommands match `install.sh`:

```bash
./scripts/remote-install.sh install
./scripts/remote-install.sh upgrade
./scripts/remote-install.sh uninstall [--purge]
./scripts/remote-install.sh status
```

Steps:

1. Source `.env`. Default `RPI_SSH_*` values match the existing
   `deploy_rpi_io_mcp.sh`.
2. Build the SSH option array exactly as the existing deploy script does
   (port, optional key, `StrictHostKeyChecking=accept-new`).
3. For `install`/`upgrade`: rsync the working tree to
   `/opt/raspberry-smarthome` on the Pi (same exclude list), then SSH and
   run `sudo /opt/raspberry-smarthome/scripts/install.sh <subcommand>
   --user <RPI_SSH_USER>`. The `--user` flag pins the deploy user so the
   Pi-side default lookup does not surprise.
4. For `uninstall` and `status`: SSH only. No rsync.
5. Stream remote stdout/stderr to the Mac terminal so the operator sees the
   `==>` log lines as they happen.

The legacy `scripts/deploy_rpi_io_mcp.sh` is removed in the same change.
The README/docs link to the new entrypoint.

## Debian Package

### `packaging/debian/control`

```text
Package: perseus-smarthome
Version: 0.1.0
Section: misc
Priority: optional
Architecture: armhf
Maintainer: <maintainer-name-and-email>
Depends: liblgpio1, libffi8, adduser, systemd, libc6, python3 (>= 3.13)
Description: Raspberry Pi I/O MCP Server
 Hardware-facing MCP server that exposes configured GPIO outputs and
 inputs over streamable HTTP on the trusted LAN. Bundles a prebuilt
 Python virtualenv at /opt/raspberry-smarthome/.venv so installs are
 self-contained.
```

The `Maintainer:` field is filled in at build time by `build-deb.sh`,
which reads it from `git config user.name`/`git config user.email` (or a
`DEB_MAINTAINER` env override) on the build host. Keeping the placeholder
here avoids embedding a personal address in the spec.

Concrete `Depends:` versions are pinned during the first build run on a
real Pi (where `apt-cache policy` is the source of truth). The values
above are the working draft — the build script asserts them at build time
against the host's apt index and fails if they cannot be satisfied.

### `packaging/debian/conffiles`

```text
/opt/raspberry-smarthome/config/rpi-io.toml
```

So apt does not silently overwrite a Pi-local edit on upgrade.

### `packaging/debian/preinst`

```bash
#!/bin/sh
set -e
# Refuse to install on top of a script-managed install.
# `dpkg-query -W -f='${Status}'` parses dpkg's own state record, so it
# returns `install ok installed` only for a currently-installed package
# (not for `rc` removed-but-not-purged, which would falsely look like a
# script-managed install if we used `dpkg-query -L`'s exit code instead).
if [ -d /opt/raspberry-smarthome ]; then
  pkg_status=$(dpkg-query -W -f='${Status}' perseus-smarthome 2>/dev/null || true)
  case "$pkg_status" in
    "install ok installed") : ;;
    *)
      echo "Found a non-package install at /opt/raspberry-smarthome." >&2
      echo "Run 'sudo make uninstall PURGE=1' first, then retry." >&2
      exit 1
      ;;
  esac
fi
```

### `packaging/debian/postinst`

```bash
#!/bin/sh
set -e
case "$1" in
  configure)
    # Create system user if missing.
    if ! getent passwd perseus-smarthome >/dev/null; then
      adduser --system --group --home /opt/raspberry-smarthome \
              --shell /usr/sbin/nologin --no-create-home \
              perseus-smarthome
    fi
    # Add to gpio for /dev/gpio* access.
    if ! id -nG perseus-smarthome | grep -qw gpio; then
      usermod -aG gpio perseus-smarthome
    fi
    chown -R perseus-smarthome:gpio /opt/raspberry-smarthome
    systemctl daemon-reload
    systemctl enable --now rpi-io-mcp.service
    ;;
esac
```

### `packaging/debian/prerm`

```bash
#!/bin/sh
set -e
case "$1" in
  remove|upgrade|deconfigure)
    if systemctl is-active --quiet rpi-io-mcp.service; then
      systemctl stop rpi-io-mcp.service
    fi
    if systemctl is-enabled --quiet rpi-io-mcp.service; then
      systemctl disable rpi-io-mcp.service
    fi
    ;;
esac
```

### `packaging/debian/postrm`

```bash
#!/bin/sh
set -e
case "$1" in
  remove)
    systemctl daemon-reload || true
    ;;
  purge)
    systemctl daemon-reload || true
    rm -rf /opt/raspberry-smarthome
    if getent passwd perseus-smarthome >/dev/null; then
      deluser --system perseus-smarthome >/dev/null 2>&1 || true
    fi
    ;;
esac
```

### Build process — `packaging/build-deb.sh`

Run on a Pi 2 (armv7l). Steps:

1. Read version from `pyproject.toml`.
2. Drift check: assert
   `packaging/debian/perseus-smarthome.service ==
   deploy/systemd/rpi-io-mcp.service` (post-User-substitution); fail
   `make deb` if they differ. The packaging copy uses
   `User=perseus-smarthome` whereas the canonical unit uses `User=pi`, so
   the comparison is on the rendered form.
3. Stage:

   ```text
   _build/perseus-smarthome_<version>_armhf/
   ├── DEBIAN/
   │   ├── control
   │   ├── conffiles
   │   ├── preinst
   │   ├── postinst
   │   ├── prerm
   │   └── postrm
   ├── etc/systemd/system/rpi-io-mcp.service
   └── opt/raspberry-smarthome/
       ├── .venv/                          # built by `uv sync --no-dev`
       ├── config/rpi-io.toml
       ├── pyproject.toml
       ├── src/perseus_smarthome/...
       ├── tools/...
       └── deploy/systemd/rpi-io-mcp.service   # canonical reference copy
   ```

4. Permissions: maintainer scripts `chmod 0755`.
5. `dpkg-deb --build --root-owner-group _build/perseus-smarthome_<version>_armhf
   dist/`.
6. Print `dpkg-deb -I` and `dpkg-deb -c` of the output for inspection.

## Makefile

```make
SHELL := /bin/bash
.DEFAULT_GOAL := help

help:                ## Print this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / \
	  {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:             ## Script install on this host (idempotent)
	sudo ./scripts/install.sh install

upgrade:             ## Re-deploy code and restart the service on this host
	sudo ./scripts/install.sh upgrade

uninstall:           ## Stop service, remove unit. Use PURGE=1 to also remove /opt/raspberry-smarthome
	sudo ./scripts/install.sh uninstall $(if $(PURGE),--purge,)

status:              ## Print service status and reachability
	./scripts/install.sh status

remote-install:      ## Run install over SSH from this Mac (uses .env)
	./scripts/remote-install.sh install

remote-upgrade:      ## Run upgrade over SSH from this Mac (uses .env)
	./scripts/remote-install.sh upgrade

remote-uninstall:    ## Run uninstall over SSH. Use PURGE=1 to also wipe /opt/raspberry-smarthome
	./scripts/remote-install.sh uninstall $(if $(PURGE),--purge,)

remote-status:       ## Print remote service status (uses .env)
	./scripts/remote-install.sh status

deb:                 ## Build .deb (must run on armv7l Pi)
	./packaging/build-deb.sh

deb-install:         ## apt install the most recent built .deb
	sudo apt install -y ./dist/perseus-smarthome_*_armhf.deb

deb-uninstall:       ## apt remove the package (keeps config)
	sudo apt remove -y perseus-smarthome

deb-purge:           ## apt purge the package (removes /opt/raspberry-smarthome)
	sudo apt purge -y perseus-smarthome

clean:               ## Remove build artifacts
	rm -rf _build dist

test:                ## Run unit tests (excluding e2e and hardware)
	uv run pytest -m "not e2e and not hardware"

.PHONY: help install upgrade uninstall status \
        remote-install remote-upgrade remote-uninstall remote-status \
        deb deb-install deb-uninstall deb-purge clean test
```

## Safety Properties

- GPIO23 safe-default is unchanged. The service implementation
  (`src/perseus_smarthome/service.py`) drives GPIO23 low at startup and at
  shutdown; this is independent of how the service was installed.
- `enable --now` semantics in both `postinst` and `install.sh` match
  Milestone 1 reboot persistence.
- The `.deb` does not run any GPIO operations during install; only the
  service does, after systemd starts it.
- No path in this design widens network exposure or adds a new listener.
  The service still binds to `0.0.0.0:8000` on the trusted LAN; that is
  unchanged.

## Error Model

- Bash scripts use `set -euo pipefail`. Each step is wrapped with a `log`
  line so the journal/terminal trace is readable.
- Unrecoverable errors call `die "<message>"` from `lib.sh`, which prints
  to stderr and exits 1. The message must name the failed step and a
  remediation hint.
- Maintainer scripts (`postinst` etc.) use `set -e` and follow the
  `case "$1" in configure|remove|purge ...)` Debian convention so dpkg
  retries are well-defined.
- The build script (`build-deb.sh`) fails fast on drift between the
  packaged unit and the canonical unit.

## Tests

Unit-test-able pieces:

- `scripts/lib.sh::apt_missing` — pure bash function; cover with a
  `tests/scripts/test_install_lib.bats` (or shell-only smoke runner if
  bats is rejected).
- `packaging/build-deb.sh` drift check — invoke with mocked unit files
  and assert exit code.

Integration tests (gated on hardware availability, not run in CI):

- Fresh-install on a clean Trixie image.
- Re-install idempotency.
- Uninstall with and without `--purge`.
- Deb install, remove, purge cycle.
- Reboot persistence after each path.
- Existing E2E suite passes after install via each path.

CI tests:

- `make test` continues to run `uv run pytest -m "not e2e and not hardware"`.
- Optionally add a `make lint` later that runs `shellcheck` over the
  scripts; not required for this iteration.

Manual operator checks:

- `make help` prints all targets.
- `make remote-install` from a fresh checkout on a fresh Pi reaches the
  active state in under five minutes (excluding the first armv7l source
  build of `lgpio` which is dominated by I/O on Pi 2).

## Open Questions

None blocking. Possible follow-ups for a later iteration:

- Publish a public apt repository (out of scope here).
- Add `cross-deb` build via a Docker armv7l container on the Mac (out of
  scope here; build host is the Pi for now).
- Automate version bumping in `packaging/debian/changelog` from
  `pyproject.toml`.

## Change Log

- 2026-05-01: Initial draft. Resolves the four `requirements.md` open
  questions (service-user model: divergent by design; ExecStart: switch to
  venv console script; unit location: keep canonical at
  `deploy/systemd/`; cross-path coexistence: not supported, with refusal
  guards on both sides). Pending owner approval.
- 2026-05-01: Owner approved. Status flipped from Draft to Approved.
  Implementation begins under issues `#43`–`#48`.
- 2026-05-01: Spec-PR review punch-list landed inline (no implementation
  changes): preinst guard switched from `dpkg-query -L` to
  `dpkg-query -W -f='${Status}'` so the `rc` (removed-not-purged) state
  no longer falsely trips the script-vs-deb guard; File Layout now lists
  the packaged `perseus-smarthome.service` and the `preinst` script;
  Cross-Path Coexistence prose reconciled with the snippet; status-probe
  port read from `config/rpi-io.toml::server.port`; `Maintainer:` field
  in `control` made a build-time placeholder so personal contact details
  do not live in the spec.
