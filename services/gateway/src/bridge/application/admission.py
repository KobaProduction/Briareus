"""Seek a fresh bounded current-authority decision for every connection."""

import asyncio
from typing import Protocol

from bridge.domain.admission import ConnectionAdmission, ConnectionDecision


class ConnectionDecisionPort(Protocol):
    async def decide(self, admission: ConnectionAdmission) -> ConnectionDecision: ...


class AuthorizeConnection:
    def __init__(self, decisions: ConnectionDecisionPort | None, timeout: float) -> None:
        self._decisions = decisions
        self._timeout = timeout

    async def execute(self, admission: ConnectionAdmission) -> ConnectionDecision:
        if self._decisions is None:
            return ConnectionDecision.UNAVAILABLE
        try:
            decision: object = await asyncio.wait_for(
                self._decisions.decide(admission), timeout=self._timeout
            )
        except Exception:
            # A malformed or unavailable authenticated owner closes admission.
            # CancelledError deliberately propagates: client cancellation must
            # not continue forwarding or acquire a cached admission.
            return ConnectionDecision.UNAVAILABLE
        if not isinstance(decision, ConnectionDecision):
            return ConnectionDecision.UNAVAILABLE
        return decision
