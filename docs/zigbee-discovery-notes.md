# Zigbee / CC2531 Discovery Notes (Phase 0)

Status: Discovery (pre-spec)
Last reviewed: 2026-05-01
Owner: Vadim
Successor: `specs/features/cc2531-zigbee-mcp/` (Phase 1, not yet created)

## Purpose

Pre-spec discovery scaffold for the next milestone (CC2531/Zigbee MCP). Three
outcomes must be locked before Phase 1 SDD work begins:

1. **Decision A — firmware:** CC2531 confirmed running Z-Stack 3.x.0 coordinator
   firmware (date-stamped version recorded).
2. **Decision B — stack:** one of {Zigbee2MQTT, zigpy-znp, ZHA} chosen with
   written rationale.
3. **Demo:** Orvibo PIR motion sensor paired against the chosen stack; ≥3
   motion ON/OFF transitions captured with timestamps; sensor re-joins
   automatically across coordinator restart.

Time-box: ~2 sessions. If firmware flashing blocks, escalate before continuing.

This document is **discovery scaffolding**, not an SDD spec. It does not
replace `specs/features/cc2531-zigbee-mcp/`, which opens in Phase 1 once the
decisions above are locked.

## Execution model

All Phase 0 issues are worked by a coding agent running on the local MacBook,
with SSH access to the Raspberry Pi over the same LAN (existing
`.env::RPI_SSH_*` configuration; same connection `scripts/remote-install.sh`
already proves). The agent can:

- Read/write files in this repo.
- SSH to the Pi and run probes, flashers, pairing harnesses.
- Capture stdout/stderr from the Pi back to the issue.
- Verify outcomes with the Pi over SSH.

Physical bench actions remain operator-only:

- Wiring jumpers from Pi GPIOs to the CC2531 debug header (one-time, only for
  the Pi-GPIO flash path).
- Plugging in a CC Debugger (CC Debugger flash path only).
- Reading model numbers off physical labels.
- Pressing the Orvibo pairing button.
- Triggering motion in front of the PIR sensor.

Issues that require any of those bench actions for acceptance carry the
`needs-manual-verification` label so the auto-merge gate does not close them
on agent output alone.

## Out of scope for Phase 0

- Any code under `src/perseus_smarthome/`.
- Any spec edits beyond a single answer to `specs/project.spec.md` Open
  Question #2 (state persistence), captured in the Phase 0 closeout issue.
- The MCP wrapper itself.

## Steps and tracking issues

