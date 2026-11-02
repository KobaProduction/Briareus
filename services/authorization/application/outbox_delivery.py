"""Commit a claim before publication, then settle in a separate transaction."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from authorization.domain.outbox_delivery import ClaimedEvent as ClaimedEvent
from authorization.domain.outbox_delivery import require_outbox_limit


class DurableOutboxPublisher(Protocol):
    async def publish(self, event: ClaimedEvent) -> bool: ...


class OutboxTransaction(Protocol):
    async def claim(self, limit: int) -> tuple[ClaimedEvent, ...]: ...

    async def finish(self, event: ClaimedEvent, acknowledged: bool) -> bool: ...


class OutboxTransactions(Protocol):
    def open(self) -> AbstractAsyncContextManager[OutboxTransaction]: ...


class DispatchOutbox:
    def __init__(self, transactions: OutboxTransactions, publisher: DurableOutboxPublisher) -> None:
        self._transactions = transactions
        self._publisher = publisher

    async def execute(self, limit: int) -> int:
        require_outbox_limit(limit)
        async with self._transactions.open() as transaction:
            batch = await transaction.claim(limit)
        acknowledged = 0
        for event in batch:
            try:
                durable_ack = await self._publisher.publish(event)
            except Exception:
                durable_ack = False
            async with self._transactions.open() as transaction:
                settled = await transaction.finish(event, durable_ack)
            if settled:
                acknowledged += 1
        return acknowledged
