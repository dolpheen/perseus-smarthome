# Deployment Guide — Raspberry Pi I/O MCP Server

This guide covers installing and managing the `rpi-io-mcp` systemd service on
Raspberry Pi OS Lite 32-bit (Debian Trixie).

Hardware target: Raspberry Pi 2.  
Service user: `RPI_SSH_USER` from `.env` (default `pi`; must be in the `gpio`
group). The repo's unit file uses `pi` as the canonical Raspbian default, and
`scripts/deploy_rpi_io_mcp.sh` rewrites `User=` and `/home/pi/` paths to match
`RPI_SSH_USER` at install time so a Pi with a custom primary user (e.g.
`perseus`) works without editing the unit by hand.  
Project directory on Pi: `/opt/raspberry-smarthome` (fixed; not configurable via
`RPI_PROJECT_DIR` so the systemd unit, deploy script, and docs all agree without
runtime templating of paths).

## Prerequisites

### On the Raspberry Pi

1. Install build dependencies required by native packages (`cffi`, `lgpio`):

   ```bash
   sudo apt install -y libffi-dev python3-dev build-essential
   ```

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

### Option A — Automated deploy script

```bash
# From the repository root on your MacBook:
./scripts/deploy_rpi_io_mcp.sh
```

The script reads `.env`, syncs the project to the Pi, runs `uv sync --no-dev`,
copies the systemd unit, enables, and starts the service.

### Option B — Manual steps

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

# 4. On the Pi: install the systemd unit (rewriting User= and /home/pi/
#    to match the actual user when the deploy user isn't `pi`)
sudo sed \
    -e "s|^User=pi$|User=$USER|" \
    -e "s|/home/pi/|/home/$USER/|g" \
    deploy/systemd/rpi-io-mcp.service \
    | sudo tee /etc/systemd/system/rpi-io-mcp.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable rpi-io-mcp.service
sudo systemctl start rpi-io-mcp.service
```

## Update (re-deploy after code changes)

Run the deploy script again — it syncs changed files, updates dependencies, and
restarts the service:

```bash
./scripts/deploy_rpi_io_mcp.sh
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
