"""Compatibility composition for durable Access outbox claim and acknowledgement."""

from sqlalchemy.ext.asyncio import AsyncSession

from authorization.application.outbox_delivery import ClaimedEvent as ClaimedEvent
from authorization.application.outbox_delivery import DispatchOutbox
from authorization.application.outbox_delivery import DurableOutboxPublisher as DurableEventSink
from authorization.infrastructure.outbox_delivery import (
    SqlOutboxTransaction,
    SqlOutboxTransactions,
)
from common.platform_db import PlatformDatabase


class OutboxDispatcher:
    def __init__(self, database: PlatformDatabase, sink: DurableEventSink) -> None:
        self.database = database
        self.sink = sink

    @staticmethod
    async def claim(tx: AsyncSession, *, limit: int = 64) -> list[ClaimedEvent]:
        return list(await SqlOutboxTransaction(tx).claim(limit))

    @staticmethod
    async def finish(tx: AsyncSession, event: ClaimedEvent, *, acknowledged: bool) -> bool:
        return await SqlOutboxTransaction(tx).finish(event, acknowledged)

    async def dispatch_once(self, *, limit: int = 64) -> int:
        return await DispatchOutbox(
            SqlOutboxTransactions(self.database),
            self.sink,
        ).execute(limit)
