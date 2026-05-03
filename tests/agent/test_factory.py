"""Tests for the deepagents agent factory.

Degraded-mode tests (bottom section: no agent extras needed) run in
default CI (``uv sync`` without ``--extra agent``).

Happy-path tests (CompiledStateGraph construction, tool-call wiring,
init_chat_model argument verification) require the [agent] extras and
are skipped when those deps are absent.

Spec: AGENT-FR-003, AGENT-FR-010, AGENT-FR-011
Design: specs/features/llm-agent/design.md
  - "Agent Construction" section
  - "Error Model" → llm_unconfigured
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from perseus_smarthome.agent.factory import (
    AGENT_SYSTEM_PROMPT,
    _build_default_tools,
    _UnconfiguredAgent,
    create_agent,
)

# ---------------------------------------------------------------------------
# Optional agent deps — needed only for happy-path tests.
# ---------------------------------------------------------------------------

_AGENT_DEPS = True
try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolCall
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import tool
    from langgraph.graph.state import CompiledStateGraph
    from pydantic import Field
except ImportError:
    _AGENT_DEPS = False

_skip_without_agent_deps = pytest.mark.skipif(
    not _AGENT_DEPS,
    reason="requires [agent] extras (deepagents, langchain-core, langgraph)",
)

# Define agent-dep helpers only when deps are available to avoid NameError
# at class/function definition time.
if _AGENT_DEPS:

    class ScriptedChatModel(BaseChatModel):  # type: ignore[misc]
        """Stub BaseChatModel returning pre-scripted AIMessages in order.

        Implements ``bind_tools`` so deepagents can wire tool schemas without error.
        """

        responses: list[AIMessage] = Field(default_factory=list)
        call_count: int = Field(default=0)

        @property
        def _llm_type(self) -> str:
            return "scripted-stub"

        def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
            """Return self — tool schemas accepted but not inspected by the stub."""
            return self

        def _generate(
            self,
            messages: list[Any],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            if self.call_count < len(self.responses):
                msg = self.responses[self.call_count]
            else:
                msg = AIMessage(content="Done.")
            object.__setattr__(self, "call_count", self.call_count + 1)
            return ChatResult(generations=[ChatGeneration(message=msg)])

    def _make_stub(*responses: AIMessage) -> ScriptedChatModel:
        """Return a ScriptedChatModel pre-loaded with *responses*."""
        return ScriptedChatModel(responses=list(responses))

    def _noop_tool(name: str) -> Any:
        """Return a named no-op LangChain tool for wiring tests."""

        @tool
        def _t() -> dict[str, Any]:
            """No-op."""
            return {"ok": True}

        _t.name = name  # type: ignore[attr-defined]
        return _t

    _PHASE_A_NOOP_TOOLS = [
        _noop_tool("health"),
        _noop_tool("list_devices"),
        _noop_tool("set_output"),
        _noop_tool("read_input"),
    ]


# ---------------------------------------------------------------------------
# Degraded-mode tests — no agent extras needed; always run in CI.
# ---------------------------------------------------------------------------


def _clear_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_create_agent_returns_unconfigured_when_provider_keys_are_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_agent() must return _UnconfiguredAgent when provider keys are absent."""
    _clear_provider_keys(monkeypatch)
    agent = create_agent()
    assert isinstance(agent, _UnconfiguredAgent)


def test_create_agent_returns_unconfigured_when_provider_keys_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_agent() must return _UnconfiguredAgent when provider keys are empty."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    agent = create_agent()
    assert isinstance(agent, _UnconfiguredAgent)


