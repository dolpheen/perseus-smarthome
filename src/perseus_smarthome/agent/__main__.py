"""Entrypoint for the agent chat service (``rpi-io-agent`` systemd unit).

Reads configuration from environment variables (loaded from
``/etc/perseus-smarthome/agent.env`` via systemd ``EnvironmentFile``):

  AGENT_CHAT_HOST    default 0.0.0.0
  AGENT_CHAT_PORT    default 8765
  OPENROUTER_API_KEY preferred for the default OpenRouter live LLM
  OPENAI_API_KEY     accepted for OpenAI-compatible providers
                     (legacy LLM_API_KEY is also accepted). Service starts in
                     degraded mode when no provider key is present.

Spec: AGENT-FR-001, AGENT-FR-002, AGENT-FR-003
Design: specs/features/llm-agent/design.md  "Deployment"
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys


def main() -> None:
    """Start the agent chat service."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Lazy import: websockets and deepagents live in [agent] extras.
    try:
        from perseus_smarthome.agent.chat_service import ChatService
        from perseus_smarthome.agent.factory import create_agent
    except ImportError as exc:
        print(
            f"Missing dependencies: {exc}\n"
            "Install the [agent] extras with:  uv sync --extra agent",
            file=sys.stderr,
        )
        sys.exit(1)

    host = os.environ.get("AGENT_CHAT_HOST", "0.0.0.0")
    port = int(os.environ.get("AGENT_CHAT_PORT", "8765"))

    service = ChatService(
        agent_factory=create_agent,
        host=host,
        port=port,
    )

    # Install SIGTERM handler so systemd stop/restart cycles shut down cleanly.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
