# LLM Agent Layer Design

Status: Approved (Phase A Implemented 2026-05-03; Phase B remains Approved-only)
Last reviewed: 2026-05-03
Owner: Vadim
Requirements: requirements.md

## Summary

Implement a Python service on the Raspberry Pi that hosts a LangChain
`deepagents` agent and exposes a WebSocket chat surface to the trusted
LAN. The agent reaches hardware exclusively through the existing
Milestone 1 `rpi-io-mcp` server — it does not touch GPIO directly. Phase A
ships the chat surface and live tool calls. Phase B adds persistent thing
aliases and `deepagents` long-term memory.

**Phase A status (2026-05-03):** Implemented. The two-process layout
(`rpi-io-mcp.service` + `rpi-io-agent.service`), the agent factory and
chat service under `src/perseus_smarthome/agent/`, the additive
`list_devices.rate_limit` MCP contract extension, the per-device
`asyncio.Lock` + global inter-toggle guard, the most-recent-wins
WebSocket session policy, the `EnvironmentFile=-` degraded-boot path,
and both install paths' agent-unit deployment are all on `main`.
Bench smoke executed on the live Pi at `172.16.0.106` is captured in
the LLM-A-9 closing comment on issue #77. Phase B sections of this
design (alias store, `CompositeBackend` long-term memory) remain
Approved-only and ungated until a Phase B kickoff.

The Milestone 1 MCP boundary already enforces the configured-device
allowlist and the GPIO23 safe-default. The agent layer inherits both for
free by going through that boundary.

## Runtime

- Target board: Raspberry Pi 2 (1 GB RAM, ARMv7 32-bit).
- Target OS: Raspberry Pi OS Lite 32-bit, Debian Trixie (matches
  Milestone 1).
- Python: 3.13.
- Package manager: `uv`. Lock file: `uv.lock`.
- Service manager: systemd. New unit `rpi-io-agent.service` parallel to
  the existing `rpi-io-mcp.service`.