def test_create_agent_returns_unconfigured_when_provider_keys_are_whitespace_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only provider keys are treated as unset."""
    monkeypatch.setenv("OPENROUTER_API_KEY", " ")
    monkeypatch.setenv("OPENAI_API_KEY", "\t")
    monkeypatch.setenv("LLM_API_KEY", "   ")
    agent = create_agent()
    assert isinstance(agent, _UnconfiguredAgent)


def test_unconfigured_agent_returns_llm_unconfigured_code() -> None:
    """_UnconfiguredAgent.invoke must return code='llm_unconfigured'."""
    agent = _UnconfiguredAgent()
    result = agent.invoke({"messages": []})
    assert result["code"] == "llm_unconfigured"


def test_unconfigured_agent_returns_error_type() -> None:
    """_UnconfiguredAgent response type must be 'error'."""
    agent = _UnconfiguredAgent()
    result = agent.invoke({"messages": []})
    assert result["type"] == "error"


def test_unconfigured_agent_callable_returns_same_as_invoke() -> None:
    """Calling _UnconfiguredAgent() directly must equal .invoke()."""
    agent = _UnconfiguredAgent()
    assert agent({}) == agent.invoke({})


def test_unconfigured_error_does_not_contain_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_UnconfiguredAgent response must not echo provider keys from the environment.

    Sets recognisable sentinels so that any code path reading
    the env var and including it in the response would be caught.

    Spec: AGENT-FR-010 — credential must never appear in logs or error messages.
    """
    secrets = {
        "OPENROUTER_API_KEY": "or-secret-key-xyz",
        "OPENAI_API_KEY": "openai-secret-key-xyz",
        "LLM_API_KEY": "legacy-secret-key-xyz",
    }
    for key, secret in secrets.items():
        monkeypatch.setenv(key, secret)
    agent = _UnconfiguredAgent()
    result = agent.invoke({"messages": []})
    for value in result.values():
        for key, secret in secrets.items():
            assert secret not in str(value), (
                f"{key} value leaked into error output: {value!r}"
            )


