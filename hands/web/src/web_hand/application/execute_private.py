"""Reserve one private browser effect before dispatch, preserving unknown outcomes."""

from dataclasses import dataclass
from typing import Protocol

from web_hand.domain.private_effect import PrivateBrowserOperation


@dataclass(frozen=True, slots=True)
class UnknownBrowserOutcome:
    """A durable reservation has no confirmed outcome; execution must not be replayed."""


@dataclass(frozen=True, slots=True)
class StoredBrowserOperation[Outcome]:
    fingerprint: str
    reply: Outcome | None


class BrowserOperationHistory[Outcome](Protocol):
    async def load(
        self, operation: PrivateBrowserOperation
    ) -> StoredBrowserOperation[Outcome] | None: ...
    async def reserve(self, operation: PrivateBrowserOperation) -> None: ...
    async def complete(self, operation: PrivateBrowserOperation, reply: Outcome) -> None: ...


class PrivateBrowser[Outcome](Protocol):
    async def inspect(self, operation: PrivateBrowserOperation) -> Outcome: ...
    def now(self) -> float: ...


class ExecutePrivateBrowser[Outcome]:
    def __init__(
        self, history: BrowserOperationHistory[Outcome], browser: PrivateBrowser[Outcome]
    ) -> None:
        self._history = history
        self._browser = browser

    async def execute(self, operation: PrivateBrowserOperation) -> Outcome | UnknownBrowserOutcome:
        previous = await self._history.load(operation)
        if previous is not None:
            operation.require_fingerprint(previous.fingerprint)
            operation.require_output_authority(self._browser.now())
            return previous.reply if previous.reply is not None else UnknownBrowserOutcome()
        await self._history.reserve(operation)
        operation.require_output_authority(self._browser.now())
        reply = await self._browser.inspect(operation)
        operation.require_output_authority(self._browser.now())
        await self._history.complete(operation, reply)
        operation.require_output_authority(self._browser.now())
        return reply
