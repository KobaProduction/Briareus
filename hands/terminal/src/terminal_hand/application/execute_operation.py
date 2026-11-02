"""Durably reserve an effect before dispatch; replay never executes twice."""

from dataclasses import dataclass
from typing import Protocol

from terminal_hand.domain.operation import OperationIdentity


@dataclass(frozen=True, slots=True)
class UnknownOperationOutcome:
    """A reservation survived without a confirmed reply; never replay its effect."""


@dataclass(frozen=True)
class StoredOperation[Outcome]:
    fingerprint: str
    reply: Outcome | None


class OperationHistory[Outcome](Protocol):
    def load(self, identity: OperationIdentity) -> StoredOperation[Outcome] | None: ...
    def reserve(self, identity: OperationIdentity) -> None: ...
    def complete(self, identity: OperationIdentity, reply: Outcome) -> None: ...


class OperationWorker[Outcome](Protocol):
    def authority_current(self) -> bool: ...
    async def prepare(self) -> None: ...
    async def stop(self) -> None: ...
    async def dispatch(self) -> Outcome: ...


class ExecuteOperation[Outcome]:
    def __init__(
        self, history: OperationHistory[Outcome], worker: OperationWorker[Outcome]
    ) -> None:
        self._history, self._worker = history, worker

    async def execute(self, identity: OperationIdentity) -> Outcome | UnknownOperationOutcome:
        previous = self._history.load(identity)
        if previous is not None:
            identity.require_fingerprint(previous.fingerprint)
            return previous.reply if previous.reply is not None else UnknownOperationOutcome()
        if not self._worker.authority_current():
            raise ValueError("Current Core authority expired before dispatch")
        self._history.reserve(identity)
        await self._worker.prepare()
        if not self._worker.authority_current():
            await self._worker.stop()
            raise ValueError("Core authority expired while preparing execution")
        reply = await self._worker.dispatch()
        self._history.complete(identity, reply)
        return reply
