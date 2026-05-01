# Deployment Guide — Raspberry Pi I/O MCP Server

This guide covers installing and managing the `rpi-io-mcp` systemd service on
Raspberry Pi OS Lite 32-bit (Debian Trixie).

Hardware target: Raspberry Pi 2.  
Service user: `RPI_SSH_USER` from `.env` (default `pi`; must be in the `gpio`
group). The repo's unit file uses `pi` as the canonical Raspbian default, and
`scripts/remote-install.sh` passes `--user "$RPI_SSH_USER"` to
`scripts/install.sh` on the Pi, which rewrites `User=` to match at install time
so a Pi with a custom primary user (e.g. `perseus`) works without editing the
unit by hand.  
Project directory on Pi: `/opt/raspberry-smarthome` (fixed; not configurable via
`RPI_PROJECT_DIR` so the systemd unit, install scripts, and docs all agree
without runtime templating of paths).

## Prerequisites

### On the Raspberry Pi

1. Install build dependencies required by native packages (`cffi`, `lgpio`):

   ```bash
   sudo apt install -y libffi-dev python3-dev build-essential swig liblgpio-dev
   ```

   `swig` is the codegen step in the `lgpio` source build; `liblgpio-dev`
   provides the C library + headers it links against. Skipping either one
   causes `uv sync` to fail with a swig-not-found or `cannot find -llgpio`
   error during the lgpio build on armv7l.

2. Install `uv`:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   # or: pip install uv
   ```

3. Ensure the deploy user (the one in `RPI_SSH_USER`, default `pi`) is in the
   `gpio` group:

   ```bash
   groups "$USER"   # should include gpio
   # If not:
   sudo usermod -aG gpio "$USER"
   # Log out and back in, or reboot, to apply.
   ```

### On the MacBook (deploy machine)

- SSH access to the Pi configured via `~/.ssh/config` or key path in `.env`.
- `rsync` available (`brew install rsync` if needed).
- A local `.env` file with Raspberry Pi connection details (see `.env.example`).

## First Install

### Option A — Automated remote-install (recommended)

Run `make help` to see all available targets:

```bash
make help
```

The primary operator workflow uses `make` targets that delegate to
`scripts/remote-install.sh`:

```bash
make remote-install          # first install
make remote-upgrade          # re-sync and restart after code changes
make remote-status           # print remote service status
make remote-uninstall        # stop/disable service and remove systemd unit
make remote-uninstall PURGE=1  # also removes /opt/raspberry-smarthome
```

`make remote-install` and `make remote-upgrade` read `.env`, rsync the project
to `/opt/raspberry-smarthome` on the Pi, then SSH and run
`sudo scripts/install.sh <subcommand>`. `make remote-status` and
`make remote-uninstall` SSH directly without rsyncing first (no file transfer
needed).

You can also invoke the script directly when `make` is not available:

```bash
./scripts/remote-install.sh install
./scripts/remote-install.sh upgrade
./scripts/remote-install.sh status
./scripts/remote-install.sh uninstall
./scripts/remote-install.sh uninstall --purge
```

### Option B — Debian package (`apt install`)

The `.deb` is built on the Pi (armv7l) and bundles a self-contained venv,
so installs are atomic and need no source build at install time. The
service runs as a dedicated system user `perseus-smarthome` (created by
`postinst`) instead of the deploy user — see
`specs/features/deployment/design.md::Resolved Design Decisions::1`.

Mixing the deb path and the script path on the same Pi is unsupported
(both manage `/opt/raspberry-smarthome` and the same systemd unit); the
preinst and `scripts/install.sh` refuse with a clear error if the other
path's install is detected.

```bash
# On the Pi (or any armv7l host with a checkout):
make deb                                  # produces dist/perseus-smarthome_<ver>_armhf.deb
sudo apt install -y ./dist/perseus-smarthome_<ver>_armhf.deb

