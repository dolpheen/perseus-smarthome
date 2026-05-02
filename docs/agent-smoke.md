# Manual LLM Agent Smoke Tests — Phase A

Walk-through for verifying the Phase A LLM chat agent against real hardware
on the Pi. Companion to:

- [`docs/manual-smoke-tests.md`](manual-smoke-tests.md) — Milestone 1 GPIO
  and Codex MCP smoke tests. Run those first; the agent layer assumes
  `rpi-io-mcp` is already proven against the wiring on this bench.
- [`docs/deployment.md`](deployment.md) — agent service install + secret
  deployment.
- `tests/e2e/test_agent_chat.py` (LLM-A-8 positive E2E) and
  `tests/e2e/test_agent_negative.py` (LLM-A-8b negative-path E2E) — the
  scripted-LLM coverage that this manual checklist complements.

The four checks below cover the Phase A acceptance criteria from
`specs/features/llm-agent/requirements.md`:

1. [Bench browser flow](#1-bench-browser-flow) — operator drives the four
   MVP prompts from a real browser against a real LLM-free agent path
   (covers `AGENT-FR-001`, `AGENT-FR-002`, `AGENT-FR-003`, `AGENT-FR-007`).
2. [Live-LLM smoke](#2-live-llm-smoke---run-llm) — same prompts but with the
   real OpenRouter call, gated behind `--run-llm` so CI never touches the
   provider.
3. [Reboot persistence](#3-reboot-persistence) — service auto-starts after a
   power cycle and accepts a chat turn (`AGENT-FR-009`).
4. [Residual risk reminder](#4-residual-risk-reminder) — what to do when
   the bench live-LLM call starts to 4xx/5xx on or after **2026-05-08**.

## Prerequisites

- Milestone 1 GPIO wiring is in place and the multimeter / LED / button
  smoke from `docs/manual-smoke-tests.md` has been signed off on this
  bench. The agent layer drives the same GPIO23/GPIO24 pins through MCP;
  if those don't toggle by hand, the agent flow won't either.
- `rpi-io-mcp.service` and `rpi-io-agent.service` are both `active`
  (`systemctl is-active rpi-io-mcp.service rpi-io-agent.service` returns
  `active` twice).
- `/etc/perseus-smarthome/agent.env` exists with mode `0600` owner
  `root:root` and contains a working `LLM_API_KEY` (live-LLM smoke only).
  See [LLM Agent Secrets](deployment.md#llm-agent-secrets).
- Operator's MacBook is on the same trusted LAN as the Pi.
- `<pi>` below is the Pi's hostname or IP — substitute throughout.

## 1. Bench browser flow

The four MVP prompts must work end-to-end with the operator typing into a
real browser. This check does **not** require a live LLM key — the path
under test is the WebSocket chat service, the static page, and the agent's
MCP tool calls. With a missing/invalid key, the first turn returns
`error/code=llm_unconfigured` and the rest of the suite is gated behind
[live-LLM smoke](#2-live-llm-smoke---run-llm) below; for the four MVP prompts
the operator needs a working key.

1. Open `http://<pi>:8765/` on the LAN. The chat UI loads (no auth
   challenge — Phase A is trusted-LAN only).
2. Send the prompt **`turn on pin 23`** and observe:
   - Chat replies with a confirmation that names `gpio23_output`.
   - LED / multimeter / relay shows GPIO23 driven HIGH (≈ 3.3 V).
3. Send **`turn off pin 23`** and observe:
   - Chat replies with a confirmation.
   - GPIO23 returns to LOW (≈ 0 V); the LED extinguishes / the relay
     releases.
4. Send **`what is on pin 24`** and observe:
   - With BCM24 floating, the reply names value `0`.
   - Bridge BCM24 to a 3V3 rail (physical pin 1 or 17 — **never** physical
     2 or 4 which are 5 V), re-ask the same prompt, and observe value `1`.
   - Disconnect the bridge before moving on.
5. Send **`turn on pin 5`** (an unconfigured pin) and observe:
   - Chat replies with a refusal that explains the pin is not configured.
   - **No** new `set_output` call is logged on the MCP side.
   - Verify on the Pi:

     ```bash
     sudo journalctl -u rpi-io-mcp.service --since "30 sec ago" \
       | grep -E 'set_output|gpio5'
     # expect: no matches
     ```

If any step fails, capture `journalctl -u rpi-io-agent.service --since "5
min ago"` and the chat transcript before re-running.

## 2. Live-LLM smoke (`--run-llm`)

This check exercises the real OpenRouter call. CI never runs it because the
`llm` pytest marker is excluded from default runs and the `--run-llm` flag
gates execution explicitly.

```bash
uv run pytest tests/agent/ -m llm --run-llm
```

Pass criteria:

- Tests collect against the live model declared in
  `/etc/perseus-smarthome/agent.env` (`LLM_MODEL`).
- The default model `tencent/hy3-preview:free` returns expected refusals
  and tool-call decisions for the scripted prompts. If the listing has been
  swapped, tests run against the operator-chosen replacement (see
  [Residual risk reminder](#4-residual-risk-reminder)).

### OpenRouter free-tier 429 fallback

The `tencent/hy3-preview:free` listing does not publish per-key request /
minute or daily caps. When OpenRouter returns `429 Too Many Requests`:

- The agent must back off and surface the failure in chat (per
  `AGENT-FR-011`-aligned Residual Risks in `requirements.md`).
- Tool calls must **not** be retried implicitly — the operator decides
  whether to re-prompt.
- If the free tier is too tight for repeatable bench smoke, switch to a
  paid OpenRouter model or native Anthropic by editing the operator's
  local `.env` and re-running `make remote-install` (which redeploys
  `agent.env`); document the swap in the Phase A closeout PR.

## 3. Reboot persistence

```bash
ssh "$RPI_SSH_USER@$RPI_SSH_HOST" 'sudo reboot'
# wait ~60 s for the Pi to come back

ssh "$RPI_SSH_USER@$RPI_SSH_HOST" \
  'systemctl is-active rpi-io-mcp.service rpi-io-agent.service'
# expect: active (twice)
```

Then in a fresh browser tab open `http://<pi>:8765/`, send **`turn on pin
23`**, and confirm GPIO state. Expected: `gpio23_output` toggles HIGH and
the chat reply mentions the device. The agent service auto-started without
operator intervention, satisfying `AGENT-FR-009`.

End the check by sending **`turn off pin 23`** and confirming GPIO returns
to LOW so the bench is left in a safe state.

## 4. Residual risk reminder

`tencent/hy3-preview:free` is announced for deprecation **2026-05-08**.
That date is six days after the LLM agent spec was approved (2026-05-02);
the model was picked as a free-tier testing tradeoff with this exit
condition recorded in `specs/features/llm-agent/requirements.md` →
*Residual Risks*.

When the live-LLM smoke (section 2 above) starts to return 4xx/5xx on or
after 2026-05-08:

- That is **the expected signal**, not a regression.
- The swap path is one config change in the operator's local `.env`:
  set `LLM_MODEL` and `LLM_API_BASE_URL` to a current OpenAI-compatible
  endpoint (or set `model_provider="anthropic"` in the agent factory and
  drop `base_url` for native Anthropic).
- Re-run `make remote-install` to redeploy `/etc/perseus-smarthome/agent.env`
  with the new values.
- Note the swap in the Phase A closeout PR's Change Log so the milestone
  history captures which model actually gated acceptance.

## What "passing" means for Phase A

- `tests/e2e/test_agent_chat.py` and `tests/e2e/test_agent_negative.py`
  green under `--run-hardware`.
- All four MVP prompts pass section 1 above.
- `--run-llm` smoke is green against the current default model (or the
  documented replacement, post-2026-05-08).
- Reboot persistence is green and the agent unit auto-starts.

When all four are signed off, Phase A acceptance criteria from
`specs/features/llm-agent/requirements.md` (`AGENT-FR-001` through
`AGENT-FR-012`) are verified end-to-end and the closeout issue
(`LLM-A-10`, #78) can be opened for spec status flips.
