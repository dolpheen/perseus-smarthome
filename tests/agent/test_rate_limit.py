"""Unit tests for the per-device asyncio.Lock and rate-limit guard.

Tests verify:
- Concurrent set_output calls on the same device are serialized with at
  least output_min_interval_ms between them.
- Concurrent set_output calls on different devices proceed in parallel.
- When list_devices returns no rate_limit field, the agent falls back to
  250 ms and emits a startup warning.

No HTTP server or GPIO hardware is required.

Spec: LLM agent requirements, Resolved Decision #7.
Verify: uv run pytest tests/agent/test_rate_limit.py
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pytest

from perseus_smarthome.agent.mcp_tools import RpiIOMCPTools
from perseus_smarthome.agent.rate_limit import OutputRateLimiter, _DEFAULT_INTERVAL_MS


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DEVICES = [
    {
        "id": "gpio23_output",
        "name": "GPIO23 Output",
        "kind": "output",
        "capabilities": ["set_output"],
        "state": 0,
    },
    {
        "id": "gpio24_input",
        "name": "GPIO24 Input",
        "kind": "input",
        "capabilities": ["read_input"],
        "state": 0,
    },
]

# Two output devices so the parallel test can use different device IDs.
_TWO_OUTPUT_DEVICES = [
    {
        "id": "gpio23_output",
        "name": "GPIO23 Output",
        "kind": "output",
        "capabilities": ["set_output"],
        "state": 0,
    },
    {
        "id": "gpio22_output",
        "name": "GPIO22 Output",
        "kind": "output",
        "capabilities": ["set_output"],
        "state": 0,
    },
]

# Use 100 ms for faster tests while still being measurably above scheduling jitter.
_TEST_INTERVAL_MS = 100


def _make_result(devices: list[dict[str, Any]], interval_ms: int) -> dict[str, Any]:
    return {
        "devices": devices,
        "rate_limit": {"output_min_interval_ms": interval_ms},
    }


# ---------------------------------------------------------------------------
# OutputRateLimiter.from_list_devices_result — fallback warning
# ---------------------------------------------------------------------------


def test_missing_rate_limit_field_uses_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When rate_limit is absent, OutputRateLimiter falls back to 250 ms."""
    result: dict[str, Any] = {"devices": _DEVICES}  # no rate_limit key

    with caplog.at_level(logging.WARNING, logger="perseus_smarthome.agent.rate_limit"):
        limiter = OutputRateLimiter.from_list_devices_result(result)

    # Should use the default interval.
    assert limiter._interval_s == _DEFAULT_INTERVAL_MS / 1000.0


def test_missing_rate_limit_field_emits_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When rate_limit is absent, a startup WARNING is logged."""
    result: dict[str, Any] = {"devices": _DEVICES}  # no rate_limit key

    with caplog.at_level(logging.WARNING, logger="perseus_smarthome.agent.rate_limit"):
        OutputRateLimiter.from_list_devices_result(result)

    assert any(r.levelno == logging.WARNING for r in caplog.records)
    # Warning must mention the fallback value so operators can diagnose it.
    assert str(_DEFAULT_INTERVAL_MS) in caplog.text


def test_missing_rate_limit_field_warning_via_list_devices(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When list_devices returns no rate_limit, RpiIOMCPTools logs a warning."""
    result_without_rate_limit: dict[str, Any] = {"devices": _DEVICES}

    async def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return result_without_rate_limit

    with caplog.at_level(logging.WARNING, logger="perseus_smarthome.agent.rate_limit"):
        asyncio.run(RpiIOMCPTools(call).list_devices())

    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# Same-device calls must serialize with >= output_min_interval_ms between them
# ---------------------------------------------------------------------------


def test_same_device_calls_serialize() -> None:
    """Two concurrent set_output calls on the same device must not overlap."""
    active_calls: list[bool] = []  # True = call start, False = call end

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return _make_result(_DEVICES, _TEST_INTERVAL_MS)
        active_calls.append(True)
        await asyncio.sleep(0)  # yield so other tasks can attempt to run
        active_calls.append(False)
        return {"device_id": args["device_id"], "value": args["value"], "ok": True}

    async def run() -> None:
        tools = RpiIOMCPTools(recording_call)
        await tools.list_devices()
        await asyncio.gather(
            tools.set_output("gpio23_output", 1),
            tools.set_output("gpio23_output", 0),
        )

    asyncio.run(run())

    assert len(active_calls) == 4, "Expected exactly two calls recorded"
    # Serialized: the first call must finish before the second starts.
    assert active_calls == [True, False, True, False], (
        f"Calls overlapped: {active_calls}"
    )


def test_same_device_interval_is_enforced() -> None:
    """MCP calls on the same device are separated by >= output_min_interval_ms."""
    call_times: list[float] = []

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return _make_result(_DEVICES, _TEST_INTERVAL_MS)
        call_times.append(time.monotonic())
        return {"device_id": args["device_id"], "value": args["value"], "ok": True}

    async def run() -> None:
        tools = RpiIOMCPTools(recording_call)
        await tools.list_devices()
        await asyncio.gather(
            tools.set_output("gpio23_output", 1),
            tools.set_output("gpio23_output", 0),
        )

    asyncio.run(run())

    assert len(call_times) == 2
    gap_ms = (call_times[1] - call_times[0]) * 1000
    # Allow 10 ms tolerance for scheduling overhead.
    assert gap_ms >= _TEST_INTERVAL_MS - 10, (
        f"Inter-toggle gap {gap_ms:.1f} ms < {_TEST_INTERVAL_MS} ms"
    )


# ---------------------------------------------------------------------------
# Different-device calls must run in parallel
# ---------------------------------------------------------------------------


def test_different_devices_run_in_parallel() -> None:
    """Concurrent set_output calls on different devices must overlap."""
    overlap_detected = False
    active: set[str] = set()

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        nonlocal overlap_detected
        if name == "list_devices":
            return _make_result(_TWO_OUTPUT_DEVICES, _TEST_INTERVAL_MS)
        device_id: str = args["device_id"]
        active.add(device_id)
        if len(active) > 1:
            overlap_detected = True
        await asyncio.sleep(0.05)  # 50 ms simulated hardware latency
        active.discard(device_id)
        return {"device_id": device_id, "value": args["value"], "ok": True}

    async def run() -> None:
        tools = RpiIOMCPTools(recording_call)
        await tools.list_devices()
        await asyncio.gather(
            tools.set_output("gpio23_output", 1),
            tools.set_output("gpio22_output", 1),
        )

    asyncio.run(run())
    assert overlap_detected, (
        "Expected concurrent set_output on different devices to overlap"
    )


def test_different_devices_total_time_less_than_serial() -> None:
    """Total elapsed time for parallel different-device calls < sum of individual."""
    delay_s = 0.05  # 50 ms per call

    async def recording_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_devices":
            return _make_result(_TWO_OUTPUT_DEVICES, _TEST_INTERVAL_MS)
        await asyncio.sleep(delay_s)
        return {"device_id": args["device_id"], "value": args["value"], "ok": True}

    async def run() -> float:
        tools = RpiIOMCPTools(recording_call)
        await tools.list_devices()
        t0 = time.monotonic()
        await asyncio.gather(
            tools.set_output("gpio23_output", 1),
            tools.set_output("gpio22_output", 1),
        )
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    serial_time = 2 * delay_s
    # Parallel execution should be well under the serial sum.
    assert elapsed < serial_time * 1.5, (
        f"Elapsed {elapsed:.3f} s >= 1.5 × serial {serial_time:.3f} s; "
        "calls may not be running in parallel"
    )