# Subsequent management uses standard apt verbs:
sudo apt remove perseus-smarthome         # stop service, remove unit; keep /opt/raspberry-smarthome
sudo apt purge perseus-smarthome          # also remove install root and the perseus-smarthome user
```

`make deb-install`, `make deb-uninstall`, and `make deb-purge` are thin
wrappers; `deb-install` resolves the latest built `.deb` so `dist/` may
hold multiple versions safely.

The build script reads the maintainer identity from `git config user.name`
/ `git config user.email` (or a `DEB_MAINTAINER` env override), and
checks the `Depends:` packages against the build host's apt index before
packaging. `pyproject.toml`'s version drives the artifact name.

### Option C — Manual steps

```bash
# 1. Sync the project to the Pi
rsync -az --delete \
  --exclude=".git" --exclude=".env" --exclude=".venv" \
  ./ pi@raspberrypi.local:/opt/raspberry-smarthome/

# 2. SSH into the Pi
ssh pi@raspberrypi.local

# 3. On the Pi: install dependencies
cd /opt/raspberry-smarthome
uv sync --no-dev

# 4. On the Pi: install the systemd unit (rewriting User= when the
#    deploy user isn't `pi`)
sudo sed \
    -e "s|^User=pi$|User=$USER|" \
    deploy/systemd/rpi-io-mcp.service \
    | sudo tee /etc/systemd/system/rpi-io-mcp.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable rpi-io-mcp.service
sudo systemctl start rpi-io-mcp.service
```

## Update (re-deploy after code changes)

Run the upgrade target — it syncs changed files, updates dependencies, and
restarts the service:

```bash
make remote-upgrade
```

Or invoke the script directly:

```bash
./scripts/remote-install.sh upgrade
```

Or manually on the Pi:

```bash
cd /opt/raspberry-smarthome
git pull  # or rsync from MacBook
uv sync --no-dev
sudo systemctl restart rpi-io-mcp.service
```

## Service Management

All commands run on the Raspberry Pi (or over SSH):

### Check service status

```bash
sudo systemctl status rpi-io-mcp.service
```

### Start / stop / restart

```bash
sudo systemctl start rpi-io-mcp.service
sudo systemctl stop rpi-io-mcp.service
sudo systemctl restart rpi-io-mcp.service
```

### Enable / disable autostart on boot

```bash
sudo systemctl enable rpi-io-mcp.service   # start on boot
sudo systemctl disable rpi-io-mcp.service  # do not start on boot
```

### View logs (journald)

```bash
# Follow live logs
sudo journalctl -u rpi-io-mcp.service -f

# Show the last 100 lines
sudo journalctl -u rpi-io-mcp.service -n 100

# Show logs since the last boot
sudo journalctl -u rpi-io-mcp.service -b
```

## Verifying the Endpoint

From the MacBook, after the service is running:

```bash
# Quick health check (requires curl)
curl http://raspberrypi.local:8000/mcp

# Full E2E test suite (requires issue #6 branch to be merged)
RPI_MCP_URL=http://raspberrypi.local:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py
```

Replace `raspberrypi.local` with the Pi's IP address if mDNS is not available.

## Safety Notes

- GPIO23 is reset to **low/off** automatically every time the service process
  starts — on initial install, on restart after failure, and on boot after
  reboot. This is handled by `GPIOService.__init__` (see
  `src/perseus_smarthome/service.py`) which sets the pin low before the MCP
  server begins accepting requests. Satisfies IO-MCP-FR-015.
- When systemd stops or restarts the service (`systemctl stop/restart`), it
  sends SIGTERM. `server.py:main()` installs a SIGTERM handler that raises
  `SystemExit(0)`, which propagates through the `try/finally` block and
  ensures `service.close()` drives GPIO23 low before the process exits
  (design.md Safety Rules).
- GPIO24 is input-only; the service never drives it.
- The service binds on `0.0.0.0:8000`. Keep the Raspberry Pi on a trusted LAN
  segment. No authentication is required or provided in Milestone 1.
- Never commit `.env`, SSH keys, or any real secrets to the repository.
