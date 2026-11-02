"""Reserve before native IPC, commit once, and never replay an uncertain effect."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from web_hand.domain.dispatch import DispatchIdentity, DispatchReservation


class OutcomeJournal[Outcome](Protocol):
    def reserve(self, identity: DispatchIdentity) -> DispatchReservation[Outcome]: ...
    def commit(self, identity: DispatchIdentity, outcome: Outcome) -> None: ...


class DispatchBrowser[Outcome]:
    def __init__(
        self,
        journal: OutcomeJournal[Outcome],
        stop: Callable[[], Awaitable[None]],
    ) -> None:
        self.journal = journal
        self.stop = stop

    async def execute(
        self,
        identity: DispatchIdentity,
        exchange: Callable[[], Awaitable[Outcome]],
        *,
        deferred: bool,
    ) -> Outcome:
        reservation = self.journal.reserve(identity)
        if reservation.replay:
            return reservation.outcome
        try:
            outcome = await exchange()
            self.journal.commit(identity, outcome)
            return outcome
        except BaseException:
            if not deferred:
                await self.stop()
            raise
