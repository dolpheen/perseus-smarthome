#!/usr/bin/env python3
"""Interactive multimeter smoke verification for the Raspberry Pi I/O MCP.

Walks the operator step-by-step through GPIO23 output and GPIO24 input
verification using a multimeter. No loopback wiring required. Maps directly
to FR-012 and FR-013 (manual smoke tests) in
``specs/features/rpi-io-mcp/requirements.md``.

Usage:
    RPI_MCP_URL=http://<raspberry-pi-ip>:8000/mcp uv run python tools/smoke_meter.py

The script connects to a running MCP server, drives `set_output` / `read_input`
via the streamable-HTTP MCP contract from PR #5, and pauses at each step for
the operator to confirm the meter reading matches expectation. A summary is
printed at the end.

Wire safety reminders printed inline:
- Black probe: any GND header pin (physical 6, 9, 14, 20, 25, 30, 34, or 39).
- Red probe on physical pin 16 = BCM23 (output under test).
- For the input "drive high" step, briefly bridge BCM24 (physical 18) to a
  3V3 rail (physical 1 or 17). NEVER touch BCM24 to a 5V rail (physical 2
  or 4). 5V on a GPIO input damages the SoC.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    name: str
    expected: str
    operator_pass: bool
    note: str = ""


@dataclass
class Report:
    steps: list[StepResult] = field(default_factory=list)

    def add(self, result: StepResult) -> None:
        self.steps.append(result)
        marker = "PASS" if result.operator_pass else "FAIL"
        print(f"  [{marker}] {result.name}")

    def summary(self) -> int:
        print("\n=========== Summary ===========")
        passed = sum(1 for s in self.steps if s.operator_pass)
        total = len(self.steps)
        for s in self.steps:
            marker = "PASS" if s.operator_pass else "FAIL"
            extra = f" — {s.note}" if s.note else ""
            print(f"  [{marker}] {s.name}{extra}")
        print(f"\n  {passed}/{total} passed")
        return 0 if passed == total else 1


def _prompt_yes(question: str) -> tuple[bool, str]:
    """Prompt operator with a yes/no/note question. Returns (passed, note)."""
    while True:
        ans = input(f"  {question} [y]es / [n]o / [s]kip: ").strip().lower()
        if ans in ("y", "yes"):
            note = input("  Optional note (Enter to skip): ").strip()
            return True, note
        if ans in ("n", "no"):
            note = input("  What did you observe? (Enter to skip): ").strip()
            return False, note
        if ans in ("s", "skip"):
            return False, "skipped"
        print("  Please answer y, n, or s.")


def _wait_for_enter(message: str) -> None:
    input(f"  {message} (press Enter when ready) ")


def _result_dict(result: Any) -> dict[str, Any]:
    if result.structuredContent is not None:
        return result.structuredContent
    if result.content:
        text = result.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Non-JSON content from server: {text!r} ({exc})") from None
    raise RuntimeError(f"CallToolResult has no content: {result!r}")


async def _run_steps(url: str, report: Report) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, timeout=10.0) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Sanity check: server is reachable and reports healthy.
            health = _result_dict(await session.call_tool("health", {}))
            if not health.get("ok"):
                raise RuntimeError(f"Server health failed: {health!r}")
            print(f"  Server: {health.get('service')} via {health.get('transport')}\n")

            # All GPIO23 manipulation runs inside try/finally so that any
            # interruption — Ctrl+C, network error, server restart, an
            # exception inside _prompt_yes / _wait_for_enter — drives GPIO23
            # back to 0 before the script exits. design.md Safety Rules
            # require GPIO23 to not stay driven across operator interruptions.
            try:
                # ---------- Step 1: GPIO23 output, drive LOW ----------
                print("\nStep 1 — GPIO23 drives LOW (~0V)")
                print("  Probe placement:")
                print("    - Black probe: any GND header pin (e.g., physical 6 or 14)")
                print("    - Red probe:   physical pin 16 (BCM23)")
                _wait_for_enter("Probes in place?")
                res = _result_dict(
                    await session.call_tool("set_output", {"device_id": "gpio23_output", "value": 0})
                )
                print(f"  Server response: {res}")
                ok, note = _prompt_yes("Does the meter read approximately 0V (within ±0.1V)?")
                report.add(StepResult("GPIO23 → LOW reads ~0V on meter", "~0V", ok, note))

                # ---------- Step 2: GPIO23 output, drive HIGH ----------
                print("\nStep 2 — GPIO23 drives HIGH (~3.3V)")
                print("  Keep the same probe placement as Step 1.")
                _wait_for_enter("Ready?")
                res = _result_dict(
                    await session.call_tool("set_output", {"device_id": "gpio23_output", "value": 1})
                )
                print(f"  Server response: {res}")
                ok, note = _prompt_yes("Does the meter read approximately 3.3V (within ±0.2V)?")
                report.add(StepResult("GPIO23 → HIGH reads ~3.3V on meter", "~3.3V", ok, note))
            finally:
                # Best-effort reset; suppress any error from the call so the
                # original exception (if any) propagates intact.
                try:
                    await session.call_tool("set_output", {"device_id": "gpio23_output", "value": 0})
                    print("  (GPIO23 reset to 0)")
                except Exception:  # noqa: BLE001 — operator-tool teardown
                    print("  (warning: GPIO23 reset call failed; verify pin state manually)")

            # ---------- Step 3: GPIO24 input, default pull-down reads 0 ----------
            print("\nStep 3 — GPIO24 input, no wiring, internal pull-down reads 0")
            print("  Disconnect anything from BCM24 (physical pin 18). Leave it floating.")
            _wait_for_enter("BCM24 disconnected?")
            res = _result_dict(await session.call_tool("read_input", {"device_id": "gpio24_input"}))
            print(f"  Server response: {res}")
            value = res.get("value")
            ok = res.get("ok") is True and value == 0
            note = "" if ok else f"got value={value!r} (expected 0)"
            report.add(StepResult("GPIO24 floating reads 0 via pull-down", "0", ok, note))

            # ---------- Step 4: GPIO24 input, drive HIGH from 3V3 rail ----------
            print("\nStep 4 — GPIO24 input, briefly bridged to 3V3 reads 1")
            print("  IMPORTANT: bridge BCM24 (physical 18) to a 3V3 rail")
            print("  (physical 1 or 17). NEVER use a 5V rail (physical 2 or 4).")
            _wait_for_enter("BCM24 bridged to 3V3?")
            # Poll up to 5 times so the operator can see the live transition.
            attempts = 5
            high_seen = False
            for i in range(1, attempts + 1):
                res = _result_dict(await session.call_tool("read_input", {"device_id": "gpio24_input"}))
                print(f"  read {i}/{attempts}: {res}")
                if res.get("ok") is True and res.get("value") == 1:
                    high_seen = True
                    break
                await asyncio.sleep(0.5)
            note = "" if high_seen else "never observed value=1 — check the 3V3 bridge"
            report.add(StepResult("GPIO24 bridged to 3V3 reads 1", "1", high_seen, note))

            # ---------- Step 5: GPIO24 input, disconnect → reads 0 again ----------
            print("\nStep 5 — GPIO24 input, disconnect 3V3, reads 0 again")
            _wait_for_enter("BCM24 disconnected from 3V3?")
            attempts = 5
            low_seen = False
            for i in range(1, attempts + 1):
                res = _result_dict(await session.call_tool("read_input", {"device_id": "gpio24_input"}))
                print(f"  read {i}/{attempts}: {res}")
                if res.get("ok") is True and res.get("value") == 0:
                    low_seen = True
                    break
                await asyncio.sleep(0.5)
            note = "" if low_seen else "stayed at 1 — the input may still be connected"
            report.add(StepResult("GPIO24 disconnected returns to 0", "0", low_seen, note))


def main() -> int:
    url = os.environ.get("RPI_MCP_URL")
    if not url:
        print(
            "RPI_MCP_URL is not set.\n"
            "  Run: RPI_MCP_URL=http://<pi-ip>:8000/mcp uv run python tools/smoke_meter.py",
            file=sys.stderr,
        )
        return 2

    print(f"Connecting to MCP server at {url}\n")
    report = Report()
    try:
        asyncio.run(_run_steps(url, report))
    except KeyboardInterrupt:
        print("\nAborted by operator.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — operator-facing tool, surface anything
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
