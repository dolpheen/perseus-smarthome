# Manual GPIO and Codex MCP Smoke Tests

Walk-through guides for verifying `rpi-io-mcp` against real hardware on the
Raspberry Pi. These complement the deterministic MacBook E2E suite (the
pytest E2E module under `tests/e2e/`, landing alongside this doc as part of
Milestone 1):

- The E2E suite proves the MCP contract over the wire.
- The smoke tests prove the wired hardware path — GPIO voltages, LED
  illumination, relay click, switch press, and Codex client integration —
  which the E2E suite cannot check on its own.

Both should pass before declaring a Milestone 1 deployment fully verified.
Maps to `IO-MCP-FR-012` (output smoke) and `IO-MCP-FR-013` (input smoke) in
`specs/features/rpi-io-mcp/requirements.md`.

## Prerequisites

- `rpi-io-mcp` already running on the Pi (deploy guide in `docs/deployment.md`
  ships alongside this doc as part of Milestone 1; for a one-off
  verification before that lands, start the server by hand on the Pi with
  `cd /path/to/repo && uv run rpi-io-mcp`).
- Endpoint reachable from MacBook at `http://<pi>:8000/mcp`.
- Export the URL once for this shell:

  ```bash
  export RPI_MCP_URL=http://<pi>:8000/mcp
  ```

Output and input smoke each have multiple wiring variants — pick **one
output variant** (multimeter / LED / relay) and **one input variant**
(multimeter / push-button) based on the parts you have on hand. The Codex
client smoke is its own check and should be run in addition once the
output and input paths verify. See "[What 'passing' means](#what-passing-means-for-milestone-1)"
for the per-criterion checklist.

## Multimeter protocol (no extra wiring)

`tools/smoke_meter.py` runs an interactive 5-step verification using a
multimeter and the live MCP endpoint.

```bash
RPI_MCP_URL=http://<pi>:8000/mcp uv run python tools/smoke_meter.py
```

The five steps:

1. **GPIO23 → LOW** — drives output to 0; red probe on physical pin 16, black
   on any GND pin. Expect ≈ 0 V.
2. **GPIO23 → HIGH** — drives output to 1; same probes. Expect ≈ 3.3 V.
3. **GPIO24 floating** — disconnect any wire; `read_input` returns `0` via
   the internal pull-down.
4. **GPIO24 bridged to 3V3** — wire BCM24 (physical 18) briefly to a 3V3
   rail (physical 1 or 17, **never** physical 2 or 4 which are 5 V); the
   script polls `read_input` and expects `1`.
5. **GPIO24 disconnected** — remove the bridge; `read_input` falls back to
   `0`.

Each step prompts y/n with optional notes, and the final summary prints a
pass/fail table. Safe defaults are restored between steps.

## LED output smoke (GPIO23)

Wiring:

- BCM23 (physical pin 16) → 220 Ω – 1 kΩ resistor → LED anode → LED cathode →
  GND (any GND header pin).
- The series resistor is **mandatory** — it limits LED current and protects
  the GPIO driver. Do not connect an LED directly between BCM23 and GND.

Toggle from the MacBook:

```bash
RPI_MCP_URL=http://<pi>:8000/mcp uv run python -c "
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
    async with streamablehttp_client(os.environ['RPI_MCP_URL']) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for v in (1, 0, 1, 0):
                res = await s.call_tool('set_output', {'device_id': 'gpio23_output', 'value': v})
                print(res.structuredContent)
                await asyncio.sleep(0.5)
asyncio.run(main())
"
```

Expected: LED illuminates on `value=1`, extinguishes on `value=0`. The script
ends with the LED off.

## Relay output smoke (GPIO23)

⚠️ **Use a relay module or driver circuit — never a bare relay coil.** The
inductive kick from a coil exceeds the per-pin spec and will damage the
driver.

Wiring (3.3V-compatible relay module):

- Module `VCC` → Pi 3V3 (physical pin 1 or 17). Verify the module accepts
  3.3 V; some require 5 V and will not switch reliably from 3.3 V.
- Module `GND` → any Pi GND.
- Module `IN` → BCM23 (physical pin 16).

Toggle with the same Python snippet from the LED section. Listen for the
relay click on each transition. Some active-low modules invert the signal —
"on" may correspond to `value=0`. Observe behavior and document expected
polarity for the specific module if it differs.

## Input smoke (GPIO24)

⚠️ **Never connect a 5 V rail to BCM24.** Pi GPIO inputs are 3.3 V tolerant;
5 V damages the SoC.

Wiring (manual input drive with push-button):

- One side of switch → BCM24 (physical pin 18).
- Other side of switch → 3V3 (physical pin 1 or 17).
- Internal pull-down on BCM24 keeps the input low when the switch is open;
  no external pull-down required.

Read from the MacBook (poll while pressing/releasing):

```bash
RPI_MCP_URL=http://<pi>:8000/mcp uv run python -c "
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
    async with streamablehttp_client(os.environ['RPI_MCP_URL']) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for _ in range(20):
                res = await s.call_tool('read_input', {'device_id': 'gpio24_input'})
                print(res.structuredContent)
                await asyncio.sleep(0.5)
asyncio.run(main())
"
```

Expected: `value: 1` while the switch is pressed, `value: 0` when released.

## Codex MCP client smoke

Verifies that the live endpoint is discoverable from a real MCP client.

Register the endpoint with Codex:

```bash
codex mcp add rpi-io --url http://<pi>:8000/mcp
codex mcp list
codex mcp get rpi-io
```

`codex mcp list` should show `rpi-io`; `codex mcp get rpi-io` should print
the URL and a healthy status.

⚠️ **Start a new Codex session before testing the tools.** Codex clients do
not pick up newly-registered MCP servers in the middle of an existing
session — the tool list is snapshotted at session start.

In the new session, ask Codex to call the I/O tools, e.g. "List the GPIO
devices on rpi-io" or "Turn on the GPIO23 output, then turn it off". Codex
should report the configured devices and successfully toggle GPIO23. This
exercises the same MCP transport + tools the E2E suite tests, but through
an LLM-driven client rather than a pytest fixture.

## What "passing" means for Milestone 1

- The deterministic E2E suite is green against the live endpoint:
  `RPI_MCP_URL=http://<pi>:8000/mcp uv run pytest tests/e2e/ --run-hardware`
  (the suite and the `--run-hardware` opt-in are added under Milestone 1).
- At least one of the output smoke paths (multimeter, LED, or relay) shows
  GPIO23 toggling under MCP control.
- At least one of the input smoke paths (multimeter or push-button) shows
  GPIO24 reads tracking the wired state.
- The Codex client smoke succeeds — the registered endpoint is reachable
  and a fresh Codex session can list and call the tools.

When all four are signed off, the Milestone 1 acceptance criteria from
`specs/features/rpi-io-mcp/requirements.md` (FR-001 through FR-013) are
verified end-to-end.
