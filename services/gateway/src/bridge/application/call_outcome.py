"""Deliver bounded outcome diagnostics without retrying or changing an executed reply."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from bridge.domain.call_outcome import CallObservation, CallOutcome, call_outcome

LOG = logging.getLogger(__name__)


@runtime_checkable
class CallOutcomePort(Protocol):
    async def record_call(self, *, permit: str, status: CallOutcome, duration_ms: int) -> None: ...


class RecordCallOutcome:
    def __init__(
        self, authority: CallOutcomePort, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._authority, self._clock = authority, clock

    async def execute(self, permit: str, observation: CallObservation, started: float) -> None:
        try:
            async with asyncio.timeout(2):
                await self._authority.record_call(
                    permit=permit,
                    status=call_outcome(observation),
                    duration_ms=min(86400000, round((self._clock() - started) * 1000)),
                )
        except Exception:
            LOG.warning("MCP call journal delivery unavailable")
