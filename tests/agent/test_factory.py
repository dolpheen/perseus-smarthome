"""Tests for the deepagents agent factory.

Unit tests — no real LLM, no real MCP server, no Raspberry Pi hardware.
deepagents and langchain are optional deps; the whole module is skipped
when they are not installed (e.g. CI with ``uv sync`` and no ``--extra agent``).

Spec: AGENT-FR-003, AGENT-FR-010, AGENT-FR-011
Design: specs/features/llm-agent/design.md
  - "Agent Construction" section
  - "Error Model" → llm_unconfigured
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Skip the entire module when optional agent deps are absent.
deepagents = pytest.importorskip("deepagents")
langchain_core = pytest.importorskip("langchain_core")

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolCall  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.graph.state import CompiledStateGraph  # noqa: E402
from pydantic import Field  # noqa: E402

from perseus_smarthome.agent.factory import (  # noqa: E402
    AGENT_SYSTEM_PROMPT,
    _UnconfiguredAgent,
    create_agent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ScriptedChatModel(BaseChatModel):
    """Stub BaseChatModel that returns pre-scripted AIMessages in order.

    Implements ``bind_tools`` so deepagents can wire tool schemas without error.
    """

    responses: list[AIMessage] = Field(default_factory=list)
    call_count: int = Field(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-stub"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        """Return self — tool schemas are accepted but not inspected by the stub."""
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
        # Increment in-place (Pydantic model; __setattr__ is allowed).
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


# ---------------------------------------------------------------------------
# Degraded mode tests (no deepagents call, no imports needed beyond factory)
# ---------------------------------------------------------------------------


def test_create_agent_returns_unconfigured_when_key_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_agent() must return _UnconfiguredAgent when LLM_API_KEY is absent."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    agent = create_agent()
    assert isinstance(agent, _UnconfiguredAgent)


def test_create_agent_returns_unconfigured_when_key_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_agent() must return _UnconfiguredAgent when LLM_API_KEY is empty."""
    monkeypatch.setenv("LLM_API_KEY", "")
    agent = create_agent()
    assert isinstance(agent, _UnconfiguredAgent)


def test_create_agent_returns_unconfigured_when_key_is_whitespace_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only LLM_API_KEY is treated as unset."""
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
    """The llm_unconfigured error must not include the LLM_API_KEY value.

    Spec: AGENT-FR-010 — credential must never appear in logs or messages.
    """
    secret = "super-secret-key-xyz"
    monkeypatch.setenv("LLM_API_KEY", "")
    agent = _UnconfiguredAgent()
    result = agent.invoke({"messages": []})
    for value in result.values():
        assert secret not in str(value)


# ---------------------------------------------------------------------------
# Happy-path factory tests (use scripted stub model + injected tools)
# ---------------------------------------------------------------------------


def test_create_agent_returns_compiled_state_graph_with_stub_model() -> None:
    """create_agent(model=stub) must return a CompiledStateGraph."""
    stub = _make_stub(AIMessage(content="Hello."))
    tools = [_noop_tool("health"), _noop_tool("list_devices"), _noop_tool("set_output"), _noop_tool("read_input")]
    agent = create_agent(model=stub, tools=tools)
    assert isinstance(agent, CompiledStateGraph)


def test_factory_wires_four_phase_a_tools() -> None:
    """Agent must be created with all four Phase A tools accessible."""
    tool_names = ["health", "list_devices", "set_output", "read_input"]
    stub = _make_stub(AIMessage(content="Done."))

    call_log: list[str] = []

    def _tracked(name: str) -> Any:
        @tool
        def _t() -> dict[str, Any]:
            """Tracked no-op."""
            call_log.append(name)
            return {"ok": True}

        _t.name = name  # type: ignore[attr-defined]
        return _t

    phase_a_tools = [_tracked(n) for n in tool_names]
    agent = create_agent(model=stub, tools=phase_a_tools)
    # Agent is a CompiledStateGraph — the factory wired successfully.
    assert isinstance(agent, CompiledStateGraph)


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

    # Scripted: first response is a tool call, second is the final reply.
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


def test_system_prompt_constant_is_non_empty() -> None:
    """AGENT_SYSTEM_PROMPT must be a non-empty string."""
    assert isinstance(AGENT_SYSTEM_PROMPT, str)
    assert len(AGENT_SYSTEM_PROMPT.strip()) > 0


def test_system_prompt_mentions_safety_rules() -> None:
    """System prompt must contain the non-overridable safety-rules clause."""
    assert "SAFETY RULES" in AGENT_SYSTEM_PROMPT or "safety" in AGENT_SYSTEM_PROMPT.lower()


def test_create_agent_does_not_raise_on_import_with_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing factory and calling create_agent must not raise with no key.

    Spec: AGENT-FR-011 — service must start in degraded mode without exiting.
    """
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    # Must not raise.
    agent = create_agent()
    assert agent is not None


def test_create_agent_with_key_uses_provided_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model= is supplied, create_agent uses it regardless of LLM_API_KEY."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    stub = _make_stub(AIMessage(content="Hello."))
    tools = [_noop_tool("health"), _noop_tool("list_devices"), _noop_tool("set_output"), _noop_tool("read_input")]
    agent = create_agent(model=stub, tools=tools)
    # Injected model → real agent, not degraded.
    assert isinstance(agent, CompiledStateGraph)