| Step | Title | Blocked by | Bench action |
|---|---|---|---|
| 0 | CC2531 + Orvibo bench prep (#59) | — | read sensor label |
| 1 | Flash CC2531 with Z-Stack 3.x.0 firmware (#60) | #59 | wire jumpers / plug CC Debugger |
| 2 | Stack selection — Z2M vs zigpy-znp vs ZHA (#61) | — | review & accept recommendation |
| 3 | Orvibo pairing & motion proof-of-life (#62) | #60, #61 | press pairing button; trigger motion |
| 4 | Capture Phase 0 outputs (#63) | #59, #60, #61, #62 | review writeup |
| Final | Lock decisions for Phase 1 spec (#64) | #63 | owner sign-off |

Cross-issue dependencies are tracked via text-only "Blocked by:" notes,
matching the existing repo convention (native issue Relationships are not
configured here).

## Step 0 — Bench prep

Goals:

- `lsusb` shows TI CC2531 (USB IDs `0451:16a8`).
- `/dev/ttyACM*` device present.
- Orvibo sensor model + pairing procedure recorded from the physical label.

Output: bench probe under `tools/`; agent SSHs to the Pi, runs it, and pastes
the structured output into the issue. Operator confirms the Orvibo model +
pairing procedure from the sensor label.

## Step 1 — Firmware flash

Source: `Koenkk/Z-Stack-firmware` →
`coordinator/Z-Stack_3.x.0/bin/CC2531/CC2531_DEFAULT_*.zip` →
`CC2531ZNP-Prod.hex` (record the date-stamped filename).

Two flashing paths:

- **CC Debugger + cc-tool** (via Mac USB or Pi USB): most reliable; requires
  extra hardware (~$50). Once the CC Debugger is plugged in, the agent runs
  `cc-tool` locally on the host with the CC Debugger attached.
- **Pi GPIO + CC2531-flasher**: no extra hardware; requires four jumpers
  (DD/DC/RESET/GND) from Pi GPIOs to the CC2531 debug header. Once wired, the
  agent SSHs to the Pi and runs `cc2531-flasher` end-to-end.

**GPIO conflict warning (Pi-GPIO path):** GPIO23/24 are already in use by the
running `rpi-io-mcp.service`. Either configure the flasher to use other BCM
pins, or stop the service and disconnect the GPIO23/24 wiring before flashing.
The agent must verify `rpi-io-mcp` is stopped before initiating any flash via
the Pi-GPIO path; verify it restarts cleanly afterward.

Acceptance: a Z-Stack coordinator probe (added in this step) reaches init
without "not a coordinator" / version-mismatch errors.

## Step 2 — Stack selection

Evaluate against current upstream docs:

| Criterion | Zigbee2MQTT + Mosquitto | zigpy-znp (in-process) | HA ZHA |
|---|---|---|---|
| Orvibo PIR support | confirmed for many models | via zigpy quirks | confirmed |
| Services added on Pi | `mosquitto`, `zigbee2mqtt` (Node) | none (Python lib) | full HA |
| Event delivery | MQTT topic | Python callback / async | HA event bus |
| Persistence | `data/database.db`, `coordinator_backup.json` | sqlite via zigpy | HA db |
| Trust-LAN impact | new MQTT port on the LAN | none | full HA exposure |
| Fits one-systemd-service deploy | adds 2 units | yes | no |
| Maintenance | very high | high (smaller community) | tied to HA cadence |

Lean recommendation: **zigpy-znp**. Preserves the trusted-LAN posture, keeps
the deployment story (one systemd service) and packaging path (.deb still
self-contained) intact. Switch to Z2M only if device coverage proves
insufficient.

This is a placeholder; the live decision is made in the Step 2 issue and
recorded in the Phase 0 closeout.

## Step 3 — Proof-of-life

Pair Orvibo via the chosen stack. Capture:

- IEEE address.
- Model identifier, manufacturer string.
- Exposed clusters / attributes / command set.
- ≥3 motion ON/OFF transitions with timestamps.
- Re-join across coordinator power-cycle (`ssh pi@... sudo systemctl restart …`
  or `sudo reboot`, depending on the chosen stack's lifecycle).

Throwaway harness under `tools/`; explicitly not the production path. Will be
deleted or absorbed into `src/` once Phase 1 specs land.

## Step 4 — Capture outputs

Synthesize results into `docs/zigbee-discovery-results.md`:

1. Firmware version + flash recipe.
2. Chosen stack + rationale (the comparison table with real findings, not the
   placeholder above).
3. Orvibo runtime surface (clusters, attributes, message cadence).
4. Persistence requirements: which files/DBs the stack creates, where they
   live, what `apt purge` should remove vs. preserve.
5. Event-delivery model the MCP layer must wrap (poll-on-call vs. cached
   last-known vs. MCP notifications).
6. Trusted-LAN delta (new ports? new services?).
7. Open questions for Phase 1 spec.

This step forces an explicit answer to `specs/project.spec.md` Open Question
#2 (state persistence), which has been deferred since project intake.

## Final — Decision lock

Owner-approved record of:

- Chosen stack.
- Firmware version (filename + date stamp).
- Persistence approach.
- Trusted-LAN delta.

A small PR adds the Open Question #2 answer to `specs/project.spec.md` and
drafts the `Source Material Reviewed` paragraph that Phase 1's
`requirements.md` will cite. Phase 1
(`specs/features/cc2531-zigbee-mcp/{requirements,design,tasks}.md`) opens
after this lock.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Flashing bricks the stick | Time-box; if the second attempt fails, pause and consult docs / order a CC Debugger. |
| Pi-GPIO flasher conflicts with `rpi-io-mcp` GPIO23/24 | Stop the service before flashing, or use other BCM pins for the flasher. Verify the service restarts cleanly after. |
| Orvibo model not in the chosen stack's device DB | zigpy quirks repo; or fall back to the alternative stack. |
| zigpy-znp turns out too sparse for richer future devices | Document Z2M migration as a follow-up; rationale already captured. |
| CC2531 routing limits at scale | Flag as a future risk; CC2652 stick is the modern path. Not a Phase 0 blocker. |
| MQTT broker (if Z2M) opens the trusted-LAN attack surface | Decide explicitly in Step 2 before adopting Z2M; document in the trusted-LAN delta. |
