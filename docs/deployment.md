# Deployment Guide — Raspberry Pi I/O MCP Server

This guide covers installing and managing the `rpi-io-mcp` systemd service on
Raspberry Pi OS Lite 32-bit (Debian Trixie).

Hardware target: Raspberry Pi 2.  
Service user: `pi` (must be in the `gpio` group).  
Project directory on Pi: `/opt/raspberry-smarthome` (or the value of
`RPI_PROJECT_DIR` in your local `.env`).

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

3. Ensure the `pi` user is in the `gpio` group (usually true by default):

   ```bash
   groups pi   # should include gpio
   # If not:
   sudo usermod -aG gpio pi
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

# 4. On the Pi: install the systemd unit
sudo cp deploy/systemd/rpi-io-mcp.service /etc/systemd/system/rpi-io-mcp.service
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

# Full E2E test suite
RPI_MCP_URL=http://raspberrypi.local:8000/mcp uv run pytest tests/e2e/test_rpi_io_mcp.py
```

Replace `raspberrypi.local` with the Pi's IP address if mDNS is not available.

## Safety Notes

- GPIO23 is reset to **low/off** automatically every time the service process
  starts — on initial install, on restart after failure, and on boot after
  reboot. This is handled by `GPIOService.__init__` (see
  `src/perseus_smarthome/service.py`) which sets the pin low before the MCP
  server begins accepting requests. Satisfies IO-MCP-FR-015.
- GPIO24 is input-only; the service never drives it.
- The service binds on `0.0.0.0:8000`. Keep the Raspberry Pi on a trusted LAN
  segment. No authentication is required or provided in Milestone 1.
- Never commit `.env`, SSH keys, or any real secrets to the repository.