def test_create_agent_does_not_raise_on_import_with_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing factory and calling create_agent must not raise with no key.

    Spec: AGENT-FR-011 — service must start in degraded mode without exiting.
    """
    _clear_provider_keys(monkeypatch)
    agent = create_agent()
    assert agent is not None


def test_system_prompt_constant_is_non_empty() -> None:
    """AGENT_SYSTEM_PROMPT must be a non-empty string."""
    assert isinstance(AGENT_SYSTEM_PROMPT, str)
    assert len(AGENT_SYSTEM_PROMPT.strip()) > 0


def test_system_prompt_mentions_safety_rules() -> None:
    """System prompt must contain the non-overridable safety-rules clause."""
    assert "SAFETY RULES" in AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Happy-path tests — require [agent] extras; skipped in default CI.
# ---------------------------------------------------------------------------


@_skip_without_agent_deps
def test_create_agent_returns_compiled_state_graph_with_stub_model() -> None:
    """create_agent(model=stub) must return a CompiledStateGraph."""
    stub = _make_stub(AIMessage(content="Hello."))
    agent = create_agent(model=stub, tools=_PHASE_A_NOOP_TOOLS)
    assert isinstance(agent, CompiledStateGraph)


@_skip_without_agent_deps
def test_factory_wires_four_phase_a_tools() -> None:
    """All four Phase A tools must be reachable and callable via the wired agent."""
    call_log: list[str] = []

    @tool
    def health() -> dict[str, Any]:
        """Health."""
        call_log.append("health")
        return {"ok": True, "service": "rpi-io-mcp"}

    @tool
    def list_devices() -> dict[str, Any]:
        """List devices."""
        call_log.append("list_devices")
        return {"devices": []}

    @tool
    def set_output(device_id: str, value: int) -> dict[str, Any]:
        """Set output."""
        call_log.append("set_output")
        return {"ok": True, "device_id": device_id, "value": value}

    @tool
    def read_input(device_id: str) -> dict[str, Any]:
        """Read input."""
        call_log.append("read_input")
        return {"ok": True, "device_id": device_id, "value": 0}

    # Stub: emit one ToolCall per Phase A tool, then give the final response.
    tcs = [
        ToolCall(name="health", args={}, id="c1"),
        ToolCall(name="list_devices", args={}, id="c2"),
        ToolCall(
            name="set_output",
            args={"device_id": "gpio23_output", "value": 1},
            id="c3",
        ),
        ToolCall(name="read_input", args={"device_id": "gpio24_input"}, id="c4"),
    ]
    stub = _make_stub(
        AIMessage(content="", tool_calls=tcs),
        AIMessage(content="Done."),
    )

    agent = create_agent(
        model=stub, tools=[health, list_devices, set_output, read_input]
    )
    agent.invoke({"messages": [HumanMessage(content="test all tools")]})

    assert set(call_log) == {
        "health",
        "list_devices",
        "set_output",
        "read_input",
    }, f"Expected all four Phase A tools called; got: {call_log}"


@_skip_without_agent_deps
def test_tool_call_wiring_set_output() -> None:
    """Stub model emits set_output(gpio23_output, 1); tool must be invoked with those args.

    Acceptance: Design "Agent Construction"; issue LLM-A-4 acceptance bullet 2.
    """
    call_log: list[dict[str, Any]] = []

    @tool
    def set_output(device_id: str, value: int) -> dict[str, Any]:  # noqa: WPS442
        """Set a GPIO output device to 0 (off) or 1 (on)."""
        call_log.append({"device_id": device_id, "value": value})
        return {"ok": True, "device_id": device_id, "value": value}

    @tool
    def list_devices() -> dict[str, Any]:  # noqa: WPS442
        """List devices."""
        return {"devices": []}

    @tool
    def read_input(device_id: str) -> dict[str, Any]:  # noqa: WPS442
        """Read input."""
        return {"ok": True, "device_id": device_id, "value": 0}

    @tool
    def health() -> dict[str, Any]:  # noqa: WPS442
        """Health."""
        return {"ok": True, "service": "rpi-io-mcp"}

    tc = ToolCall(
        name="set_output",
        args={"device_id": "gpio23_output", "value": 1},
        id="call_test_1",
    )
    stub = _make_stub(
        AIMessage(content="", tool_calls=[tc]),
        AIMessage(content="GPIO23 is now on."),
    )

    agent = create_agent(
        model=stub,
        tools=[list_devices, set_output, read_input, health],
    )
    agent.invoke({"messages": [HumanMessage(content="Turn on gpio23_output")]})

    assert len(call_log) == 1, f"Expected 1 set_output call, got {call_log}"
    assert call_log[0]["device_id"] == "gpio23_output"
    assert call_log[0]["value"] == 1


@_skip_without_agent_deps
def test_init_chat_model_receives_correct_provider_url_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_agent with a real key must call init_chat_model with the right args.

    Verifies model_provider="openai", correct base_url, correct model name,
    and that the api_key is passed through — but never logged (AGENT-FR-010).
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-abc123")
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-key")
    monkeypatch.setenv("LLM_API_KEY", "legacy-key")
    monkeypatch.setenv("LLM_API_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model/name")

    stub = _make_stub(AIMessage(content="Done."))

    with patch(
        "langchain.chat_models.init_chat_model", return_value=stub
    ) as mock_init:
        agent = create_agent(tools=_PHASE_A_NOOP_TOOLS)

    mock_init.assert_called_once_with(
        model="test-model/name",
        model_provider="openai",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key-abc123",
    )
    assert isinstance(agent, CompiledStateGraph)


@_skip_without_agent_deps
def test_init_chat_model_falls_back_to_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPENAI_API_KEY is accepted when OPENROUTER_API_KEY is absent."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-compatible-key")
    monkeypatch.setenv("LLM_API_KEY", "legacy-key")

    stub = _make_stub(AIMessage(content="Done."))

    with patch(
        "langchain.chat_models.init_chat_model", return_value=stub
    ) as mock_init:
        create_agent(tools=_PHASE_A_NOOP_TOOLS)

    assert mock_init.call_args.kwargs["api_key"] == "openai-compatible-key"


@_skip_without_agent_deps
def test_init_chat_model_falls_back_to_legacy_llm_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_API_KEY remains a deprecated compatibility fallback."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "legacy-key")

    stub = _make_stub(AIMessage(content="Done."))

    with patch(
        "langchain.chat_models.init_chat_model", return_value=stub
    ) as mock_init:
        create_agent(tools=_PHASE_A_NOOP_TOOLS)

    assert mock_init.call_args.kwargs["api_key"] == "legacy-key"


@_skip_without_agent_deps
def test_init_chat_model_uses_default_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When LLM_MODEL / LLM_API_BASE_URL are unset, documented defaults are used."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "some-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    stub = _make_stub(AIMessage(content="Done."))

    with patch(
        "langchain.chat_models.init_chat_model", return_value=stub
    ) as mock_init:
        create_agent(tools=_PHASE_A_NOOP_TOOLS)

    kw = mock_init.call_args.kwargs
    assert kw["model"] == "tencent/hy3-preview:free"
    assert kw["model_provider"] == "openai"
    assert kw["base_url"] == "https://openrouter.ai/api/v1"
    assert kw["api_key"] == "some-key"


@_skip_without_agent_deps
def test_create_agent_with_injected_model_bypasses_init_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model= is supplied, create_agent uses it regardless of provider keys."""
    _clear_provider_keys(monkeypatch)
    stub = _make_stub(AIMessage(content="Hello."))
    agent = create_agent(model=stub, tools=_PHASE_A_NOOP_TOOLS)
    # Injected model → real agent, not degraded.
    assert isinstance(agent, CompiledStateGraph)


