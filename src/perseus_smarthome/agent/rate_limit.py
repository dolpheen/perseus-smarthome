"""Per-device asyncio.Lock manager and inter-toggle interval guard for set_output.

Serializes outbound ``set_output`` calls per ``device_id`` and enforces a
minimum inter-toggle interval so that rapid-fire or concurrent LLM tool-loop
calls cannot damage hardware.

Spec: LLM agent requirements, Resolved Decision #7 (per-device lock +
250 ms minimum inter-toggle interval).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

_DEFAULT_INTERVAL_MS = 250
_log = logging.getLogger(__name__)


class OutputRateLimiter:
    """Serializes ``set_output`` calls per device and enforces a minimum
    inter-toggle interval.

    Args:
        interval_ms: Minimum milliseconds that must elapse between successive
            ``set_output`` calls for the **same** device.  Calls on different
            devices are not serialized and may proceed in parallel.
    """

    def __init__(self, interval_ms: int) -> None:
        self._interval_s = interval_ms / 1000.0
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}

    @staticmethod
    def _resolve_interval_ms(result: dict[str, Any]) -> int:
        """Extract ``output_min_interval_ms`` from a ``list_devices`` result.

        Logs a warning and returns :data:`_DEFAULT_INTERVAL_MS` when either the
        ``rate_limit`` field or the ``output_min_interval_ms`` key is absent.
        """
        rate_limit = result.get("rate_limit")
        if rate_limit is None:
            _log.warning(
                "list_devices response missing 'rate_limit' field; "
                "falling back to %d ms inter-toggle interval.",
                _DEFAULT_INTERVAL_MS,
            )
            return _DEFAULT_INTERVAL_MS
        interval_ms = rate_limit.get("output_min_interval_ms")
        if interval_ms is None:
            _log.warning(
                "list_devices rate_limit missing 'output_min_interval_ms' key; "
                "falling back to %d ms inter-toggle interval.",
                _DEFAULT_INTERVAL_MS,
            )
            return _DEFAULT_INTERVAL_MS
        return interval_ms

    @classmethod
    def from_list_devices_result(cls, result: dict[str, Any]) -> "OutputRateLimiter":
        """Build from a ``list_devices`` result dict."""
        return cls(cls._resolve_interval_ms(result))

    def update_interval_from_list_devices_result(self, result: dict[str, Any]) -> None:
        """Update the inter-toggle interval from a refreshed ``list_devices`` result.

        Preserves all existing per-device locks and last-call timestamps so
        that an in-flight write is not affected and the interval guard remains
        intact across device-list refreshes.
        """
        self._interval_s = self._resolve_interval_ms(result) / 1000.0

    def _get_lock(self, device_id: str) -> asyncio.Lock:
        if device_id not in self._locks:
            self._locks[device_id] = asyncio.Lock()
        return self._locks[device_id]

    @asynccontextmanager
    async def guard(self, device_id: str) -> AsyncGenerator[None, None]:
        """Async context manager that serializes access per device and enforces
        the minimum inter-toggle interval.

        Acquires the per-device lock, sleeps if necessary to honour the
        minimum interval since the last call to this device, then yields.
        Records the call time on exit so subsequent calls can measure elapsed
        time.
        """
        async with self._get_lock(device_id):
            last = self._last_call.get(device_id, 0.0)
            wait_s = self._interval_s - (time.monotonic() - last)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            try:
                yield
            finally:
                self._last_call[device_id] = time.monotonic()