- Chat transport: WebSocket over plain HTTP on the trusted LAN. TLS is
  out of scope for this milestone (matches Milestone 1's posture).
- Default chat listen address: `0.0.0.0`. Default chat port: TBD,
  proposed `8765`. Endpoint: `ws://<pi>:8765/chat`. Static page at
  `http://<pi>:8765/`.
- LLM transport: HTTPS to OpenRouter at
  `https://openrouter.ai/api/v1` using the OpenAI Chat Completions
  schema. Default model: `tencent/hy3-preview:free` (262K context,
  free tier, tool-use supported). Owner-approved 2026-05-02. Free
  tier has shared rate limits; switching to a paid model is a
  config-only change. The model is built once via LangChain
  `init_chat_model` and handed to `create_deep_agent(model=...)` —
  see the Agent Construction section.
- Hardware path: streamable HTTP MCP to the local `rpi-io-mcp` instance,
  default `http://127.0.0.1:8000/mcp` (override via `AGENT_RPI_MCP_URL`).

## Architecture

```text
Browser on LAN
  -> WebSocket /chat
  -> Agent chat service (this milestone)
       |
       +-- deepagents harness (LangChain + LangGraph)
       |     |
       |     +-- LLM (BaseChatModel built once via
       |     |        init_chat_model and handed to
       |     |        create_deep_agent(model=...))
       |     +-- Tool layer (Python wrappers around rpi-io-mcp)
       |     +-- Long-term memory (Phase B: CompositeBackend ->
       |                            StoreBackend at /memories/)
       |
       +-- Thing-alias service (Phase B)
       |     +-- JSON file on disk
       |
       +-- MCP client to rpi-io-mcp (streamable HTTP)
              -> Milestone 1 GPIO service & adapter -> hardware
```

The chat service is a single Python process. It owns the WebSocket
endpoint, the static-page handler, the agent loop, the alias store, and
the MCP client. It does not own GPIO.

## Process Layout (proposed)

Two systemd services on the Pi:

- `rpi-io-mcp.service` — unchanged from Milestone 1.
- `rpi-io-agent.service` — new. Depends on `rpi-io-mcp.service` so
  systemd starts MCP first and restarts the agent if MCP is unhealthy
  on boot.

This keeps the Milestone 1 contract untouched, lets the agent be
restarted independently while hardware control stays up, and mirrors a
future remote-agent topology where the agent could move off the Pi.

Single-process is also workable but is rejected as default because it
would couple agent restarts to MCP restarts and would hide the MCP
contract behind Python imports.

## Tooling Surface Exposed To The Agent

The agent's tool layer is a thin Python wrapper around the `rpi-io-mcp`
client. The agent never reaches GPIO directly.

Phase A tools:

- `list_devices()` — wraps MCP `list_devices`.
- `set_output(device_id: str, value: 0 | 1)` — wraps MCP `set_output`.
- `read_input(device_id: str)` — wraps MCP `read_input`.
- `health()` — wraps MCP `health`.

Phase B tools (additive):

- `list_things()` — returns alias map: `[{alias, device_id, kind}]`.
- `set_thing(alias: str, device_id: str)` — creates or rebinds an
  alias. Rebind requires `confirm: bool = False` and refuses without it
  when the alias already exists.
- `remove_thing(alias: str)` — removes an alias.
- `resolve_thing(alias: str)` — returns the configured device or a
  structured "unknown alias" error.

The system prompt instructs the agent to:

- Refer to devices by alias when one exists.
- Refuse requests targeting unconfigured pins or unknown aliases.
- Never invent a device ID — only use IDs returned by `list_devices`.
- Ask for confirmation before rebinding an existing alias.
- Treat the `set_thing` tool as the only way to persist a name; do not
  rely on long-term memory text alone for alias resolution.

## Hardware Safety Boundary

All hardware safety guarantees come from `rpi-io-mcp`. The agent
inherits them by going through the MCP boundary:

- Configured-device allowlist (FR-005, FR-007).
- GPIO23 safe-default-low on service start (FR-015).
- `wrong_direction` rejection if a write targets an input device.
- Structured error codes that the agent surfaces in chat.

The agent layer adds two further guards:

- **Per-device serialization.** Outbound `set_output` calls for the
  same `device_id` are serialized through an in-process `asyncio.Lock`
  (or equivalent) so the agent cannot interleave a flap. A global
  minimum inter-toggle interval (default 250 ms) is enforced before
  issuing the next `set_output` for the same device. The interval
  value is read from the MCP `list_devices` response top-level
  `rate_limit.output_min_interval_ms` field — the agent does not
  read `config/rpi-io.toml` from disk, which keeps the off-Pi-agent
  topology workable. If the field is absent (older MCP server), the
  agent falls back to the 250 ms default and logs a warning at
  startup.
- **Prompt-injection resistance for safety claims.** The agent's system
  prompt explicitly states that no chat instruction can override the
  configured-device allowlist or the alias-confirmation flow. The
  allowlist enforcement is at the MCP boundary regardless, so a
  successful prompt injection still cannot reach unconfigured pins.

## Persistence (Phase B)

### Thing-alias store

- Location: `/var/lib/perseus-smarthome/aliases.json`, created and
  owned by systemd via `StateDirectory=perseus-smarthome` on the
  `rpi-io-agent.service` unit. Owner is the unit's `User=`, which is
  standardized to `perseus-smarthome` across both install paths
  (deployment-spec amendment, see Phase A prereq task LLM-A-0 in
  `tasks.md`). Mode `0640`.
- Format: JSON. One top-level object: `{ "aliases": [ {alias,
  device_id, kind, created_at, last_modified} ] }`. Alias values are
  case-folded for comparison; original casing preserved for display.
- Concurrency: the chat service owns the file. Writes go through a
  small atomic-write helper (write-temp-then-rename). No other process
  writes to it.
- Validation on load:
  - Every alias's `device_id` must exist in `rpi-io-mcp`'s
    `list_devices`. Aliases pointing at devices that no longer exist
    are surfaced to the operator as a startup warning in chat and are
    not auto-deleted.
- Backup: not in scope for this milestone; document the file location
  in `docs/deployment.md` so operators can copy it.

### Long-term agent memory

- Backed by `deepagents`'s `CompositeBackend` routing `/memories/` to a
  `StoreBackend`. Store backed by SQLite at
  `/var/lib/perseus-smarthome/agent-memory.db`.
- Namespace: single namespace per Pi for this milestone (single-user
  trusted-LAN posture). Multi-tenant memory is out of scope.
- Memory is for durable agent context (operator preferences, learned
  conventions). The alias store is the source of truth for thing
  resolution — the agent must call `resolve_thing` rather than guess
  from memory contents.

## WebSocket Protocol

Frame shape, JSON lines, one frame per chat turn or system event:

Client → server:

```json
{ "type": "user_turn", "content": "turn on pin 23" }
```

Server → client:

```json
{ "type": "agent_turn", "content": "Turning gpio23_output on." }
{ "type": "tool_call", "name": "set_output", "args": {...} }
{ "type": "tool_result", "name": "set_output", "ok": true, ... }
{ "type": "agent_done" }
{ "type": "error", "code": "llm_unreachable", "message": "..." }
```

Tool-call frames are informational so the operator can see what the
agent did. They are not control frames; clients should treat them as
read-only.

The chat service enforces a **most-recent-wins** single-session
policy. At any moment at most one WebSocket holds the agent session.
When a second connection arrives, the chat service:

1. Sends `{ "type": "error", "code": "session_superseded",
   "message": "..." }` on the prior WebSocket and closes it.
2. Accepts the new connection and binds it to the agent session.

This keeps a quick laptop-sleep / Wi-Fi-blip reconnect from being
locked out by a still-warm zombie session, and matches typical
single-user dev-tool behavior (Vite, Jupyter, etc.). The tradeoff
is documented in `requirements.md` Edge Cases: a second concurrent
operator silently displaces the first; acceptable on the
single-operator trusted-LAN posture.

Multi-session ownership (per-user identity) is reconsidered in
Phase B if needed.

## Static Chat Page

A single HTML file with vanilla JS, served from the chat service. No
build step. Renders a transcript pane and an input box. Connects to
`ws://<same-host>:<same-port>/chat`. Shows `tool_call` and `tool_result`
frames as collapsed lines so the operator can audit what was invoked.

## Configuration

New `.env.example` keys:

```text
OPENROUTER_API_KEY   # OpenRouter key for the default provider route
OPENAI_API_KEY       # OpenAI-compatible key; accepted for OpenRouter too
ANTHROPIC_API_KEY    # optional native Anthropic key for future/provider swaps
LANGSMITH_*          # optional LangSmith tracing keys
LLM_API_BASE_URL     # default https://openrouter.ai/api/v1
LLM_MODEL            # default tencent/hy3-preview:free
AGENT_CHAT_HOST      # default 0.0.0.0
AGENT_CHAT_PORT      # default 8765
AGENT_RPI_MCP_URL    # default http://127.0.0.1:8000/mcp
```

`LLM_API_KEY` is accepted as a deprecated fallback alias for existing
operator `.env` files. For the default OpenRouter route, the factory
uses `OPENROUTER_API_KEY` first, then `OPENAI_API_KEY`, then legacy
`LLM_API_KEY`. New OpenAI-compatible non-OpenRouter endpoints should use
`OPENAI_API_KEY`, matching LangChain / Deep Agents conventions.

## Agent Construction

`deepagents` owns model instantiation. The agent factory builds a
LangChain `BaseChatModel` once via `init_chat_model`, then hands it to
`create_deep_agent(model=...)`. The signature of `create_deep_agent` is
(abridged):

```python
create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    backend: BackendProtocol | BackendFactory | None = None,
    store: BaseStore | None = None,
    ...
) -> CompiledStateGraph
```

Concrete construction for the default OpenRouter target:

```python
from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent

model = init_chat_model(
    model=os.environ["LLM_MODEL"],          # tencent/hy3-preview:free
    model_provider="openai",                # OpenAI Chat Completions schema
    base_url=os.environ["LLM_API_BASE_URL"],# https://openrouter.ai/api/v1
    api_key=os.environ["OPENROUTER_API_KEY"], # or OPENAI/legacy fallback
)

agent = create_deep_agent(
    model=model,
    tools=[list_devices, set_output, read_input, health,
           # Phase B additions:
           # list_things, set_thing, remove_thing, resolve_thing
           ],
    system_prompt=AGENT_SYSTEM_PROMPT,
    # Phase B: backend=CompositeBackend(... StoreBackend at /memories/),
    #          store=<langgraph BaseStore backed by SQLite>,
)
```

Provider swap: change `LLM_API_BASE_URL` and `LLM_MODEL` (and
`OPENROUTER_API_KEY` / `OPENAI_API_KEY` for the OpenAI-compatible route)
in `.env`.
`model_provider="openai"` stays the same for
any OpenAI-Chat-Completions-compatible endpoint (OpenRouter, OpenAI
proper, a local vLLM/SGLang server, etc.). For non-OpenAI-compatible
providers (e.g. native Anthropic) the swap is one extra line: change
`model_provider`, drop `base_url`, and use that provider's standard key
such as `ANTHROPIC_API_KEY`.

A `LLM_PROVIDER` env key is intentionally not added — `init_chat_model`
already takes `model_provider` as a Python argument; introducing a
parallel env-only knob would let the two drift.

`config/rpi-io.toml` proposed additions (optional, owner-decided):

```toml
[rate_limit]
output_min_interval_ms = 250
```

## Error Model

Agent-level errors surface as `error` frames over the WebSocket plus
plain-language summaries inside `agent_turn` frames. Reused/added codes:

- `llm_unreachable` — provider HTTPS error or timeout.
- `llm_unauthorized` — provider rejected the API key.
- `llm_unconfigured` — `OPENROUTER_API_KEY` and `OPENAI_API_KEY` are
  unset or empty at the time the operator sends a turn, and no legacy
  `LLM_API_KEY` fallback is present. The chat service comes up in degraded mode, accepts
  WebSocket connections, and surfaces this code on the first turn
  rather than failing to start. `requirements.md` Verification covers
  the boot path.
- `mcp_unreachable` — `rpi-io-mcp` not responding.
- `mcp_error` — MCP returned a structured error; original code
  forwarded in `details`.
- `unknown_alias` — Phase B; alias not in store.
- `alias_conflict` — Phase B; rebind requested without confirm.
- `session_superseded` — sent to the prior WebSocket when a new
  connection takes the session (most-recent-wins, see WebSocket
  Protocol).
- `unconfigured_pin` — operator referenced a pin not in
  `config/rpi-io.toml`.

No code path may include the `OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`, or legacy `LLM_API_KEY` value
in any error message or log line. Tool-call frames must not embed these
keys in headers or debug payloads.

`tool_call` frames echo argument dictionaries to the chat client by
default. Phase A tools take only device IDs and integer values so
this is safe. Future tools that accept free-form operator-supplied
text or any field that could carry a credential, webhook URL, or
PII must implement a per-field redaction pass before the frame is
serialized — the chat client is treated as a low-trust surface
(operators may screen-share).

## Tests

Unit tests (mock LLM, mock MCP client):

- Tool-wrapper layer maps natural-language prompts to MCP tool calls
  for the canonical phrases listed in requirements acceptance.
- Unconfigured-pin requests are refused before MCP is touched.
- MCP error codes are translated into plain-language replies.
- Per-device serialization holds under concurrent tool-call attempts.

Phase B unit tests:

- Alias add / lookup / rename / remove round-trips through the JSON
  file.
- Alias to unconfigured device is rejected.
- Rebind without `confirm=True` returns `alias_conflict`.
- Loading an alias file whose `device_id` no longer exists in MCP
  produces a startup warning and does not crash.

Integration tests (real `rpi-io-mcp`, mock LLM that emits scripted
tool-call sequences):

- WebSocket client connects, sends "turn on pin 23", asserts
  `set_output(gpio23_output, 1)` was issued and GPIO23 is `1`.
- WebSocket client sends "what is on pin 24", asserts a `read_input`
  call and the resulting value reaches the chat reply.

Manual smoke tests:

- Phase A bench: open chat in a browser, run the four MVP prompts
  against the loopback wiring, confirm GPIO state matches.
- Phase B bench: assign "lamp" to pin 23, reboot Pi, reconnect, run
  "turn the lamp on", confirm hardware response.

End-to-end live LLM test is gated behind `--run-llm` (analogous to
Milestone 1's `--run-hardware`) so CI does not need a provider key.

## Deployment

- New systemd unit `deploy/systemd/rpi-io-agent.service`.
- `User=perseus-smarthome`, `Group=perseus-smarthome` — both
  install paths standardize on the `perseus-smarthome` system
  user (deployment-spec amendment, prereq task LLM-A-0). The
  `perseus-smarthome` user already exists on the deb path and is
  created at script-install time after LLM-A-0 lands. The agent
  unit's `Group=` is **not** `gpio`: the agent reaches hardware
  only through `rpi-io-mcp` over HTTP, so its primary GID does
  not need to be `gpio`. The MCP unit retains `Group=gpio`
  because it actually drives GPIO. Setting
  `Group=perseus-smarthome` on the agent unit makes
  `StateDirectory=perseus-smarthome` land files owned
  `perseus-smarthome:perseus-smarthome`, matching the Phase B
  ownership claim for `aliases.json` and `agent-memory.db`.

  Note on least privilege: with the current postinst (which
  runs `usermod -aG gpio perseus-smarthome`), the
  `perseus-smarthome` user is a *supplementary* member of
  `gpio` system-wide. systemd inherits user supplementary
  groups by default — `Group=perseus-smarthome` does not
  override that — so the agent process technically still has
  permission to open `/dev/gpio*`. The hardware safety
  guarantee continues to come from the MCP allowlist boundary
  (the agent doesn't open `/dev/gpio*` because nothing in its
  code path tries to), not from group isolation. A follow-up
  hardening would drop the supplementary `gpio` membership and
  let `Group=gpio` on the MCP unit be the only path to GPIO;
  noted under Residual Risks.
- `After=rpi-io-mcp.service`, `Wants=rpi-io-mcp.service`.
- `Restart=on-failure`.
- `StateDirectory=perseus-smarthome` so
  `/var/lib/perseus-smarthome/{aliases.json,agent-memory.db}` are
  managed by systemd ownership at mode `0750` (default), with the
  alias file at mode `0640` written by the service itself.
- `EnvironmentFile=-/etc/perseus-smarthome/agent.env` (the
  leading `-` makes the unit start in degraded mode if the file is
  missing, surfacing `llm_unconfigured` on the first turn — see
  Error Model). systemd reads this file as root at unit start, before
  dropping to `User=perseus-smarthome`, so mode `0600` owner `root`
  works.
- **Secret deployment from MacBook (script path):**
  `scripts/remote-install.sh` is extended to read the local
  `.env` (gitignored, repo root), filter only approved
  agent-runtime keys (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `LANGSMITH_*`, `LLM_MODEL`, `LLM_API_BASE_URL`, and legacy
  `LLM_API_KEY`), and scp them to the Pi at
  `/etc/perseus-smarthome/agent.env` with `chmod 600` and owner
  `root`. `RPI_*` keys are explicitly excluded; they have no
  business sitting on the Pi. Re-running `make remote-install`
  overwrites the file idempotently.
- **Secret deployment (deb path):** the package cannot ship the
  secret. Operator manually creates
  `/etc/perseus-smarthome/agent.env` after `apt install` per the
  documented step in `docs/deployment.md`. The unit's
  `EnvironmentFile=-` prefix means the service still starts and
  surfaces `llm_unconfigured` on the first turn until the file
  exists.
- `make remote-install` and the deb path both extended to install
  the new unit alongside the existing one.
- `docs/deployment.md` updated with the new `.env` keys (in the
  repo-root `.env`), the approved agent-key filtering behavior of
  `remote-install.sh`, the deb-path manual step, and a note that
  the on-Pi env file must remain `chmod 600` owner `root`.

## Resolved Design Decisions

Owner-approved 2026-05-02:

- **LLM host.** Remote API over HTTPS. No on-device inference.
- **Process layout.** Two systemd services on the Pi:
  `rpi-io-mcp.service` (unchanged) and `rpi-io-agent.service` (new),
  with `After=rpi-io-mcp.service` and `Wants=rpi-io-mcp.service`.
- **Phase split.** Phase A and Phase B ship under separate owner
  approvals. Phase B work does not start until Phase A closes.
- **Chat WebSocket auth.** Trusted LAN only, no auth. The
  `AGENT_SHARED_SECRET` env key is dropped from the reference design;
  if a future milestone re-introduces auth it can be added back.
- **LLM provider and model.** OpenRouter at
  `https://openrouter.ai/api/v1`, default model
  `tencent/hy3-preview:free`. Implementation uses an OpenAI Chat
  Completions compatible client (`langchain-openai` chat model with
  `base_url` override is the proposed concrete dep). Provider is
  swappable via `.env` keys; no code change needed to point at OpenAI
  proper, a local vLLM, etc.
- **Alias store format.** JSON file at
  `/var/lib/perseus-smarthome/aliases.json`, atomic write
  (write-temp-then-rename), case-folded comparison, mode `0640`.
- **Output rate-limit policy.** Per-device `asyncio.Lock` (mandatory
  for race-safety) plus a **global** 250 ms minimum inter-toggle
  interval applied to every output. The interval is published to
  the agent through the MCP `list_devices` response as a top-level
  `rate_limit.output_min_interval_ms` field. The lock and the
  interval are enforced in the agent process. The MCP contract gains
  a small additive field (Phase A task LLM-A-2 also amends
  `specs/features/rpi-io-mcp/`); existing clients that ignore the
  new field still work.
- **Service user across install paths.** Both script-install and
  deb-install standardize on `User=perseus-smarthome` (Phase A
  prereq task LLM-A-0 amends `specs/features/deployment/`). Drops
  the previous "divergent by design" model so the alias store and
  `agent-memory.db` have one documented owner.
- **Multi-session policy.** Most-recent-wins; the prior WebSocket
  is closed with `error/code=session_superseded` when a new
  connection takes the session. Drops the earlier
  `session_in_use` rejection.
- **Service boot with missing provider key.** Service starts in
  degraded mode (does not exit non-zero, does not flap under
  systemd `Restart=on-failure`) when `OPENROUTER_API_KEY` /
  `OPENAI_API_KEY` are absent and no legacy `LLM_API_KEY` fallback is
  present. WebSocket connections succeed. The first operator turn
  returns `llm_unconfigured` so the configuration problem is visible
  without revealing the key.

## Open Design Decisions

None. All design decisions are resolved.

## Residual Risks

- **`tencent/hy3-preview:free` going-away date 2026-05-08.** Default
  OpenRouter listing announces deprecation six days after this spec
  was finalized. Swap path is a one-line `.env` change. Phase A
  integration tests against the live model will start to 4xx/5xx on
  or after that date — that is the expected signal to flip the
  default, not a regression in the agent code.
- **OpenRouter free-tier rate limits unpublished.** Phase A
  integration tests must back off on `429` and surface failures in
  chat instead of retrying. If the free tier proves too tight,
  switch to a paid OpenRouter model or native Anthropic before
  Phase B.
- **Agent process inherits `gpio` supplementary group.** The
  `perseus-smarthome` user is a supplementary member of `gpio`
  (added by the existing deb postinst and mirrored by `LLM-A-0`
  for the script path) so the MCP unit can keep `Group=gpio`.
  systemd inherits user supplementary groups, so the agent
  process — which sets `Group=perseus-smarthome` — still has
  read/write permission on `/dev/gpio*` even though it has no
  reason to use it. Hardware safety remains anchored at the MCP
  allowlist boundary, which the agent cannot bypass. A future
  hardening could drop the supplementary `gpio` membership and
  rely solely on the MCP unit's `Group=gpio` (primary) for
  hardware access. Out of scope for Phase A.

## Change Log

- 2026-05-02: Initial Draft. Two-process layout (rpi-io-mcp +
  rpi-io-agent), agent reaches hardware only through MCP, Phase B adds
  JSON alias store + `deepagents` long-term memory backed by SQLite,
  WebSocket frame shape sketched, six Open Design Decisions surfaced.
- 2026-05-02: Owner resolved four of six Open Design Decisions:
  remote LLM API, two-systemd-service process layout, separate
  Phase A/B approval gates, trusted-LAN-no-auth chat posture.
  `AGENT_SHARED_SECRET` removed from `.env.example`. Three
  subdetails remain open (provider/model, alias store format,
  rate-limit default), each with a proposed default.
- 2026-05-02: Owner picked OpenRouter (default model
  `tencent/hy3-preview:free`) and confirmed JSON for the alias store.
  SDK choice is now an OpenAI Chat Completions compatible client
  (proposed: `langchain-openai` with `base_url` override). New env
  key `LLM_API_BASE_URL` added; provider is swappable via `.env`.
  Output rate-limit policy is the only remaining Open Design
  Decision.
- 2026-05-02: Owner picked the rate-limit policy: per-device
  `asyncio.Lock` + 250 ms minimum inter-toggle interval,
  configurable per-device via `rate_limit_ms` in
  `config/rpi-io.toml`. Lock and interval are enforced in the agent
  process so `rpi-io-mcp`'s contract stays untouched. All Open
  Design Decisions resolved.
- 2026-05-02: Spec-review pass folded six decisions into the
  design. Rate-limit shape switched from per-device on
  `[[devices]]` to a **global**
  `rate_limit.output_min_interval_ms`, sourced via an additive
  extension to the MCP `list_devices` response (so the agent does
  not parse `config/rpi-io.toml` and stays portable off-Pi).
  Service user standardized to `perseus-smarthome` across both
  install paths (Phase A prereq task LLM-A-0 amends the
  deployment spec, reversing its "divergent by design" decision).
  Multi-session policy switched to most-recent-wins with
  `session_superseded`; `session_in_use` is dropped from the error
  model. The then-current `LLM_*` key set lived in the same root `.env`
  and `scripts/remote-install.sh` filtered and copied it to
  `/etc/perseus-smarthome/agent.env` (mode `0600`, owner `root`)
  on the Pi; deb-path operators create the file by hand. This env-key
  shape was superseded by the 2026-05-03 LangChain / OpenRouter sync
  entry below.
  `EnvironmentFile=-` lets the service start in degraded mode when
  the secret is missing; `llm_unconfigured` surfaces on the first
  turn. Stale "see Open Question #6" reference removed. Added
  `tool_call` redaction note for future tools that take free-form
  args. Residual Risks section captures the
  `tencent/hy3-preview:free` 2026-05-08 going-away date.
- 2026-05-02: Three additional punch-list defects fixed before
  approval. (1) Resilience verification mis-traced to
  `AGENT-FR-024` (Phase B alias persistence); added Phase A
  `AGENT-FR-012` for the MCP-client reconnect path and
  retargeted the trace. (2) `LLM-A-6` covered only the
  script-install path; expanded to extend
  `packaging/build-deb.sh` (drift check + payload staging),
  add `packaging/debian/perseus-smarthome-agent.service`,
  and update `postinst`/`prerm`/`postrm` so the deb cannot
  silently ship without the agent unit. (3) `LLM-A-6`'s
  `Group=gpio` on the agent unit contradicted `LLM-B-4`'s
  ownership claim for `/var/lib/perseus-smarthome/`; corrected
  to `Group=perseus-smarthome` and noted the supplementary-`gpio`
  inheritance caveat under Residual Risks.
- 2026-05-02: Owner approved. Status flipped from Draft to
  Approved.
- 2026-05-03: Env contract synchronized with LangChain / Deep Agents
  conventions. `OPENROUTER_API_KEY` is the explicit default-route
  credential; `OPENAI_API_KEY` remains accepted for OpenAI-compatible
  endpoints. `ANTHROPIC_API_KEY` and `LANGSMITH_*` are documented as
  approved agent-runtime keys. `LLM_API_KEY` remains a deprecated
  fallback. Deployment filtering and examples were updated to match.
- 2026-05-03: Phase A closeout (LLM-A-10). Top-level `Status`
  callout extended with Phase A Implemented note; Phase A status
  block added to the Summary section pointing reviewers at the
  bench-evidence comment on issue #77. No design content changed —
  this is a status-flip pass only. Phase B sections remain
  Approved-only and untouched. Implementation residual risks
  surfaced during the bench smoke are tracked outside this spec
  on follow-up issues #98 (Phase B `tool_call` arg redaction
  prereq), #102 (`rustc`/`cargo` to `APT_PREREQS`), #103 (PR #101
  graceful-shutdown SIGKILL on `TimeoutStopSec=10`), and #104
  (`AGENT-FR-006` `read_input` vs `list_devices.state` shortcut
  divergence). The pre-existing Residual Risks list in this file
  (`tencent/hy3-preview:free` going-away, OpenRouter free-tier
  rate limits, supplementary-`gpio` group inheritance) is
  unchanged; the OpenRouter free-tier risk was confirmed
  empirically on the bench (five free models hit different
  failure modes; smoke completed against
  `google/gemini-3-flash-preview` paid).