# ---------------------------------------------------------------------------
# Regression: _build_default_tools must share state across calls
# ---------------------------------------------------------------------------
#
# Before the fix, each @tool wrapper inside _build_default_tools opened a
# fresh streamable-HTTP MCP session AND instantiated a brand-new
# RpiIOMCPTools.from_session(session) per call.  That rebuilt the
# OutputRateLimiter with empty _locks/_last_call on every set_output, so
# the per-device asyncio.Lock and 250 ms inter-toggle interval mandated by
# Resolved Decision #7 / AGENT-FR-007 never serialised anything across
# calls in production, and every set_output triggered a fresh lazy
# list_devices (mcp_tools.py: lazy device-cache init).
#
# These tests inject a fake call_tool through the new optional kwarg so
# no real MCP server is needed.  They verify the shared rate limiter and
# device cache by exercising the wrappers end-to-end — they fail on the
# unmodified factory (where each wrapper builds its own RpiIOMCPTools)
# and pass after the fix.


@_skip_without_agent_deps
def test_build_default_tools_shares_device_cache_across_set_output_calls() -> None:
    """Two set_output calls through the wrappers must trigger list_devices once.

    Before the fix, each wrapper rebuilt RpiIOMCPTools so the lazy device
    cache was empty on every set_output, causing a duplicate list_devices
    round-trip per write.
    """
    import asyncio  # noqa: PLC0415

    call_log: list[str] = []
    devices = [
        {
            "id": "gpio23_output",
            "name": "GPIO23 Output",
            "kind": "output",
            "capabilities": ["set_output"],
            "state": 0,
        }
    ]

    async def fake_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        call_log.append(name)
        if name == "list_devices":
            return {
                "devices": devices,
                "rate_limit": {"output_min_interval_ms": 100},
            }
        if name == "set_output":
            return {
                "ok": True,
                "device_id": args["device_id"],
                "value": args["value"],
            }
        raise AssertionError(f"unexpected tool: {name}")

    tools = _build_default_tools("http://x", call_tool=fake_call)
    by_name = {t.name: t for t in tools}

    async def run() -> None:
        await by_name["set_output"].ainvoke({"device_id": "gpio23_output", "value": 1})
        await by_name["set_output"].ainvoke({"device_id": "gpio23_output", "value": 0})

    asyncio.run(run())

    list_devices_calls = [n for n in call_log if n == "list_devices"]
    assert len(list_devices_calls) == 1, (
        f"Expected exactly one list_devices round-trip "
        f"(shared device cache); got {len(list_devices_calls)}: {call_log!r}"
    )


@_skip_without_agent_deps
def test_build_default_tools_shares_rate_limiter_across_set_output_calls() -> None:
    """Two back-to-back set_output calls through the wrappers must be separated
    by at least the announced inter-toggle interval.

    Before the fix, each wrapper rebuilt the OutputRateLimiter so _last_call
    was always empty and the per-device interval guard never fired.
    """
    import asyncio  # noqa: PLC0415
    import time  # noqa: PLC0415

    interval_ms = 100
    set_output_times: list[float] = []
    devices = [
        {
            "id": "gpio23_output",
            "name": "GPIO23 Output",
            "kind": "output",
            "capabilities": ["set_output"],
            "state": 0,
        }
    ]

    async def fake_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return {
                "devices": devices,
                "rate_limit": {"output_min_interval_ms": interval_ms},
            }
        if name == "set_output":
            set_output_times.append(time.monotonic())
            return {
                "ok": True,
                "device_id": args["device_id"],
                "value": args["value"],
            }
        raise AssertionError(f"unexpected tool: {name}")

    tools = _build_default_tools("http://x", call_tool=fake_call)
    by_name = {t.name: t for t in tools}

    async def run() -> None:
        await by_name["set_output"].ainvoke({"device_id": "gpio23_output", "value": 1})
        await by_name["set_output"].ainvoke({"device_id": "gpio23_output", "value": 0})

    asyncio.run(run())

    assert len(set_output_times) == 2, (
        f"Expected exactly two set_output calls; got {len(set_output_times)}"
    )
    gap_ms = (set_output_times[1] - set_output_times[0]) * 1000
    # Allow 10 ms tolerance for scheduling jitter.
    assert gap_ms >= interval_ms - 10, (
        f"Inter-toggle gap {gap_ms:.1f} ms < {interval_ms} ms; "
        "the OutputRateLimiter is not shared across wrapper calls."
    )
